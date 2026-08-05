"""공문·자료관리 웹 화면과 관리자 PC 전용 동기화 API."""

import hmac
import io
import json
import ntpath
import os
from datetime import timedelta

from flask import (
    Blueprint, abort, jsonify, redirect, render_template, request, send_file, session, url_for,
)

import config
from auth import get_csrf_token, login_required, validate_csrf
from extensions import dashboard_db
from services import official_document_manager as manager
from services import ai_insights
from services import official_excel_export
from services import official_excel_import
from services import security_audit
from utils import now_kst


official_docs_bp = Blueprint("official_docs", __name__, url_prefix="/official-docs")


@official_docs_bp.before_request
def purge_expired_trash():
    """Finalize items whose 30-day trash retention has elapsed."""
    connection = dashboard_db()
    try:
        if manager.purge_expired_documents(connection):
            connection.commit()
    finally:
        connection.close()


def _role():
    role = session.get("role")
    if role:
        return role
    user_id = session.get("user_id")
    if not user_id:
        return "anonymous"
    connection = dashboard_db()
    try:
        row = connection.execute(
            "SELECT role FROM dashboard_users WHERE id = ?", (user_id,)
        ).fetchone()
        role = (row["role"] if row else None) or "user"
        session["role"] = role
        return role
    finally:
        connection.close()


def admin_required(view):
    from functools import wraps

    @wraps(view)
    def wrapped(*args, **kwargs):
        if _role() != "admin":
            abort(403)
        return view(*args, **kwargs)

    return wrapped


def _common(connection):
    update_status = manager.data_update_status(connection)
    return {
        "categories": manager.list_reference_values(connection, "category"),
        "folder_categories": manager.list_reference_values(connection, "folder_category"),
        "storage_labels": manager.STORAGE_LABELS,
        "csrf_token": get_csrf_token(),
        "is_admin": _role() == "admin",
        "windows_file_url": manager.windows_file_url,
        "datetime_minute": manager.datetime_minute,
        "official_db_updated_at": (
            manager.datetime_minute(update_status["latest_updated_at"])
            if update_status["latest_updated_at"] else None
        ),
        "official_document_updated_at": (
            manager.datetime_minute(update_status["document_updated_at"])
            if update_status["document_updated_at"] else None
        ),
        "folder_index_updated_at": (
            manager.datetime_minute(update_status["folder_updated_at"])
            if update_status["folder_updated_at"] else None
        ),
    }


@official_docs_bp.route("/")
@login_required
def dashboard():
    connection = dashboard_db()
    try:
        recent, _ = manager.list_documents(connection, per_page=8)
        review, _ = manager.list_documents(connection, per_page=8, review_only=True)
        return render_template(
            "official_docs/dashboard.html",
            metrics=manager.dashboard_metrics(connection),
            recent=recent,
            review=review,
            **_common(connection),
        )
    finally:
        connection.close()


@official_docs_bp.route("/list")
@login_required
def document_list():
    try:
        page = max(1, int(request.args.get("page", 1)))
    except ValueError:
        page = 1
    filters = {key: request.args.get(key) for key in (
        "q", "category_code", "folder_category_code", "storage_status", "manager",
        "organization", "registered_by", "video_exported", "export_pledge", "processing_result",
        "date_from", "date_to", "sort", "direction", "year",
    )}
    connection = dashboard_db()
    try:
        documents, total = manager.list_documents(connection, filters, page=page)
        return render_template(
            "official_docs/list.html", documents=documents, total=total, page=page,
            filters=filters, **_common(connection),
        )
    finally:
        connection.close()


@official_docs_bp.route("/import-excel", methods=["GET", "POST"])
@login_required
def import_excel():
    connection = dashboard_db()
    try:
        result = None
        error = None
        if request.method == "POST":
            if not validate_csrf(request.form.get("csrf_token", "")):
                abort(400)
            uploaded = request.files.get("ledger")
            try:
                raw = uploaded.read(official_excel_import.MAX_IMPORT_BYTES + 1) if uploaded else b""
                result = official_excel_import.import_ledger(
                    connection, raw, uploaded.filename if uploaded else "",
                    {"id": session.get("user_id"), "username": session.get("username")},
                    request.form.get("default_category_code") or "03",
                    request.form.get("default_folder_category_code") or "072",
                )
            except official_excel_import.LedgerImportError as exc:
                error = str(exc)
        return render_template(
            "official_docs/import_excel.html", result=result, import_error=error,
            selected_category=request.form.get("default_category_code") or "03",
            selected_folder=request.form.get("default_folder_category_code") or "072",
            **_common(connection),
        )
    finally:
        connection.close()


@official_docs_bp.get("/import-excel/template")
@login_required
def import_excel_template():
    """Header-only upload template; available to every authorized user."""
    return send_file(
        io.BytesIO(official_excel_import.build_header_template()),
        as_attachment=True,
        download_name="외부자료제공_공문접수_업로드_샘플.xlsx",
        mimetype=(
            "application/vnd.openxmlformats-officedocument."
            "spreadsheetml.sheet"
        ),
    )


