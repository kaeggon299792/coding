"""Dashboard-integrated tips board routes."""

import hashlib
import mimetypes
import os
import sqlite3
import uuid
from pathlib import Path
from urllib.parse import urlparse

from flask import (
    Blueprint, abort, flash, g, redirect, render_template, request, send_file,
    session, url_for,
)
from werkzeug.utils import secure_filename

import config
from auth import admin_required, login_required, validate_csrf
from extensions import dashboard_db
from services import comment_notifications, content_translation, security_audit, tips_content
from utils import now_kst


tips_bp = Blueprint("tips", __name__, url_prefix="/resources")
ALLOWED_EXTENSIONS = {
    ".png", ".jpg", ".jpeg", ".gif", ".webp", ".pdf", ".xlsx", ".xlsm",
    ".docx", ".pptx", ".txt", ".csv", ".zip",
}


def _snippet(text, limit=170):
    compact = " ".join((text or "").split())
    if len(compact) <= limit:
        return compact
    return f"{compact[:limit].rsplit(' ', 1)[0]}…"


def _is_admin():
    return session.get("role") == "admin"


def _active_tip_categories(connection, include=()):
    names = [
        row["name"] for row in connection.execute(
            """SELECT name FROM tips_categories WHERE is_active=1
               ORDER BY sort_order, name COLLATE NOCASE"""
        ).fetchall()
    ]
    return tuple(dict.fromkeys((*names, *(name for name in include if name))))


def _tip_category_name(raw_name):
    name = " ".join((raw_name or "").split()).strip()
    if not name:
        raise ValueError("카테고리명을 입력해주세요.")
    if len(name) > 80:
        raise ValueError("카테고리명은 80자 이하로 입력해주세요.")
    return name


def _validate_tip_category(connection, name, include=()):
    allowed = _active_tip_categories(connection, include=include)
    if name not in allowed:
        raise ValueError("현재 사용할 수 없는 카테고리입니다.")


def _site_form_values():
    title = request.form.get("title", "").strip()
    site_url = request.form.get("url", "").strip()
    description = request.form.get("description", "").strip()
    category = request.form.get("category", "기타").strip() or "기타"
    tags = request.form.get("tags", "").strip()
    if not title:
        raise ValueError("사이트명을 입력해주세요.")
    parsed = urlparse(site_url)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        raise ValueError("http:// 또는 https://로 시작하는 올바른 주소를 입력해주세요.")
    return {
        "title": title[:150], "url": site_url[:1000],
        "description": description[:1000], "category": category[:50],
        "tags": tags[:300], "is_pinned": request.form.get("is_pinned") == "1",
        "is_public": request.form.get("is_public", "1") == "1",
    }


def _site_categories(connection):
    names = [
        row["name"] for row in connection.execute(
            "SELECT name FROM related_site_categories "
            "WHERE is_active=1 ORDER BY name COLLATE NOCASE"
        ).fetchall()
    ]
    return tuple(dict.fromkeys(names))


def _glossary_form_values():
    category = request.form.get("category", "").strip().lower()
    term_ko = " ".join(request.form.get("term_ko", "").split()).strip()
    term_en = " ".join(request.form.get("term_en", "").split()).strip()
    definition = request.form.get("definition", "").strip()
    easy_explanation = request.form.get("easy_explanation", "").strip()
    aliases = ", ".join(
        part.strip() for part in request.form.get("aliases", "").split(",")
        if part.strip()
    )
    if category not in {"game", "business"}:
        raise ValueError("카테고리를 선택해주세요.")
    if not term_ko or not definition or not easy_explanation:
        raise ValueError("용어, 기본 의미, 쉽게 풀어쓴 설명은 필수입니다.")
    if len(term_ko) > 100 or len(term_en) > 150:
        raise ValueError("용어명이 너무 깁니다.")
    if len(definition) > 2000 or len(easy_explanation) > 2000 or len(aliases) > 500:
        raise ValueError("설명 또는 유의어가 허용 길이를 초과했습니다.")
    return {
        "category": category,
        "term_ko": term_ko,
        "term_en": term_en,
        "definition": definition,
        "easy_explanation": easy_explanation,
        "aliases": aliases,
        "is_public": request.form.get("is_public", "1") == "1",
    }


