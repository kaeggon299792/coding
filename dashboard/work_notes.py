"""Administrator-only work-note board routes."""

from __future__ import annotations

import mimetypes
import re
import uuid
from pathlib import Path

import bleach
import markdown
from flask import (
    Blueprint, abort, flash, jsonify, redirect, render_template, request,
    send_file, session, url_for,
)
from markupsafe import Markup

import config
from auth import admin_required, get_csrf_token, validate_csrf
from extensions import dashboard_db
from services import editor_images, security_audit, work_notes
from utils import now_kst


work_notes_bp = Blueprint("work_notes", __name__, url_prefix="/blog/work-notes")
ALLOWED_EXTENSIONS = {
    ".pdf", ".doc", ".docx", ".xls", ".xlsx", ".xlsm", ".ppt", ".pptx",
    ".txt", ".csv", ".zip", ".png", ".jpg", ".jpeg", ".gif", ".webp",
}
MARKDOWN_TAGS = {
    "p", "br", "strong", "em", "del", "blockquote", "code", "pre", "ul",
    "ol", "li", "h1", "h2", "h3", "h4", "hr", "table", "thead", "tbody",
    "tr", "th", "td", "a", "img", "input",
}


def render_markdown(value):
    rendered = markdown.markdown(
        value or "", extensions=["fenced_code", "tables", "sane_lists", "nl2br"],
        output_format="html",
    )
    rendered = re.sub(
        r"<li>\s*\[([ xX])\]\s*",
        lambda match: '<li class="task-list-item"><input type="checkbox" disabled{}> '.format(
            " checked" if match.group(1).lower() == "x" else ""
        ),
        rendered,
    )
    return Markup(bleach.clean(
        rendered,
        tags=MARKDOWN_TAGS,
        attributes={
            "a": ["href", "title"], "img": ["src", "alt", "title"],
            "input": ["type", "disabled", "checked"], "li": ["class"],
        },
        protocols={"https", "mailto"}, strip=True,
    ))


def _raw_form():
    keys = (
        "category_id", "title", "content", "work_date", "reminder_date",
        "reminder_time", "target_date", "completed_at", "priority", "status",
        "version_label", "tags", "is_pinned", "recurrence_type",
        "recurrence_interval_days",
    )
    return {key: request.form.get(key, "") for key in keys}


def _default_form():
    return {
        "work_date": now_kst().date().isoformat(), "reminder_time": "08:50",
        "priority": "normal", "status": "planned", "recurrence_type": "none",
        "tags": [],
    }


def _form_context(connection, form_data=None, note=None, error=None):
    return {
        "form_data": form_data or _default_form(), "note": note, "error": error,
        "categories": work_notes.list_categories(connection),
        "statuses": work_notes.STATUSES, "priorities": work_notes.PRIORITIES,
        "recurrences": work_notes.RECURRENCES, "csrf_token": get_csrf_token(),
    }


def _save_file(connection, uploaded, owner_id, note_id=None):
    original = Path(uploaded.filename or "").name.strip()
    suffix = Path(original).suffix.casefold()
    if not original or suffix not in ALLOWED_EXTENSIONS:
        raise ValueError("허용되지 않는 첨부파일 형식입니다.")
    data = uploaded.read(config.WORK_NOTE_MAX_FILE_BYTES + 1)
    if not data:
        raise ValueError("빈 파일은 첨부할 수 없습니다.")
    if len(data) > config.WORK_NOTE_MAX_FILE_BYTES:
        raise ValueError("첨부파일은 개별 20MB 이하만 가능합니다.")
    root = Path(config.WORK_NOTE_FILE_DIR)
    root.mkdir(parents=True, exist_ok=True)
    stored = f"{uuid.uuid4().hex}{suffix}"
    path = root / stored
    path.write_bytes(data)
    try:
        attachment_id = work_notes.register_attachment(
            connection, owner_id, stored, original,
            uploaded.mimetype or mimetypes.guess_type(original)[0], len(data),
            note_id=note_id,
        )
    except Exception:
        path.unlink(missing_ok=True)
        raise
    return attachment_id