@official_docs_bp.route("/field-suggestions")
@login_required
def field_suggestions():
    field = request.args.get("field") or ""
    columns = {
        "manager": "manager",
        "organization": "organization",
        "registered_by": "registered_by",
    }
    column = columns.get(field)
    if not column:
        return jsonify({"error": "unsupported field"}), 400
    term = (request.args.get("q") or "").strip()
    if not term:
        return jsonify({"suggestions": []})
    connection = dashboard_db()
    try:
        rows = connection.execute(
            f"""
            SELECT {column} AS value, COUNT(*) AS use_count, MAX(updated_at) AS last_used
            FROM official_documents
            WHERE is_active=1 AND {column} IS NOT NULL AND TRIM({column})!=''
                  AND {column} LIKE ?
            GROUP BY {column}
            ORDER BY
              CASE WHEN {column}=? THEN 0 WHEN {column} LIKE ? THEN 1 ELSE 2 END,
              use_count DESC, last_used DESC, {column}
            LIMIT 8
            """,
            (f"%{term}%", term, f"{term}%"),
        ).fetchall()
        return jsonify({"suggestions": [dict(row) for row in rows]})
    finally:
        connection.close()


@official_docs_bp.route("/export", methods=["GET", "POST"])
@login_required
def export_excel():
    if request.method == "POST" and not validate_csrf(request.form.get("csrf_token", "")):
        abort(400)
    source = request.form if request.method == "POST" else request.args
    export_type = source.get("export_type") or "filtered"
    drive_letter = (source.get("drive_letter") or "Y").strip().upper()
    if len(drive_letter) != 1 or not ("A" <= drive_letter <= "Z"):
        abort(400)
    is_admin = _role() == "admin"
    if export_type in ("all", "selected", "year") and not is_admin:
        abort(403)
    filters = {key: source.get(key) for key in (
        "q", "category_code", "folder_category_code", "storage_status", "manager",
        "organization", "registered_by", "video_exported", "export_pledge", "processing_result",
        "date_from", "date_to", "sort", "direction", "year",
    )}
    if export_type == "all":
        filters = {}
    elif export_type == "year":
        filters = {"year": source.get("year")}
        if not str(filters["year"] or "").isdigit():
            abort(400)
    if not is_admin:
        filters["registered_user_id"] = session.get("user_id")

    connection = dashboard_db()
    try:
        if export_type == "selected":
            selected_ids = {
                int(value) for value in source.getlist("document_ids")
                if str(value).isdigit()
            }
            if not selected_ids:
                return redirect(url_for("official_docs.document_list", export_error="선택한 자료가 없습니다."))
            documents = manager.list_documents_by_ids(connection, selected_ids)
            if not documents:
                return redirect(url_for("official_docs.document_list", export_error="선택한 자료를 찾을 수 없습니다."))
        else:
            documents, _ = manager.list_documents(connection, filters, per_page=1_048_575)
        label = {"all": "전체", "selected": "선택자료", "year": str(filters.get("year") or "")}.get(
            export_type, "검색결과"
        )
        today = now_kst().strftime("%Y%m%d_%H%M%S")
        filename = f"외부자료제공_및_공문접수_대장_{label}_{today}.xlsx"
        filter_json = json.dumps(
            {key: value for key, value in filters.items() if value not in (None, "")},
            ensure_ascii=False, sort_keys=True,
        )
        path = official_excel_export.create_workbook(
            documents,
            manager.list_reference_values(connection, "category"),
            manager.list_reference_values(connection, "folder_category"),
            {
                "created_at": now_kst().isoformat(),
                "username": session.get("username") or "",
                "export_type": export_type,
                "filters": filter_json,
                "year": filters.get("year") or "",
                "drive_letter": drive_letter,
            },
            include_personal_data=is_admin,
        )
        connection.execute(
            """
            INSERT INTO official_excel_exports
                (export_type, exported_by, exported_user_id, exported_at,
                 filter_conditions, record_count, output_filename, includes_personal_data)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                export_type, session.get("username") or "", session.get("user_id"),
                now_kst().isoformat(), filter_json, len(documents), filename, int(is_admin),
            ),
        )
        if documents:
            placeholders = ",".join("?" for _ in documents)
            connection.execute(
                f"UPDATE official_documents SET excel_exported_at=? WHERE id IN ({placeholders})",
                (now_kst().isoformat(), *(item["id"] for item in documents)),
            )
        security_audit.log_event(
            connection,
            "EXCEL_EXPORT",
            "official_documents",
            export_type,
            {
                "record_count": len(documents),
                "filename": filename,
                "drive_letter": drive_letter,
                "includes_personal_data": is_admin,
                "filters": json.loads(filter_json),
            },
        )
        connection.commit()
        response = send_file(
            path,
            as_attachment=True,
            download_name=filename,
            mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )
        response.call_on_close(lambda: os.path.exists(path) and os.unlink(path))
        return response
    finally:
        connection.close()


@official_docs_bp.route("/new", methods=["GET", "POST"])
@login_required
def document_new():
    connection = dashboard_db()
    try:
        form_values = request.form.to_dict() if request.method == "POST" else {}
        if request.method == "POST":
            if not validate_csrf(request.form.get("csrf_token", "")):
                return render_template(
                    "official_docs/form.html", form_values=form_values,
                    errors={"csrf": "요청이 만료되었습니다."}, duplicate_candidates=[],
                    attachment_types=manager.ATTACHMENT_TYPES, **_common(connection),
                ), 400
            errors, receipt_date, *_ = manager.validate_form(connection, request.form)
            files = [item for item in request.files.getlist("attachments") if item.filename]
            if (request.form.get("folder_handling_type") or "CREATE_NEW") == "CREATE_NEW" and not files:
                errors["attachments"] = "PDF 파일을 1개 이상 등록해주세요."
            candidates = manager.find_duplicate_candidates(connection, request.form, receipt_date)
            if candidates and request.form.get("duplicate_ack") != "1":
                return render_template(
                    "official_docs/form.html", form_values=form_values, errors=errors,
                    duplicate_candidates=candidates, attachment_types=manager.ATTACHMENT_TYPES,
                    **_common(connection),
                ), 409
            if errors:
                return render_template(
                    "official_docs/form.html", form_values=form_values, errors=errors,
                    duplicate_candidates=candidates, attachment_types=manager.ATTACHMENT_TYPES,
                    **_common(connection),
                ), 400
            try:
                document_id, create_errors = manager.create_document(
                    connection, request.form, files,
                    {"id": session.get("user_id"), "username": session.get("username")},
                )
            except manager.OfficialDocumentError as error:
                create_errors = {"attachments": str(error)}
                document_id = None
            if create_errors:
                return render_template(
                    "official_docs/form.html", form_values=form_values, errors=create_errors,
                    duplicate_candidates=candidates, attachment_types=manager.ATTACHMENT_TYPES,
                    **_common(connection),
                ), 400
            security_audit.log_event(
                connection,
                "PDF_UPLOAD",
                "official_document",
                document_id,
                {"file_count": len(files)},
            )
            connection.commit()
            return redirect(url_for("official_docs.document_detail", document_id=document_id))
        return render_template(
            "official_docs/form.html", form_values=form_values, errors={},
            duplicate_candidates=[], attachment_types=manager.ATTACHMENT_TYPES,
            **_common(connection),
        )
    finally:
        connection.close()


@official_docs_bp.route("/analyze-upload", methods=["POST"])
@login_required
def analyze_upload():
    if not validate_csrf(request.form.get("csrf_token", "")):
        abort(400)
    uploaded = request.files.get("document")
    if not uploaded or not uploaded.filename:
        return jsonify({"ok": False, "error": "분석할 PDF를 선택해주세요."}), 400
    connection = dashboard_db()
    saved = None
    try:
        saved = manager.save_temp_pdf(uploaded)
        managers = [
            row["manager"] for row in connection.execute(
                """
                SELECT manager, MAX(updated_at) AS last_used
                FROM official_documents
                WHERE manager IS NOT NULL AND TRIM(manager)!=''
                GROUP BY manager ORDER BY last_used DESC LIMIT 30
                """
            ).fetchall()
        ]
        categories = manager.list_reference_values(connection, "category")
        folders = manager.list_reference_values(connection, "folder_category")
        suggestions, error = ai_insights.extract_official_document_fields(
            connection,
            saved["path"].read_bytes(),
            saved["original_filename"],
            managers,
            categories,
            folders,
        )
        security_audit.log_event(
            connection,
            "OFFICIAL_DOCUMENT_AI_PREFILL",
            "temporary_pdf",
            saved["sha256"][:16],
            {
                "filename": saved["original_filename"],
                "file_size": saved["file_size"],
                "success": bool(suggestions),
                "suggested_fields": sorted(
                    key for key, value in (suggestions or {}).items()
                    if value not in ("", None, [], "해당없음")
                ),
            },
            success=bool(suggestions),
        )
        connection.commit()
        if error or not suggestions:
            return jsonify({
                "ok": False,
                "error": error or "문서에서 입력값을 추출하지 못했습니다.",
            }), 422
        return jsonify({"ok": True, "suggestions": suggestions})
    except manager.OfficialDocumentError as error:
        return jsonify({"ok": False, "error": str(error)}), 400
    finally:
        if saved:
            saved["path"].unlink(missing_ok=True)
        connection.close()


@official_docs_bp.route("/<int:document_id>", methods=["GET", "POST"])
@login_required
def document_detail(document_id):
    connection = dashboard_db()
    try:
        document = manager.get_document(connection, document_id)
        if not document or (not document["is_active"] and _role() != "admin"):
            abort(404)
        if request.method == "POST":
            if _role() != "admin":
                abort(403)
            if not validate_csrf(request.form.get("csrf_token", "")):
                abort(400)
            fields = {
                "processing_result": (request.form.get("processing_result") or "").strip(),
                "video_exported": request.form.get("video_exported") or "해당없음",
                "export_pledge": request.form.get("export_pledge") or "해당없음",
                "special_note": (request.form.get("special_note") or "").strip(),
                "location": (request.form.get("location") or "").strip(),
            }
            changes = {
                key: {"before": document.get(key), "after": value}
                for key, value in fields.items()
                if (document.get(key) or "") != value
            }
            connection.execute(
                """
                UPDATE official_documents
                SET processing_result=?, video_exported=?, export_pledge=?,
                    special_note=?, location=?, updated_at=?
                WHERE id=?
                """,
                (*fields.values(), now_kst().isoformat(), document_id),
            )
            manager.log_history(
                connection, document_id, "DOCUMENT_UPDATED",
                actor=session.get("username"), detail={"changes": changes},
            )
            security_audit.log_event(
                connection, "OFFICIAL_DOCUMENT_EDIT", "official_document",
                document_id, {"changes": changes},
            )
            connection.commit()
            return redirect(url_for("official_docs.document_detail", document_id=document_id))
        history = [
            dict(row) for row in connection.execute(
                "SELECT * FROM official_document_history WHERE document_id=? ORDER BY created_at DESC",
                (document_id,),
            ).fetchall()
        ]
        return render_template(
            "official_docs/detail.html", document=document, history=history,
            video_values=manager.VIDEO_EXPORT_VALUES,
            pledge_values=manager.EXPORT_PLEDGE_VALUES, **_common(connection),
        )
    finally:
        connection.close()


@official_docs_bp.route("/<int:document_id>/edit", methods=["GET", "POST"])
@login_required
@admin_required
def document_edit(document_id):
    connection = dashboard_db()
    try:
        document = manager.get_document(connection, document_id)
        if not document or not document["is_active"]:
            abort(404)
        values = dict(document) if request.method == "GET" else request.form.to_dict()
        errors = {}
        if request.method == "POST":
            if not validate_csrf(request.form.get("csrf_token", "")):
                abort(400)
            errors, receipt_date, reply_date, category, folder, video, pledge = manager.validate_form(
                connection, request.form
            )
            if (
                request.form.get("folder_handling_type") == "LINK_EXISTING"
                and not request.form.get("requested_folder_path")
                and not document.get("requested_folder_path")
            ):
                errors.pop("requested_folder_path", None)
            if request.form.get("processing_result") not in ("처리 필요", "진행 중", "완료"):
                errors["processing_result"] = "처리결과를 다시 선택해주세요."
            if not errors:
                editable = {
                    "receipt_number": (request.form.get("receipt_number") or "").strip() or None,
                    "manager": (request.form.get("manager") or "").strip(),
                    "receipt_date": receipt_date,
                    "organization": manager.canonicalize_organization(
                        connection, request.form.get("organization")
                    ),
                    "case_name": (request.form.get("case_name") or "").strip() or None,
                    "request_content": (request.form.get("request_content") or "").strip(),
                    "special_note": (request.form.get("special_note") or "").strip() or None,
                    "requester": (request.form.get("requester") or "").strip() or None,
                    "contact": (request.form.get("contact") or "").strip() or None,
                    "email": (request.form.get("email") or "").strip() or None,
                    "dispatch_number": (request.form.get("dispatch_number") or "").strip() or None,
                    "reply_date": reply_date,
                    "category_code": category["code"],
                    "category_detail": (request.form.get("category_detail") or "").strip() or None,
                    "folder_category_code": folder["code"],
                    "folder_category_detail": (
                        request.form.get("folder_category_detail") or ""
                    ).strip() or None,
                    "processing_result": (request.form.get("processing_result") or "처리 필요").strip(),
                    "video_exported": video,
                    "export_pledge": pledge,
                    "folder_handling_type": request.form.get("folder_handling_type") or "CREATE_NEW",
                    "requested_folder_path": (
                        request.form.get("requested_folder_path") or ""
                    ).strip() or None,
                    "folder_display_name": (
                        request.form.get("folder_display_name") or ""
                    ).strip() or None,
                }
                changes = {
                    key: {"before": document.get(key), "after": value}
                    for key, value in editable.items()
                    if document.get(key) != value
                }
                if changes:
                    assignments = ", ".join(f"{key}=?" for key in editable)
                    connection.execute(
                        f"UPDATE official_documents SET {assignments}, updated_at=? WHERE id=?",
                        (*editable.values(), now_kst().isoformat(), document_id),
                    )
                    manager.log_history(
                        connection, document_id, "DOCUMENT_FULL_EDITED",
                        actor=session.get("username"), detail={"changes": changes},
                    )
                    security_audit.log_event(
                        connection, "OFFICIAL_DOCUMENT_EDIT", "official_document",
                        document_id, {"changes": changes},
                    )
                    connection.commit()
                return redirect(url_for("official_docs.document_detail", document_id=document_id))
        return render_template(
            "official_docs/edit.html", document=document, form_values=values, errors=errors,
            video_values=manager.VIDEO_EXPORT_VALUES,
            pledge_values=manager.EXPORT_PLEDGE_VALUES, **_common(connection),
        ), 400 if errors else 200
    finally:
        connection.close()


@official_docs_bp.route("/bulk-action", methods=["POST"])
@login_required
@admin_required
def bulk_action():
    if not validate_csrf(request.form.get("csrf_token", "")):
        abort(400)
    document_ids = sorted({
        int(value) for value in request.form.getlist("document_ids")
        if str(value).isdigit()
    })
    if not document_ids or len(document_ids) > 500:
        return redirect(url_for("official_docs.document_list", bulk_error="자료를 선택해주세요."))
    action = request.form.get("bulk_action")
    connection = dashboard_db()
    try:
        affected = 0
        if action == "delete":
            for document_id in document_ids:
                affected += int(manager.soft_delete_document(
                    connection, document_id, session.get("username")
                ))
        elif action == "processing":
            result_value = request.form.get("processing_result")
            if result_value not in ("처리 필요", "진행 중", "완료"):
                abort(400)
            for document_id in document_ids:
                row = connection.execute(
                    "SELECT processing_result FROM official_documents WHERE id=? AND is_active=1",
                    (document_id,),
                ).fetchone()
                if row and row["processing_result"] != result_value:
                    connection.execute(
                        "UPDATE official_documents SET processing_result=?, updated_at=? WHERE id=?",
                        (result_value, now_kst().isoformat(), document_id),
                    )
                    manager.log_history(
                        connection, document_id, "PROCESSING_RESULT_BULK_UPDATED",
                        actor=session.get("username"),
                        detail={"before": row["processing_result"], "after": result_value},
                    )
                    affected += 1
        else:
            abort(400)
        security_audit.log_event(
            connection,
            "OFFICIAL_DOCUMENT_BULK_DELETE" if action == "delete"
            else "OFFICIAL_DOCUMENT_BULK_STATUS_CHANGE",
            "official_document",
            ",".join(str(item) for item in document_ids),
            {"requested_count": len(document_ids), "affected_count": affected},
        )
        connection.commit()
        return redirect(url_for(
            "official_docs.document_list", bulk_done=affected,
            bulk_kind="삭제" if action == "delete" else "처리결과 변경",
        ))
    finally:
        connection.close()


@official_docs_bp.route("/<int:document_id>/deactivate", methods=["POST"])
@login_required
@admin_required
def deactivate(document_id):
    if not validate_csrf(request.form.get("csrf_token", "")):
        abort(400)
    connection = dashboard_db()
    try:
        if not manager.soft_delete_document(connection, document_id, session.get("username")):
            abort(404)
        security_audit.log_event(
            connection, "OFFICIAL_DOCUMENT_DELETE", "official_document", document_id
        )
        connection.commit()
        return redirect(url_for("official_docs.trash"))
    finally:
        connection.close()


@official_docs_bp.route("/review")
@login_required
def review_list():
    connection = dashboard_db()
    try:
        documents, total = manager.list_documents(connection, per_page=1000, review_only=True)
        return render_template(
            "official_docs/review.html", documents=documents, total=total, **_common(connection)
        )
    finally:
        connection.close()


@official_docs_bp.route("/history")
@login_required
@admin_required
def history():
    connection = dashboard_db()
    try:
        return render_template(
            "official_docs/history.html", history=manager.list_change_log(connection), **_common(connection)
        )
    finally:
        connection.close()


@official_docs_bp.route("/trash")
@login_required
@admin_required
def trash():
    connection = dashboard_db()
    try:
        purged = manager.purge_expired_documents(connection)
        connection.commit()
        return render_template(
            "official_docs/trash.html",
            documents=manager.list_deleted_documents(connection), purged=purged,
            **_common(connection),
        )
    finally:
        connection.close()


@official_docs_bp.route("/<int:document_id>/restore", methods=["POST"])
@login_required
@admin_required
def restore(document_id):
    if not validate_csrf(request.form.get("csrf_token", "")):
        abort(400)
    connection = dashboard_db()
    try:
        if not manager.restore_document(connection, document_id, session.get("username")):
            abort(404)
        security_audit.log_event(
            connection, "OFFICIAL_DOCUMENT_RESTORE", "official_document", document_id
        )
        connection.commit()
        return redirect(url_for("official_docs.document_detail", document_id=document_id))
    finally:
        connection.close()


@official_docs_bp.route("/settings", methods=["GET", "POST"])
@login_required
@admin_required
def settings():
    connection = dashboard_db()
    try:
        if request.method == "POST":
            if not validate_csrf(request.form.get("csrf_token", "")):
                abort(400)
            action = request.form.get("action")
            if action == "add":
                kind = request.form.get("kind")
                if kind not in ("category", "folder_category"):
                    abort(400)
                connection.execute(
                    """
                    INSERT INTO official_doc_reference_values
                        (kind, code, label, active, sort_order, created_at, updated_at)
                    VALUES (?, ?, ?, 1, ?, ?, ?)
                    """,
                    (
                        kind, request.form.get("code", "").strip(),
                        request.form.get("label", "").strip(),
                        int(request.form.get("sort_order") or 999),
                        now_kst().isoformat(), now_kst().isoformat(),
                    ),
                )
            elif action == "toggle":
                connection.execute(
                    """
                    UPDATE official_doc_reference_values
                    SET active=CASE active WHEN 1 THEN 0 ELSE 1 END, updated_at=?
                    WHERE id=?
                    """,
                    (now_kst().isoformat(), int(request.form.get("reference_id"))),
                )
            connection.commit()
            return redirect(url_for("official_docs.settings"))
        return render_template(
            "official_docs/settings.html",
            all_categories=manager.list_reference_values(connection, "category", active_only=False),
            all_folders=manager.list_reference_values(connection, "folder_category", active_only=False),
            **_common(connection),
        )
    finally:
        connection.close()


@official_docs_bp.route("/audit/path-copy", methods=["POST"])
@login_required
def audit_path_copy():
    if not validate_csrf(request.form.get("csrf_token", "")):
        abort(400)
    document_id = request.form.get("document_id")
    if not str(document_id or "").isdigit():
        abort(400)
    connection = dashboard_db()
    try:
        row = connection.execute(
            """
            SELECT id, management_number
            FROM official_documents
            WHERE id=? AND is_active=1
            """,
            (int(document_id),),
        ).fetchone()
        if not row:
            abort(404)
        security_audit.log_event(
            connection,
            "Y_DRIVE_PATH_COPY",
            "official_document",
            row["id"],
            {"management_number": row["management_number"]},
        )
        connection.commit()
        return jsonify({"ok": True})
    finally:
        connection.close()


def _sync_authorized():
    expected = config.SYNC_API_TOKEN
    supplied = request.headers.get("Authorization", "")
    if supplied.lower().startswith("bearer "):
        supplied = supplied[7:].strip()
    return bool(expected) and hmac.compare_digest(expected, supplied)


def _sync_guard():
    if not _sync_authorized():
        return jsonify({"error": "unauthorized"}), 401
    return None


@official_docs_bp.route("/folder-index")
@login_required
def folder_index_search():
    term = (request.args.get("q") or "").strip()
    connection = dashboard_db()
    try:
        rows = connection.execute(
            """
            SELECT * FROM official_folder_index
            WHERE is_available=1 AND
                  (?='' OR folder_name LIKE ? OR relative_path LIKE ? OR unc_path LIKE ?)
            ORDER BY last_scanned_at DESC, folder_name LIMIT 50
            """,
            (term, f"%{term}%", f"%{term}%", f"%{term}%"),
        ).fetchall()
        return jsonify({"folders": [dict(row) for row in rows]})
    finally:
        connection.close()


def _folder_tree_nodes(rows, parent=""):
    """Build immediate children for an indexed Windows/UNC folder path."""
    nodes = {}
    parent_key = parent.rstrip("\\/").casefold()
    for row in rows:
        unc_path = str(row["unc_path"] or "").replace("/", "\\").rstrip("\\")
        relative_path = str(row["relative_path"] or "").replace("/", "\\").strip("\\")
        parts = [part for part in relative_path.split("\\") if part]
        if not unc_path or not parts:
            continue
        suffix = "\\".join(parts)
        if not unc_path.casefold().endswith(suffix.casefold()):
            continue
        root = unc_path[: len(unc_path) - len(suffix)].rstrip("\\")
        current = root
        for index, part in enumerate(parts):
            current = f"{current}\\{part}"
            key = current.casefold()
            node = nodes.setdefault(key, {
                "name": part,
                "path": current,
                "parent": ntpath.dirname(current).rstrip("\\").casefold(),
                "has_children": False,
                "file_count": None,
            })
            if index == len(parts) - 1:
                node["file_count"] = row["file_count"]

    child_parents = {node["parent"] for node in nodes.values()}
    for node in nodes.values():
        node["has_children"] = node["path"].casefold() in child_parents

    if parent_key:
        if parent_key not in nodes:
            return []
        return sorted(
            (node for node in nodes.values() if node["parent"] == parent_key),
            key=lambda node: node["name"].casefold(),
        )

    root_parents = {node["parent"] for node in nodes.values() if node["parent"] not in nodes}
    return sorted(
        (node for node in nodes.values() if node["parent"] in root_parents),
        key=lambda node: node["name"].casefold(),
    )


@official_docs_bp.route("/folder-tree")
@login_required
def folder_tree():
    parent = (request.args.get("parent") or "").strip()
    connection = dashboard_db()
    try:
        rows = connection.execute(
            """
            SELECT folder_name, relative_path, unc_path, file_count
            FROM official_folder_index
            WHERE is_available=1
            ORDER BY relative_path
            LIMIT 10000
            """
        ).fetchall()
        return jsonify({"parent": parent, "folders": _folder_tree_nodes(rows, parent)})
    finally:
        connection.close()


@official_docs_bp.route("/api/archive-sync/folder-index", methods=["POST"])
def sync_folder_index():
    denied = _sync_guard()
    if denied:
        return denied
    data = request.get_json(silent=True) or {}
    folders = data.get("folders") or []
    client_name = str(data.get("client_name") or "")[:120]
    if not isinstance(folders, list) or len(folders) > 10000:
        return jsonify({"error": "invalid folder list"}), 400
    connection = dashboard_db()
    try:
        now_iso = now_kst().isoformat()
        connection.execute("BEGIN IMMEDIATE")
        connection.execute("UPDATE official_folder_index SET is_available=0")
        for item in folders:
            unc_path = str(item.get("unc_path") or "").strip()
            relative_path = str(item.get("relative_path") or "").strip()
            folder_name = str(item.get("folder_name") or "").strip()
            if not unc_path.startswith("\\\\") or ".." in relative_path.replace("/", "\\").split("\\"):
                connection.rollback()
                return jsonify({"error": "unsafe folder path"}), 400
            connection.execute(
                """
                INSERT INTO official_folder_index
                    (folder_name, relative_path, unc_path, year, folder_category,
                     file_count, last_modified_at, last_scanned_at, is_available)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, 1)
                ON CONFLICT(unc_path) DO UPDATE SET
                    folder_name=excluded.folder_name, relative_path=excluded.relative_path,
                    year=excluded.year, folder_category=excluded.folder_category,
                    file_count=excluded.file_count, last_modified_at=excluded.last_modified_at,
                    last_scanned_at=excluded.last_scanned_at, is_available=1
                """,
                (
                    folder_name[:240], relative_path[:1000], unc_path[:1500],
                    item.get("year"), str(item.get("folder_category") or "")[:120],
                    max(0, int(item.get("file_count") or 0)),
                    item.get("last_modified_at"), now_iso,
                ),
            )
        manager.log_history(
            connection, None, "FOLDER_INDEX_SYNCED", client_name=client_name,
            detail={"folder_count": len(folders)},
        )
        connection.commit()
        return jsonify({"success": True, "folder_count": len(folders)})
    finally:
        connection.close()


@official_docs_bp.route("/api/archive-sync/<int:document_id>/verify", methods=["POST"])
def sync_verify_folder(document_id):
    denied = _sync_guard()
    if denied:
        return denied
    data = request.get_json(silent=True) or {}
    status = data.get("folder_link_status")
    if status not in ("LINK_VERIFIED", "LINK_FAILED", "FOLDER_CONFLICT"):
        return jsonify({"error": "invalid folder link status"}), 400
    unc_path = str(data.get("normalized_unc_path") or "").strip()
    if status == "LINK_VERIFIED" and not unc_path.startswith("\\\\"):
        return jsonify({"error": "verified UNC path required"}), 400
    connection = dashboard_db()
    try:
        connection.execute(
            """
            UPDATE official_documents
            SET folder_link_status=?, normalized_unc_path=?, location=?,
                folder_display_name=COALESCE(?, folder_display_name),
                folder_link_note=?, folder_verified_at=?,
                folder_verified_by_client=?, file_count=?,
                storage_status=?, updated_at=?
            WHERE id=? AND folder_handling_type='LINK_EXISTING'
            """,
            (
                status, unc_path or None, unc_path or None, data.get("folder_display_name"),
                str(data.get("message") or "")[:1000], now_kst().isoformat(),
                str(data.get("client_name") or "")[:120], max(0, int(data.get("file_count") or 0)),
                "STORED" if status == "LINK_VERIFIED" else "FAILED",
                now_kst().isoformat(), document_id,
            ),
        )
        manager.log_history(
            connection, document_id, "FOLDER_LINK_VERIFIED" if status == "LINK_VERIFIED" else status,
            client_name=data.get("client_name"), detail={"path": unc_path, "message": data.get("message")},
        )
        connection.commit()
        return jsonify({"success": True})
    finally:
        connection.close()


@official_docs_bp.route("/api/archive-sync/pending")
def sync_pending():
    denied = _sync_guard()
    if denied:
        return denied
    connection = dashboard_db()
    try:
        documents, _ = manager.list_documents(
            connection, {"storage_status": "UPLOADED"}, per_page=500
        )
        payload = []
        for item in documents:
            document = manager.get_document(connection, item["id"])
            payload.append({
                "id": document["id"],
                "management_number": document["management_number"],
                "receipt_date": document["receipt_date"],
                "category": document["category_label"],
                "folder_category": document["folder_category_label"],
                "organization": document["organization"],
                "request_content": document["request_content"],
                "target_folder_name": manager.build_archive_folder_name(
                    document["receipt_date"], document["category_label"],
                    document["organization"], document["request_content"],
                ),
                "folder_handling_type": document["folder_handling_type"],
                "requested_folder_path": document["requested_folder_path"],
                "folder_display_name": document["folder_display_name"],
                "folder_link_status": document["folder_link_status"],
                "attachments": [
                    {
                        "id": value["id"], "original_filename": value["original_filename"],
                        "file_size": value["file_size"], "sha256": value["sha256"],
                        "attachment_type": value["attachment_type"],
                    } for value in document["attachments"]
                ],
            })
        return jsonify({"documents": payload})
    finally:
        connection.close()


@official_docs_bp.route("/api/archive-sync/pending-deletions")
def sync_pending_deletions():
    denied = _sync_guard()
    if denied:
        return denied
    connection = dashboard_db()
    try:
        rows = connection.execute(
            """
            SELECT id, management_number, folder_handling_type, location,
                   requested_folder_path, delete_after
            FROM official_documents
            WHERE is_active=0 AND delete_after IS NOT NULL AND delete_after<=?
                  AND file_delete_status IN ('PENDING','FAILED')
            ORDER BY delete_after LIMIT 200
            """,
            (now_kst().isoformat(),),
        ).fetchall()
        documents = []
        for row in rows:
            attachments = connection.execute(
                """
                SELECT final_path FROM official_document_attachments
                WHERE document_id=? AND final_path IS NOT NULL
                """,
                (row["id"],),
            ).fetchall()
            documents.append({
                "id": row["id"],
                "management_number": row["management_number"],
                "delete_after": row["delete_after"],
                "file_paths": [item["final_path"] for item in attachments],
                "delete_folder": (
                    row["location"] or row["requested_folder_path"]
                    if row["folder_handling_type"] == "CREATE_NEW" else None
                ),
            })
        return jsonify({"documents": documents})
    finally:
        connection.close()


@official_docs_bp.route("/api/archive-sync/<int:document_id>/deletion-complete", methods=["POST"])
def sync_deletion_complete(document_id):
    denied = _sync_guard()
    if denied:
        return denied
    data = request.get_json(silent=True) or {}
    success = bool(data.get("success"))
    client_name = str(data.get("client_name") or "")[:120]
    connection = dashboard_db()
    try:
        row = connection.execute(
            """
            SELECT id FROM official_documents
            WHERE id=? AND is_active=0 AND delete_after IS NOT NULL AND delete_after<=?
            """,
            (document_id, now_kst().isoformat()),
        ).fetchone()
        if not row:
            return jsonify({"error": "deletion not pending"}), 409
        if success:
            connection.execute(
                """
                UPDATE official_documents SET file_delete_status='DELETED',
                    file_deleted_at=?, file_delete_client=?, file_delete_error=NULL, updated_at=?
                WHERE id=?
                """,
                (now_kst().isoformat(), client_name, now_kst().isoformat(), document_id),
            )
            manager.log_history(
                connection, document_id, "MANAGED_FILES_DELETED",
                client_name=client_name, detail={"message": data.get("message")},
            )
            manager.purge_expired_documents(connection)
        else:
            error = str(data.get("error") or "파일 삭제 실패")[:1000]
            connection.execute(
                """
                UPDATE official_documents SET file_delete_status='FAILED',
                    file_delete_client=?, file_delete_error=?, updated_at=? WHERE id=?
                """,
                (client_name, error, now_kst().isoformat(), document_id),
            )
            manager.log_history(
                connection, document_id, "MANAGED_FILE_DELETE_FAILED",
                client_name=client_name, detail={"error": error},
            )
        connection.commit()
        return jsonify({"success": True})
    finally:
        connection.close()


@official_docs_bp.route("/api/archive-sync/<int:document_id>/claim", methods=["POST"])
def sync_claim(document_id):
    denied = _sync_guard()
    if denied:
        return denied
    data = request.get_json(silent=True) or {}
    client_name = str(data.get("client_name") or "").strip()[:120]
    if not client_name:
        return jsonify({"error": "client_name required"}), 400
    connection = dashboard_db()
    try:
        now = now_kst()
        expires = now + timedelta(minutes=config.SYNC_CLAIM_TIMEOUT_MINUTES)
        connection.execute("BEGIN IMMEDIATE")
        row = connection.execute(
            "SELECT storage_status, claim_expires_at FROM official_documents WHERE id=? AND is_active=1",
            (document_id,),
        ).fetchone()
        expired = row and row["claim_expires_at"] and row["claim_expires_at"] < now.isoformat()
        if not row or (row["storage_status"] != "UPLOADED" and not expired):
            connection.rollback()
            return jsonify({"error": "not claimable"}), 409
        connection.execute(
            """
            UPDATE official_documents
            SET storage_status='PROCESSING', claim_client=?, claimed_at=?, claim_expires_at=?, updated_at=?
            WHERE id=?
            """,
            (client_name, now.isoformat(), expires.isoformat(), now.isoformat(), document_id),
        )
        manager.log_history(
            connection, document_id, "SYNC_CLAIMED", client_name=client_name,
            detail={"expires_at": expires.isoformat()},
        )
        connection.commit()
        return jsonify({"success": True, "claim_expires_at": expires.isoformat()})
    finally:
        connection.close()


@official_docs_bp.route("/api/archive-sync/attachments/<int:attachment_id>/download")
def sync_download(attachment_id):
    denied = _sync_guard()
    if denied:
        return denied
    connection = dashboard_db()
    try:
        row = connection.execute(
            """
            SELECT a.*, d.storage_status, d.id AS document_id
            FROM official_document_attachments a
            JOIN official_documents d ON d.id=a.document_id
            WHERE a.id=?
            """,
            (attachment_id,),
        ).fetchone()
        if not row or row["storage_status"] != "PROCESSING" or not row["temp_filename"]:
            abort(404)
        path = manager.temp_file_path(row["temp_filename"])
        if not path.is_file():
            abort(404)
        manager.log_history(
            connection, row["document_id"], "SYNC_DOWNLOADED",
            attachment_id=attachment_id, client_name=request.headers.get("X-Sync-Client"),
        )
        connection.commit()
        return send_file(path, as_attachment=True, download_name=row["original_filename"])
    finally:
        connection.close()


@official_docs_bp.route("/api/archive-sync/<int:document_id>/complete", methods=["POST"])
def sync_complete(document_id):
    denied = _sync_guard()
    if denied:
        return denied
    data = request.get_json(silent=True) or {}
    location = str(data.get("location") or "").strip()
    attachments = data.get("attachments") or []
    if not location or not attachments or int(data.get("file_count") or 0) < 1:
        return jsonify({"error": "verified location, file_count and attachments required"}), 400
    connection = dashboard_db()
    try:
        current = manager.get_document(connection, document_id)
        if not current or current["storage_status"] != "PROCESSING":
            return jsonify({"error": "not processing"}), 409
        expected = {item["id"]: item for item in current["attachments"]}
        submitted = {int(item["id"]): item for item in attachments}
        if set(expected) != set(submitted):
            return jsonify({"error": "attachment set mismatch"}), 409
        for attachment_id, expected_item in expected.items():
            item = submitted[attachment_id]
            if item.get("sha256") != expected_item["sha256"] or int(item.get("file_size") or -1) != expected_item["file_size"]:
                return jsonify({"error": f"verification mismatch: {attachment_id}"}), 409
            connection.execute(
                """
                UPDATE official_document_attachments
                SET final_filename=?, final_path=?, stored_at=?, temp_status='STORED'
                WHERE id=?
                """,
                (
                    item.get("final_filename"), item.get("final_path"),
                    now_kst().isoformat(), attachment_id,
                ),
            )
        connection.execute(
            """
            UPDATE official_documents
            SET location=?, file_count=?, storage_status='STORED', temp_file_status='STORED',
                verified_at=?, error_message=NULL, claim_expires_at=NULL, updated_at=?
            WHERE id=?
            """,
            (
                location, int(data["file_count"]), now_kst().isoformat(),
                now_kst().isoformat(), document_id,
            ),
        )
        manager.log_history(
            connection, document_id, "SYNC_COMPLETED",
            client_name=data.get("client_name"), detail={"location": location, "file_count": data["file_count"]},
        )
        connection.commit()
        return jsonify({"success": True})
    finally:
        connection.close()


@official_docs_bp.route("/api/archive-sync/<int:document_id>/fail", methods=["POST"])
def sync_fail(document_id):
    denied = _sync_guard()
    if denied:
        return denied
    data = request.get_json(silent=True) or {}
    connection = dashboard_db()
    try:
        connection.execute(
            """
            UPDATE official_documents
            SET storage_status='FAILED', error_message=?, claim_expires_at=NULL, updated_at=?
            WHERE id=?
            """,
            (str(data.get("error") or "동기화 실패")[:1000], now_kst().isoformat(), document_id),
        )
        manager.log_history(
            connection, document_id, "SYNC_FAILED",
            client_name=data.get("client_name"), detail={"error": str(data.get("error") or "")[:1000]},
        )
        connection.commit()
        return jsonify({"success": True})
    finally:
        connection.close()


@official_docs_bp.route("/api/archive-sync/attachments/<int:attachment_id>/temporary-file", methods=["DELETE"])
def sync_delete_temporary(attachment_id):
    denied = _sync_guard()
    if denied:
        return denied
    connection = dashboard_db()
    try:
        row = connection.execute(
            """
            SELECT a.*, d.storage_status FROM official_document_attachments a
            JOIN official_documents d ON d.id=a.document_id WHERE a.id=?
            """,
            (attachment_id,),
        ).fetchone()
        if not row or row["storage_status"] != "STORED" or not row["final_path"] or not row["stored_at"]:
            return jsonify({"error": "storage verification incomplete"}), 409
        if row["temp_filename"]:
            manager.temp_file_path(row["temp_filename"]).unlink(missing_ok=True)
        connection.execute(
            """
            UPDATE official_document_attachments
            SET temp_filename=NULL, temp_status='ARCHIVED', temp_deleted_at=?
            WHERE id=?
            """,
            (now_kst().isoformat(), attachment_id),
        )
        manager.log_history(
            connection, row["document_id"], "TEMP_FILE_DELETED", attachment_id=attachment_id
        )
        connection.commit()
        return jsonify({"success": True})
    finally:
        connection.close()