def _ensure_unique_glossary_term(connection, term_ko, *, exclude_id=None):
    duplicate = connection.execute(
        """SELECT id FROM casino_glossary_terms
           WHERE is_deleted=0 AND term_ko=? COLLATE NOCASE
             AND (? IS NULL OR id<>?)""",
        (term_ko, exclude_id, exclude_id),
    ).fetchone()
    if duplicate:
        raise ValueError("이미 등록된 용어입니다.")


def _ensure_site_category(connection, category):
    connection.execute(
        """
        INSERT OR IGNORE INTO related_site_categories
            (name, created_by, created_at, is_active)
        VALUES (?, ?, ?, 1)
        """,
        (
            category, session.get("user_id"),
            now_kst().isoformat(timespec="seconds"),
        ),
    )


def _form_values():
    return {
        "title": request.form.get("title", ""),
        "slug": request.form.get("slug", ""),
        "summary": request.form.get("summary", ""),
        "body": request.form.get("body", ""),
        "category": request.form.get("category", "기타"),
        "tags": request.form.get("tags", ""),
        "published_date": request.form.get("published_date", ""),
        "cover_image": request.form.get("cover_image", ""),
        "featured": request.form.get("featured") == "1",
        "draft": request.form.get("draft") == "1",
    }


def _save_attachments(connection, tip_id):
    root = Path(config.TIPS_ATTACHMENT_DIR)
    root.mkdir(parents=True, exist_ok=True)
    for uploaded in request.files.getlist("attachments"):
        if not uploaded or not uploaded.filename:
            continue
        original = secure_filename(uploaded.filename)
        suffix = Path(original).suffix.lower()
        if not original or suffix not in ALLOWED_EXTENSIONS:
            raise ValueError(f"허용되지 않는 첨부파일 형식입니다: {uploaded.filename}")
        uploaded.stream.seek(0, os.SEEK_END)
        size = uploaded.stream.tell()
        uploaded.stream.seek(0)
        if size > config.TIPS_MAX_ATTACHMENT_BYTES:
            raise ValueError(f"첨부파일은 개별 {config.TIPS_MAX_ATTACHMENT_BYTES // 1048576}MB 이하만 가능합니다.")
        stored = f"{uuid.uuid4().hex}{suffix}"
        destination = root / stored
        uploaded.save(destination)
        digest = hashlib.sha256(destination.read_bytes()).hexdigest()
        connection.execute(
            """INSERT INTO tips_attachments
               (tip_id, original_filename, stored_filename, mime_type, file_size,
                sha256, uploaded_by, created_at, is_deleted)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, 0)""",
            (tip_id, original, stored,
             uploaded.mimetype or mimetypes.guess_type(original)[0],
             size, digest, session.get("user_id"),
             now_kst().isoformat(timespec="seconds")),
        )
    connection.commit()


@tips_bp.route("")
def list_page():
    query = request.args.get("q", "").strip()
    category = request.args.get("category", "").strip()
    connection = dashboard_db()
    try:
        items = tips_content.list_tips(
            connection, query, category, include_drafts=_is_admin()
        )
        if g.locale == "en":
            items = content_translation.apply_cached(connection, "tip", items)
        existing_categories = [
            row["category"] for row in connection.execute(
                """SELECT DISTINCT category FROM tips_articles
                   WHERE is_deleted=0 AND category<>'' ORDER BY category"""
            ).fetchall()
        ]
        categories = tuple(dict.fromkeys((
            *_active_tip_categories(connection), *existing_categories
        )))
    finally:
        connection.close()
    return render_template(
        "tips/list.html", tips=items, query=query, selected_category=category,
        categories=categories,
    )