@work_notes_bp.route("", methods=["GET"])
@admin_required
def board():
    filters = {
        "status": request.args.get("status", ""),
        "category_id": request.args.get("category", ""),
        "tag": request.args.get("tag", ""),
        "q": request.args.get("q", "")[:100],
        "sort": request.args.get("sort", "created_desc"),
    }
    try:
        page = max(1, int(request.args.get("page", 1)))
    except (TypeError, ValueError):
        page = 1
    page_size = 15
    connection = dashboard_db()
    try:
        total = work_notes.count_notes(connection, filters)
        pages = max(1, (total + page_size - 1) // page_size)
        page = min(page, pages)
        notes = work_notes.list_notes(
            connection, filters, page_size, (page - 1) * page_size
        )
        for note in notes:
            note["content_html"] = render_markdown(note["content"])
        return render_template(
            "work_notes/board.html", notes=notes, total=total, page=page,
            total_pages=pages, filters=filters,
            dashboard=work_notes.dashboard_counts(connection),
            categories=work_notes.list_categories(connection),
            tags=work_notes.available_tags(connection), statuses=work_notes.STATUSES,
            priorities=work_notes.PRIORITIES, sorts={
                "created_desc": "등록순", "work_date_desc": "작성일순",
                "target_asc": "마감 임박순", "priority_desc": "중요도순",
                "status": "상태순",
            }, csrf_token=get_csrf_token(),
        )
    finally:
        connection.close()


@work_notes_bp.route("/new", methods=["GET", "POST"])
@admin_required
def create():
    connection = dashboard_db()
    try:
        if request.method == "GET":
            return render_template("work_notes/form.html", **_form_context(connection))
        raw = _raw_form()
        if not validate_csrf(request.form.get("csrf_token", "")):
            return render_template(
                "work_notes/form.html",
                **_form_context(connection, raw, error="요청이 만료되었습니다. 다시 시도해주세요."),
            ), 400
        saved_paths = []
        try:
            clean = work_notes.clean_form(raw)
            note_id = work_notes.create_note(connection, session["user_id"], clean)
            work_notes.attach_inline_images(connection, note_id, clean["content"], session["user_id"])
            for uploaded in request.files.getlist("attachments"):
                if not uploaded.filename:
                    continue
                attachment_id = _save_file(connection, uploaded, session["user_id"], note_id)
                attachment = work_notes.get_attachment(connection, attachment_id)
                saved_paths.append(Path(config.WORK_NOTE_FILE_DIR) / attachment["stored_name"])
            security_audit.log_event(connection, "WORK_NOTE_CREATE", "work_note", note_id)
            connection.commit()
        except ValueError as error:
            connection.rollback()
            for path in saved_paths:
                path.unlink(missing_ok=True)
            return render_template(
                "work_notes/form.html", **_form_context(connection, raw, error=str(error))
            ), 400
        return redirect(url_for("work_notes.detail", note_id=note_id))
    finally:
        connection.close()


@work_notes_bp.get("/<int:note_id>")
@admin_required
def detail(note_id):
    connection = dashboard_db()
    try:
        note = work_notes.get_note(connection, note_id)
        if not note:
            abort(404)
        return render_template(
            "work_notes/detail.html", note=note,
            note_html=render_markdown(note["content"]),
            statuses=work_notes.STATUSES, priorities=work_notes.PRIORITIES,
            recurrences=work_notes.RECURRENCES, csrf_token=get_csrf_token(),
        )
    finally:
        connection.close()


@work_notes_bp.route("/<int:note_id>/edit", methods=["GET", "POST"])
@admin_required
def edit(note_id):
    connection = dashboard_db()
    try:
        note = work_notes.get_note(connection, note_id)
        if not note:
            abort(404)
        if request.method == "GET":
            return render_template(
                "work_notes/form.html", **_form_context(connection, note, note=note)
            )
        raw = _raw_form()
        if not validate_csrf(request.form.get("csrf_token", "")):
            return render_template(
                "work_notes/form.html", **_form_context(
                    connection, raw, note=note,
                    error="요청이 만료되었습니다. 다시 시도해주세요.",
                )
            ), 400
        try:
            clean = work_notes.clean_form(raw)
            next_id = work_notes.update_note(
                connection, note_id, session["user_id"], clean
            )
            work_notes.attach_inline_images(connection, note_id, clean["content"], session["user_id"])
            for uploaded in request.files.getlist("attachments"):
                if uploaded.filename:
                    _save_file(connection, uploaded, session["user_id"], note_id)
            security_audit.log_event(
                connection, "WORK_NOTE_UPDATE", "work_note", note_id,
                {"next_recurrence_id": next_id},
            )
            connection.commit()
        except ValueError as error:
            connection.rollback()
            return render_template(
                "work_notes/form.html", **_form_context(connection, raw, note=note, error=str(error))
            ), 400
        if next_id:
            flash("완료 처리되어 다음 반복 업무를 생성했습니다.", "success")
        return redirect(url_for("work_notes.detail", note_id=note_id))
    finally:
        connection.close()


@work_notes_bp.post("/<int:note_id>/pin")
@admin_required
def pin(note_id):
    if not validate_csrf(request.form.get("csrf_token", "")):
        abort(400)
    connection = dashboard_db()
    try:
        work_notes.toggle_pin(connection, note_id)
        connection.commit()
    finally:
        connection.close()
    return redirect(url_for("work_notes.board"))


@work_notes_bp.post("/<int:note_id>/delete")
@admin_required
def delete(note_id):
    if not validate_csrf(request.form.get("csrf_token", "")):
        abort(400)
    connection = dashboard_db()
    try:
        work_notes.delete_note(connection, note_id)
        security_audit.log_event(connection, "WORK_NOTE_DELETE", "work_note", note_id)
        connection.commit()
    finally:
        connection.close()
    return redirect(url_for("work_notes.board"))


@work_notes_bp.post("/attachments/<int:attachment_id>/delete")
@admin_required
def delete_attachment(attachment_id):
    if not validate_csrf(request.form.get("csrf_token", "")):
        abort(400)
    connection = dashboard_db()
    try:
        attachment = work_notes.get_attachment(connection, attachment_id)
        if not attachment:
            abort(404)
        work_notes.soft_delete_attachment(connection, attachment_id)
        connection.commit()
        note_id = attachment.get("note_id")
    finally:
        connection.close()
    return redirect(url_for("work_notes.edit", note_id=note_id))


@work_notes_bp.get("/files/<int:attachment_id>")
@admin_required
def file(attachment_id):
    connection = dashboard_db()
    try:
        attachment = work_notes.get_attachment(connection, attachment_id)
        if not attachment:
            abort(404)
    finally:
        connection.close()
    path = Path(config.WORK_NOTE_FILE_DIR) / attachment["stored_name"]
    if not path.is_file():
        abort(404)
    return send_file(
        path, mimetype=attachment.get("content_type"), conditional=True, max_age=0,
        as_attachment=attachment.get("kind") != "image",
        download_name=attachment["original_name"],
    )


@work_notes_bp.post("/images")
@admin_required
def upload_image():
    if not validate_csrf(request.form.get("csrf_token", "")):
        return jsonify({"error": "요청이 만료되었습니다."}), 400
    try:
        filename = editor_images.save_pasted_image(
            request.files.get("image"), config.WORK_NOTE_FILE_DIR,
            min(config.WORK_NOTE_MAX_FILE_BYTES, 5 * 1024 * 1024),
        )
        path = Path(config.WORK_NOTE_FILE_DIR) / filename
        connection = dashboard_db()
        try:
            attachment_id = work_notes.register_attachment(
                connection, session["user_id"], filename, filename,
                mimetypes.guess_type(filename)[0], path.stat().st_size, kind="image",
            )
            connection.commit()
        except Exception:
            path.unlink(missing_ok=True)
            raise
        finally:
            connection.close()
    except ValueError as error:
        return jsonify({"error": str(error)}), 400
    return jsonify({"url": url_for("work_notes.file", attachment_id=attachment_id)})


@work_notes_bp.post("/preview")
@admin_required
def preview():
    if not validate_csrf(request.form.get("csrf_token", "")):
        return jsonify({"error": "요청이 만료되었습니다."}), 400
    return jsonify({"html": str(render_markdown(request.form.get("content", "")[:50000]))})


@work_notes_bp.route("/categories", methods=["GET", "POST"])
@admin_required
def categories():
    connection = dashboard_db()
    try:
        error = None
        if request.method == "POST":
            if not validate_csrf(request.form.get("csrf_token", "")):
                abort(400)
            try:
                work_notes.create_category(
                    connection, request.form.get("name"), request.form.get("emoji")
                )
                connection.commit()
                return redirect(url_for("work_notes.categories"))
            except ValueError as exc:
                connection.rollback()
                error = str(exc)
        return render_template(
            "work_notes/categories.html",
            categories=work_notes.list_categories(connection, include_inactive=True),
            csrf_token=get_csrf_token(), error=error,
        ), 400 if error else 200
    finally:
        connection.close()


@work_notes_bp.post("/categories/<int:category_id>")
@admin_required
def update_category(category_id):
    if not validate_csrf(request.form.get("csrf_token", "")):
        abort(400)
    connection = dashboard_db()
    try:
        try:
            work_notes.update_category(
                connection, category_id, request.form.get("name"),
                request.form.get("emoji"), request.form.get("is_active") == "1",
            )
            connection.commit()
        except ValueError as error:
            connection.rollback()
            flash(str(error), "error")
    finally:
        connection.close()
    return redirect(url_for("work_notes.categories"))
