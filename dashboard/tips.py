"""Dashboard-integrated tips board routes."""

import hashlib
import mimetypes
import os
import uuid
from pathlib import Path

from flask import (
    Blueprint, abort, flash, redirect, render_template, request, send_file,
    session, url_for,
)
from werkzeug.utils import secure_filename

import config
from auth import admin_required, login_required, validate_csrf
from extensions import dashboard_db
from services import tips_content
from utils import now_kst


tips_bp = Blueprint("tips", __name__, url_prefix="/tips")
ALLOWED_EXTENSIONS = {
    ".png", ".jpg", ".jpeg", ".gif", ".webp", ".pdf", ".xlsx", ".xlsm",
    ".docx", ".pptx", ".txt", ".csv", ".zip",
}


def _is_admin():
    return session.get("role") == "admin"


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
@login_required
def list_page():
    query = request.args.get("q", "").strip()
    category = request.args.get("category", "").strip()
    connection = dashboard_db()
    try:
        items = tips_content.list_tips(
            connection, query, category, include_drafts=_is_admin()
        )
        existing_categories = [
            row["category"] for row in connection.execute(
                """SELECT DISTINCT category FROM tips_articles
                   WHERE is_deleted=0 AND category<>'' ORDER BY category"""
            ).fetchall()
        ]
    finally:
        connection.close()
    categories = tuple(dict.fromkeys(
        (*tips_content.CATEGORIES, *existing_categories)
    ))
    return render_template(
        "tips/list.html", tips=items, query=query, selected_category=category,
        categories=categories,
    )


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


@tips_bp.route("/new", methods=["GET", "POST"])
@admin_required
def new_page():
    if request.method == "POST":
        if not validate_csrf(request.form.get("csrf_token")):
            abort(400)
        values = _form_values()
        connection = dashboard_db()
        try:
            item = tips_content.save_tip(
                connection, values, session.get("user_id")
            )
            _save_attachments(connection, item["id"])
        except ValueError as exc:
            connection.rollback()
            flash(str(exc), "error")
            return render_template(
                "tips/form.html", tip=values, categories=tips_content.CATEGORIES,
                mode="new",
            ), 400
        finally:
            connection.close()
        flash("자료를 등록했습니다.", "success")
        return redirect(url_for("tips.detail_page", slug=item["slug"]))
    return render_template(
        "tips/form.html", tip={}, categories=tips_content.CATEGORIES, mode="new"
    )


@tips_bp.route("/<slug>")
@login_required
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
        previous, following = tips_content.adjacent_tips(connection, item)
        rendered = tips_content.render_markdown(item["body"])
    finally:
        connection.close()
    return render_template(
        "tips/detail.html", tip=item, rendered_body=rendered,
        attachments=files, previous_tip=previous, next_tip=following,
    )


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
                item = tips_content.save_tip(
                    connection, values, session.get("user_id"), item["id"]
                )
                _save_attachments(connection, item["id"])
            except ValueError as exc:
                connection.rollback()
                flash(str(exc), "error")
                return render_template(
                    "tips/form.html", tip=values,
                    categories=tips_content.CATEGORIES, mode="edit",
                ), 400
            flash("자료를 수정했습니다.", "success")
            return redirect(url_for("tips.detail_page", slug=item["slug"]))
        return render_template(
            "tips/form.html", tip=item,
            categories=tuple(dict.fromkeys((
                *tips_content.CATEGORIES, item["category"]
            ))),
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
@login_required
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