@tips_bp.route("/glossary", methods=["GET", "POST"])
def glossary_page():
    connection = dashboard_db()
    try:
        if request.method == "POST":
            if not _is_admin():
                abort(403)
            if not validate_csrf(request.form.get("csrf_token")):
                abort(400)
            try:
                values = _glossary_form_values()
                _ensure_unique_glossary_term(connection, values["term_ko"])
                timestamp = now_kst().isoformat(timespec="seconds")
                connection.execute(
                    """
                    INSERT INTO casino_glossary_terms
                        (category, term_ko, term_en, definition, easy_explanation,
                         aliases, is_public, created_by, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        values["category"], values["term_ko"], values["term_en"],
                        values["definition"], values["easy_explanation"],
                        values["aliases"], 1 if values["is_public"] else 0,
                        session.get("user_id"), timestamp, timestamp,
                    ),
                )
                connection.commit()
            except ValueError as exc:
                flash(str(exc), "error")
                return redirect(url_for("tips.glossary_page"))
            except sqlite3.IntegrityError:
                flash("이미 등록된 용어입니다.", "error")
                return redirect(url_for("tips.glossary_page"))
            flash("카지노 용어를 등록했습니다.", "success")
            return redirect(url_for("tips.glossary_page"))

        query = request.args.get("q", "").strip()
        category = request.args.get("category", "").strip().lower()
        if category not in {"", "game", "business"}:
            category = ""
        conditions = ["is_deleted=0"]
        params = []
        if not _is_admin():
            conditions.append("is_public=1")
        if category:
            conditions.append("category=?")
            params.append(category)
        if query:
            like = f"%{query}%"
            conditions.append(
                "(term_ko LIKE ? OR term_en LIKE ? OR definition LIKE ? "
                "OR easy_explanation LIKE ? OR aliases LIKE ?)"
            )
            params.extend([like] * 5)
        terms = [
            dict(row) for row in connection.execute(
                f"SELECT * FROM casino_glossary_terms WHERE {' AND '.join(conditions)} "
                "ORDER BY CASE category WHEN 'game' THEN 0 ELSE 1 END, term_ko",
                params,
            ).fetchall()
        ]
        return render_template(
            "tips/glossary.html", terms=terms, query=query,
            selected_category=category,
        )
    finally:
        connection.close()


@tips_bp.post("/glossary/<int:term_id>/edit")
@admin_required
def edit_glossary_page(term_id):
    if not validate_csrf(request.form.get("csrf_token")):
        abort(400)
    try:
        values = _glossary_form_values()
    except ValueError as exc:
        flash(str(exc), "error")
        return redirect(url_for("tips.glossary_page"))
    connection = dashboard_db()
    try:
        _ensure_unique_glossary_term(
            connection, values["term_ko"], exclude_id=term_id
        )
        cursor = connection.execute(
            """
            UPDATE casino_glossary_terms SET
                category=?, term_ko=?, term_en=?, definition=?,
                easy_explanation=?, aliases=?, is_public=?, updated_at=?
            WHERE id=? AND is_deleted=0
            """,
            (
                values["category"], values["term_ko"], values["term_en"],
                values["definition"], values["easy_explanation"], values["aliases"],
                1 if values["is_public"] else 0,
                now_kst().isoformat(timespec="seconds"), term_id,
            ),
        )
        if not cursor.rowcount:
            abort(404)
        connection.commit()
    except (ValueError, sqlite3.IntegrityError):
        connection.rollback()
        flash("이미 등록된 용어입니다.", "error")
        return redirect(url_for("tips.glossary_page"))
    finally:
        connection.close()
    flash("카지노 용어를 수정했습니다.", "success")
    return redirect(url_for("tips.glossary_page"))


@tips_bp.post("/glossary/<int:term_id>/delete")
@admin_required
def delete_glossary_page(term_id):
    if not validate_csrf(request.form.get("csrf_token")):
        abort(400)
    connection = dashboard_db()
    try:
        timestamp = now_kst().isoformat(timespec="seconds")
        cursor = connection.execute(
            """UPDATE casino_glossary_terms
               SET is_deleted=1, deleted_at=?, updated_at=?
               WHERE id=? AND is_deleted=0""",
            (timestamp, timestamp, term_id),
        )
        if not cursor.rowcount:
            abort(404)
        connection.commit()
    finally:
        connection.close()
    flash("카지노 용어를 삭제했습니다.", "success")
    return redirect(url_for("tips.glossary_page"))


@tips_bp.route("/sites", methods=["GET", "POST"])
def sites_page():
    connection = dashboard_db()
    try:
        if request.method == "POST":
            if not _is_admin():
                abort(403)
            if not validate_csrf(request.form.get("csrf_token")):
                abort(400)
            try:
                values = _site_form_values()
            except ValueError as exc:
                flash(str(exc), "error")
                return redirect(url_for("tips.sites_page"))
            timestamp = now_kst().isoformat(timespec="seconds")
            _ensure_site_category(connection, values["category"])
            connection.execute(
                """
                INSERT INTO related_sites (
                    title, url, description, category, tags, is_pinned,
                    is_public, created_by, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    values["title"], values["url"], values["description"],
                    values["category"], values["tags"],
                    1 if values["is_pinned"] else 0,
                    1 if values["is_public"] else 0,
                    session.get("user_id"), timestamp, timestamp,
                ),
            )
            connection.commit()
            flash("관련 사이트를 등록했습니다.", "success")
            return redirect(url_for("tips.sites_page"))

        query = request.args.get("q", "").strip()
        category = request.args.get("category", "").strip()
        conditions = ["is_deleted=0"]
        params = []
        if not _is_admin():
            conditions.append("is_public=1")
        if query:
            like = f"%{query}%"
            conditions.append(
                "(title LIKE ? OR description LIKE ? OR tags LIKE ? OR url LIKE ?)"
            )
            params.extend([like] * 4)
        if category:
            conditions.append("category=?")
            params.append(category)
        sites = [
            dict(row) for row in connection.execute(
                f"SELECT * FROM related_sites WHERE {' AND '.join(conditions)} "
                "ORDER BY is_pinned DESC, updated_at DESC, id DESC",
                params,
            ).fetchall()
        ]
        if g.locale == "en":
            sites = content_translation.apply_cached(connection, "related_site", sites)
        categories = _site_categories(connection)
        return render_template(
            "tips/sites.html", sites=sites, query=query,
            selected_category=category, categories=categories,
        )
    finally:
        connection.close()


@tips_bp.post("/sites/<int:site_id>/edit")
@admin_required
def edit_site_page(site_id):
    if not validate_csrf(request.form.get("csrf_token")):
        abort(400)
    try:
        values = _site_form_values()
    except ValueError as exc:
        flash(str(exc), "error")
        return redirect(url_for("tips.sites_page"))
    connection = dashboard_db()
    try:
        _ensure_site_category(connection, values["category"])
        cursor = connection.execute(
            """
            UPDATE related_sites SET
                title=?, url=?, description=?, category=?, tags=?,
                is_pinned=?, is_public=?, updated_at=?
            WHERE id=? AND is_deleted=0
            """,
            (
                values["title"], values["url"], values["description"],
                values["category"], values["tags"],
                1 if values["is_pinned"] else 0,
                1 if values["is_public"] else 0,
                now_kst().isoformat(timespec="seconds"), site_id,
            ),
        )
        if not cursor.rowcount:
            abort(404)
        connection.commit()
    finally:
        connection.close()
    flash("관련 사이트를 수정했습니다.", "success")
    return redirect(url_for("tips.sites_page"))


@tips_bp.post("/sites/categories")
@admin_required
def add_site_category_page():
    if not validate_csrf(request.form.get("csrf_token")):
        abort(400)
    name = " ".join(request.form.get("name", "").split()).strip()
    if not name:
        flash("카테고리명을 입력해주세요.", "error")
        return redirect(url_for("tips.sites_page"))
    if len(name) > 50:
        flash("카테고리명은 50자 이하로 입력해주세요.", "error")
        return redirect(url_for("tips.sites_page"))
    connection = dashboard_db()
    try:
        before = connection.total_changes
        _ensure_site_category(connection, name)
        connection.commit()
        created = connection.total_changes > before
    finally:
        connection.close()
    flash(
        "카테고리를 추가했습니다." if created else "이미 등록된 카테고리입니다.",
        "success" if created else "info",
    )
    return redirect(url_for("tips.sites_page"))


@tips_bp.post("/sites/<int:site_id>/delete")
@admin_required
def delete_site_page(site_id):
    if not validate_csrf(request.form.get("csrf_token")):
        abort(400)
    connection = dashboard_db()
    try:
        cursor = connection.execute(
            "UPDATE related_sites SET is_deleted=1, deleted_at=?, updated_at=? "
            "WHERE id=? AND is_deleted=0",
            (
                now_kst().isoformat(timespec="seconds"),
                now_kst().isoformat(timespec="seconds"), site_id,
            ),
        )
        if not cursor.rowcount:
            abort(404)
        connection.commit()
    finally:
        connection.close()
    flash("관련 사이트를 삭제했습니다.", "success")
    return redirect(url_for("tips.sites_page"))


@tips_bp.route("/trash")
@admin_required
def trash_page():
    connection = dashboard_db()
    try:
        items = tips_content.list_tips(
            connection, include_drafts=True, include_deleted=True
        )
        items = [item for item in items if item["is_deleted"]]
    finally:
        connection.close()
    return render_template("tips/trash.html", tips=items)


@tips_bp.route("/categories", methods=["GET", "POST"])
@admin_required
def categories_page():
    connection = dashboard_db()
    try:
        if request.method == "POST":
            if not validate_csrf(request.form.get("csrf_token")):
                abort(400)
            try:
                name = _tip_category_name(request.form.get("name"))
                connection.execute(
                    """INSERT INTO tips_categories
                       (name, sort_order, is_active, created_at, updated_at)
                       VALUES (?, COALESCE((SELECT MAX(sort_order) + 1 FROM tips_categories), 1),
                               1, ?, ?)""",
                    (name, now_kst().isoformat(), now_kst().isoformat()),
                )
                security_audit.log_event(
                    connection, "TIPS_CATEGORY_CREATE", "tips_category",
                    connection.execute("SELECT last_insert_rowid()").fetchone()[0],
                    {"name": name},
                )
                connection.commit()
                flash("자료실 카테고리를 추가했습니다.", "success")
                return redirect(url_for("tips.categories_page"))
            except sqlite3.IntegrityError:
                connection.rollback()
                flash("이미 등록된 카테고리입니다.", "error")
            except ValueError as exc:
                connection.rollback()
                flash(str(exc), "error")
        categories = [
            dict(row) for row in connection.execute(
                """SELECT category.*,
                          (SELECT COUNT(*) FROM tips_articles AS article
                           WHERE article.category=category.name
                             AND article.is_deleted=0
                             AND article.draft=0) AS article_count
                   FROM tips_categories AS category
                   ORDER BY category.sort_order, category.name COLLATE NOCASE"""
            ).fetchall()
        ]
    finally:
        connection.close()
    return render_template("tips/categories.html", categories=categories)


@tips_bp.post("/categories/<int:category_id>/rename")
@admin_required
def rename_category_page(category_id):
    if not validate_csrf(request.form.get("csrf_token")):
        abort(400)
    connection = dashboard_db()
    try:
        category = connection.execute(
            "SELECT * FROM tips_categories WHERE id=?", (category_id,)
        ).fetchone()
        if not category:
            abort(404)
        try:
            name = _tip_category_name(request.form.get("name"))
            connection.execute(
                "UPDATE tips_articles SET category=?, updated_at=? WHERE category=?",
                (name, now_kst().isoformat(), category["name"]),
            )
            connection.execute(
                "UPDATE tips_categories SET name=?, updated_at=? WHERE id=?",
                (name, now_kst().isoformat(), category_id),
            )
            security_audit.log_event(
                connection, "TIPS_CATEGORY_RENAME", "tips_category", category_id,
                {"before": category["name"], "after": name},
            )
            connection.commit()
        except sqlite3.IntegrityError:
            connection.rollback()
            flash("이미 등록된 카테고리입니다.", "error")
            return redirect(url_for("tips.categories_page"))
        except ValueError as exc:
            connection.rollback()
            flash(str(exc), "error")
            return redirect(url_for("tips.categories_page"))
    finally:
        connection.close()
    flash("카테고리명과 기존 자료를 함께 변경했습니다.", "success")
    return redirect(url_for("tips.categories_page"))


@tips_bp.post("/categories/<int:category_id>/toggle")
@admin_required
def toggle_category_page(category_id):
    if not validate_csrf(request.form.get("csrf_token")):
        abort(400)
    connection = dashboard_db()
    try:
        category = connection.execute(
            "SELECT * FROM tips_categories WHERE id=?", (category_id,)
        ).fetchone()
        if not category:
            abort(404)
        next_active = 0 if category["is_active"] else 1
        if not next_active:
            active_count = connection.execute(
                "SELECT COUNT(*) FROM tips_categories WHERE is_active=1"
            ).fetchone()[0]
            if active_count <= 1:
                flash("최소 한 개의 활성 카테고리는 남겨야 합니다.", "error")
                return redirect(url_for("tips.categories_page"))
        connection.execute(
            "UPDATE tips_categories SET is_active=?, updated_at=? WHERE id=?",
            (next_active, now_kst().isoformat(), category_id),
        )
        security_audit.log_event(
            connection, "TIPS_CATEGORY_TOGGLE", "tips_category", category_id,
            {"is_active": bool(next_active)},
        )
        connection.commit()
    finally:
        connection.close()
    flash("카테고리를 다시 표시했습니다." if next_active else "카테고리를 새 글 선택 목록에서 숨겼습니다.", "success")
    return redirect(url_for("tips.categories_page"))


@tips_bp.route("/new", methods=["GET", "POST"])
@admin_required
def new_page():
    if request.method == "POST":
        if not validate_csrf(request.form.get("csrf_token")):
            abort(400)
        values = _form_values()
        connection = dashboard_db()
        try:
            categories = _active_tip_categories(connection)
            _validate_tip_category(connection, values["category"])
            item = tips_content.save_tip(
                connection, values, session.get("user_id")
            )
            _save_attachments(connection, item["id"])
        except ValueError as exc:
            connection.rollback()
            flash(str(exc), "error")
            return render_template(
                "tips/form.html", tip=values, categories=categories,
                mode="new",
            ), 400
        finally:
            connection.close()
        flash("자료를 등록했습니다.", "success")
        return redirect(url_for("tips.detail_page", slug=item["slug"]))
    connection = dashboard_db()
    try:
        categories = _active_tip_categories(connection)
    finally:
        connection.close()
    return render_template("tips/form.html", tip={}, categories=categories, mode="new")


@tips_bp.route("/<slug>")
def detail_page(slug):
    connection = dashboard_db()
    try:
        item = tips_content.get_tip(
            connection, slug, include_drafts=_is_admin()
        )
        if not item:
            abort(404)
        viewed = set(session.get("viewed_tips", []))
        if item["id"] not in viewed:
            tips_content.increment_view(connection, item["id"])
            item["view_count"] += 1
            viewed.add(item["id"])
            session["viewed_tips"] = list(viewed)[-100:]
        files = tips_content.attachments(connection, item["id"])
        item_comments = tips_content.comments(connection, item["id"])
        previous, following = tips_content.adjacent_tips(connection, item)
        if g.locale == "en":
            item = content_translation.apply_one(connection, "tip", item)
            item_comments = content_translation.apply_cached(
                connection, "tip_comment", item_comments
            )
        rendered = tips_content.render_markdown(item["body"])
    finally:
        connection.close()
    public_url = config.DASHBOARD_PUBLIC_URL.rstrip("/")
    article_url = f"{public_url}{url_for('tips.detail_page', slug=item['slug'])}"
    logo_url = f"{public_url}{url_for('static', filename='img/casino-in-logo.png')}"
    return render_template(
        "tips/detail.html", tip=item, rendered_body=rendered,
        attachments=files, comments=item_comments,
        previous_tip=previous, next_tip=following,
        seo_title=f"{item['title']} | Casino IN",
        seo_description=_snippet(item.get("summary") or item.get("body") or ""),
        seo_og_title=f"{item['title']} | Casino IN",
        seo_og_description=_snippet(item.get("summary") or item.get("body") or ""),
        seo_og_type="article",
        seo_json_ld=[{
            "@context": "https://schema.org",
            "@type": "Article",
            "headline": item["title"],
            "description": _snippet(item.get("summary") or item.get("body") or ""),
            "datePublished": item.get("published_date"),
            "dateModified": (item.get("updated_at") or item.get("updated_date") or item.get("published_date")),
            "mainEntityOfPage": {
                "@type": "WebPage",
                "@id": article_url,
            },
            "author": {"@type": "Organization", "name": "Casino IN"},
            "publisher": {
                "@type": "Organization",
                "name": "Casino IN",
                "logo": {
                    "@type": "ImageObject",
                    "url": logo_url,
                },
            },
            "image": [logo_url],
        }, {
            "@context": "https://schema.org",
            "@type": "BreadcrumbList",
            "itemListElement": [
                {
                    "@type": "ListItem", "position": 1, "name": "Casino IN",
                    "item": f"{public_url}{url_for('public_home')}",
                },
                {
                    "@type": "ListItem", "position": 2, "name": "자료실",
                    "item": f"{public_url}{url_for('tips.list_page')}",
                },
                {
                    "@type": "ListItem", "position": 3, "name": item["title"],
                    "item": article_url,
                },
            ],
        }],
    )


@tips_bp.post("/<slug>/comments")
@login_required
def add_comment_page(slug):
    if not validate_csrf(request.form.get("csrf_token")):
        abort(400)
    connection = dashboard_db()
    try:
        item = tips_content.get_tip(
            connection, slug, include_drafts=_is_admin()
        )
        if not item:
            abort(404)
        try:
            notification_email = comment_notifications.normalize_email(
                request.form.get("notification_email")
            )
            comment_id = tips_content.add_comment(
                connection, item["id"], session["user_id"],
                request.form.get("content", ""),
            )
            comment = tips_content.get_comment(connection, comment_id)
            comment_notifications.notify_new_comment(
                connection,
                scope_type="tips_article",
                scope_id=item["id"],
                author_id=session["user_id"],
                notification_email=notification_email,
                comment_id=comment_id,
                post_title=item.get("title") or "자료실",
                comment_content=comment.get("content") if comment else "",
                created_at=comment.get("created_at") if comment else now_kst().isoformat(timespec="seconds"),
                post_url=(
                    f"{config.DASHBOARD_PUBLIC_URL.rstrip('/')}"
                    f"{url_for('tips.detail_page', slug=slug)}#comments"
                ),
            )
            flash("댓글을 등록했습니다.", "success")
        except ValueError as exc:
            flash(str(exc), "error")
    finally:
        connection.close()
    return redirect(url_for("tips.detail_page", slug=slug) + "#comments")


@tips_bp.post("/<slug>/comments/<int:comment_id>/edit")
@login_required
def edit_comment_page(slug, comment_id):
    if not validate_csrf(request.form.get("csrf_token")):
        abort(400)
    connection = dashboard_db()
    try:
        item = tips_content.get_tip(
            connection, slug, include_drafts=_is_admin()
        )
        comment = tips_content.get_comment(connection, comment_id)
        if not item or not comment or comment["tip_id"] != item["id"] or comment["is_deleted"]:
            abort(404)
        if comment["author_id"] != session["user_id"] and not _is_admin():
            abort(403)
        try:
            tips_content.update_comment(
                connection, comment_id, request.form.get("content", "")
            )
            flash("댓글을 수정했습니다.", "success")
        except ValueError as exc:
            flash(str(exc), "error")
    finally:
        connection.close()
    return redirect(url_for("tips.detail_page", slug=slug) + "#comments")


@tips_bp.post("/<slug>/comments/<int:comment_id>/delete")
@login_required
def delete_comment_page(slug, comment_id):
    if not validate_csrf(request.form.get("csrf_token")):
        abort(400)
    connection = dashboard_db()
    try:
        item = tips_content.get_tip(
            connection, slug, include_drafts=_is_admin()
        )
        comment = tips_content.get_comment(connection, comment_id)
        if not item or not comment or comment["tip_id"] != item["id"] or comment["is_deleted"]:
            abort(404)
        if comment["author_id"] != session["user_id"] and not _is_admin():
            abort(403)
        tips_content.delete_comment(connection, comment_id, session["user_id"])
        flash("댓글을 삭제했습니다.", "success")
    finally:
        connection.close()
    return redirect(url_for("tips.detail_page", slug=slug) + "#comments")


@tips_bp.route("/<slug>/edit", methods=["GET", "POST"])
@admin_required
def edit_page(slug):
    connection = dashboard_db()
    try:
        item = tips_content.get_tip(
            connection, slug, include_drafts=True, include_deleted=False
        )
        if not item:
            abort(404)
        if request.method == "POST":
            if not validate_csrf(request.form.get("csrf_token")):
                abort(400)
            values = _form_values()
            try:
                categories = _active_tip_categories(
                    connection, include=(item["category"],)
                )
                _validate_tip_category(
                    connection, values["category"], include=(item["category"],)
                )
                item = tips_content.save_tip(
                    connection, values, session.get("user_id"), item["id"]
                )
                _save_attachments(connection, item["id"])
            except ValueError as exc:
                connection.rollback()
                flash(str(exc), "error")
                return render_template(
                    "tips/form.html", tip=values,
                    categories=categories, mode="edit",
                ), 400
            flash("자료를 수정했습니다.", "success")
            return redirect(url_for("tips.detail_page", slug=item["slug"]))
        return render_template(
            "tips/form.html", tip=item,
            categories=_active_tip_categories(
                connection, include=(item["category"],)
            ),
            mode="edit",
        )
    finally:
        connection.close()


@tips_bp.post("/<slug>/delete")
@admin_required
def delete_page(slug):
    if not validate_csrf(request.form.get("csrf_token")):
        abort(400)
    connection = dashboard_db()
    try:
        item = tips_content.get_tip(connection, slug, include_drafts=True)
        if not item:
            abort(404)
        tips_content.soft_delete(connection, item["id"], session.get("user_id"))
    finally:
        connection.close()
    flash("휴지통으로 이동했습니다. 첨부파일은 보존됩니다.", "success")
    return redirect(url_for("tips.list_page"))


@tips_bp.post("/<tip_id>/restore")
@admin_required
def restore_page(tip_id):
    if not validate_csrf(request.form.get("csrf_token")):
        abort(400)
    connection = dashboard_db()
    try:
        if not tips_content.get_tip_by_id(connection, tip_id):
            abort(404)
        tips_content.restore(connection, tip_id)
    finally:
        connection.close()
    flash("자료를 복구했습니다.", "success")
    return redirect(url_for("tips.trash_page"))


@tips_bp.get("/attachment/<int:attachment_id>")
def attachment_file(attachment_id):
    connection = dashboard_db()
    try:
        row = connection.execute(
            """SELECT a.* FROM tips_attachments a
               JOIN tips_articles t ON t.id=a.tip_id
               WHERE a.id=? AND a.is_deleted=0 AND t.is_deleted=0
                 AND (t.draft=0 OR ?)""",
            (attachment_id, 1 if _is_admin() else 0),
        ).fetchone()
        if not row:
            abort(404)
        path = Path(config.TIPS_ATTACHMENT_DIR) / row["stored_filename"]
        if not path.is_file():
            abort(404)
        return send_file(
            path, mimetype=row["mime_type"], as_attachment=True,
            download_name=row["original_filename"],
        )
    finally:
        connection.close()
