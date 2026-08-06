"""공문·자료관리 업무규칙, PDF 임시보관, 조회 및 동기화 상태 처리."""

import hashlib
import json
import re
import unicodedata
import uuid
from datetime import date, datetime, timedelta
from pathlib import Path
from urllib.parse import quote

import config
from services import pdf_security
from utils import now_kst


STORAGE_LABELS = {
    "UPLOADING": "업로드 중",
    "UPLOADED": "Y디스크 저장 대기",
    "PROCESSING": "저장 처리 중",
    "STORED": "저장 완료",
    "FAILED": "저장 실패",
    "MISSING": "파일 누락",
    "ARCHIVED": "보관 처리",
    "LINK_PENDING": "기존 폴더 확인 대기",
    "LINK_VERIFIED": "기존 폴더 연결 완료",
    "LINK_FAILED": "기존 폴더 확인 실패",
    "FOLDER_CONFLICT": "폴더 충돌 확인 필요",
}


def windows_file_url(path):
    value = str(path or "").strip().replace("\\", "/")
    if not value:
        return ""
    if value.startswith("//"):
        return "file:" + quote(value, safe="/:")
    if re.match(r"^[A-Za-z]:/", value):
        return "file:///" + quote(value, safe="/:")
    return ""


def datetime_minute(value):
    text = str(value or "").strip()
    if not text:
        return "-"
    return text.replace("T", " ")[:16]
VIDEO_EXPORT_VALUES = ("해당없음", "아니오", "예")
EXPORT_PLEDGE_VALUES = ("해당없음", "미접수", "접수완료", "확인완료")
ATTACHMENT_TYPES = ("일반자료", "공문", "회신공문", "영상자료", "반출확약서", "기타")
ALLOWED_SORTS = {
    "receipt_date": "d.receipt_date",
    "registered_at": "d.registered_at",
    "organization": "d.organization",
    "manager": "d.manager",
    "management_number": "d.management_number",
}


class OfficialDocumentError(ValueError):
    pass


def normalize_date(value, required=False):
    raw = str(value or "").strip()
    if not raw:
        if required:
            raise OfficialDocumentError("필수 날짜를 입력해주세요.")
        return None
    digits = re.sub(r"[^0-9]", "", raw)
    if len(digits) != 8:
        raise OfficialDocumentError(f"날짜 형식이 올바르지 않습니다: {raw}")
    try:
        return datetime.strptime(digits, "%Y%m%d").date().isoformat()
    except ValueError as error:
        raise OfficialDocumentError(f"유효하지 않은 날짜입니다: {raw}") from error


def sanitize_windows_component(value):
    text = unicodedata.normalize("NFKC", str(value or ""))
    text = re.sub(r'[\\/:*?"<>|\r\n\t]', "_", text)
    text = text.replace(" ", "")
    text = re.sub(r"_+", "_", text).strip("_. ")
    return text


def build_archive_folder_name(receipt_date, category_label, organization, request_content):
    day = normalize_date(receipt_date, required=True).replace("-", ".")
    category = sanitize_windows_component(category_label)
    org = sanitize_windows_component(organization)
    prefix = f"{day}_{category}_{org}_"
    available = max(0, 120 - len(prefix))
    request_part = sanitize_windows_component(request_content)[:available].rstrip("_.")
    return (prefix + request_part).rstrip("_")[:120]


def _organization_alias_key(value):
    """띄어쓰기와 서울 접두어가 다른 경찰서 표기를 같은 기관으로 비교한다."""
    compact = re.sub(r"[^0-9A-Za-z가-힣]", "", str(value or "")).casefold()
    if compact.startswith("서울") and compact.endswith("경찰서"):
        compact = compact[2:]
    return compact


def canonicalize_organization(connection, value):
    """기존 사용 이력과 표기 규칙으로 기관명을 한 가지 대표 이름으로 통일한다."""
    raw = str(value or "").strip()
    if not raw:
        return ""
    normalized = (
        re.sub(r"\s+", "", raw)
        if re.search(r"[가-힣]", raw)
        else re.sub(r"\s+", " ", raw)
    )
    alias_key = _organization_alias_key(normalized)
    if not alias_key:
        return normalized
    rows = connection.execute(
        """
        SELECT organization, COUNT(*) AS usage_count
        FROM official_documents
        WHERE organization IS NOT NULL AND TRIM(organization) != ''
        GROUP BY organization
        """
    ).fetchall()
    candidates = []
    for row in rows:
        candidate = str(row["organization"] or "").strip()
        if _organization_alias_key(candidate) != alias_key:
            continue
        compact = re.sub(r"\s+", "", candidate)
        candidates.append((
            int(compact.startswith("서울") and compact.endswith("경찰서")),
            int(row["usage_count"] or 0),
            -len(compact),
            compact,
        ))
    return max(candidates)[-1] if candidates else normalized


def list_reference_values(connection, kind, active_only=True):
    where = "AND active = 1" if active_only else ""
    return [
        dict(row) for row in connection.execute(
            f"""
            SELECT * FROM official_doc_reference_values
            WHERE kind = ? {where}
            ORDER BY sort_order, id
            """,
            (kind,),
        ).fetchall()
    ]


def get_reference(connection, kind, code, active_only=True):
    suffix = " AND active = 1" if active_only else ""
    row = connection.execute(
        f"SELECT * FROM official_doc_reference_values WHERE kind = ? AND code = ?{suffix}",
        (kind, code),
    ).fetchone()
    return dict(row) if row else None


def _safe_original_filename(filename):
    raw = unicodedata.normalize("NFKC", str(filename or "")).replace("\\", "/")
    name = raw.rsplit("/", 1)[-1].strip()
    name = "".join(char for char in name if char >= " " and char != "\x7f")
    if not name.casefold().endswith(".pdf") or not name[:-4].strip(". "):
        raise OfficialDocumentError("PDF 파일만 등록할 수 있습니다.")
    return f"{name[:-4].strip()[:175]}.pdf"


def save_temp_pdf(file_storage):
    original = _safe_original_filename(file_storage.filename)
    allowed_mimes = {"application/pdf", "application/x-pdf", "application/octet-stream", ""}
    if (file_storage.mimetype or "").casefold() not in allowed_mimes:
        raise OfficialDocumentError(f"PDF MIME 형식이 아닙니다: {original}")
    max_bytes = config.OFFICIAL_DOC_MAX_UPLOAD_MB * 1024 * 1024
    raw = file_storage.read(max_bytes + 1)
    if not raw:
        raise OfficialDocumentError(f"빈 파일은 등록할 수 없습니다: {original}")
    if len(raw) > max_bytes:
        raise OfficialDocumentError(f"PDF는 파일당 {config.OFFICIAL_DOC_MAX_UPLOAD_MB}MB 이하여야 합니다.")
    try:
        pdf_security.validate_pdf_content(raw)
    except pdf_security.PdfSecurityError as error:
        raise OfficialDocumentError(f"{original}: {error}") from error
    directory = Path(config.OFFICIAL_DOC_TEMP_DIR).resolve()
    directory.mkdir(parents=True, exist_ok=True)
    temp_name = f"{uuid.uuid4().hex}.pdf"
    path = directory / temp_name
    path.write_bytes(raw)
    try:
        pdf_security.scan_file(path)
    except pdf_security.PdfSecurityError as error:
        path.unlink(missing_ok=True)
        raise OfficialDocumentError(f"{original}: {error}") from error
    return {
        "original_filename": original,
        "temp_filename": temp_name,
        "file_size": len(raw),
        "mime_type": "application/pdf",
        "sha256": hashlib.sha256(raw).hexdigest(),
        "path": path,
    }


def temp_file_path(temp_filename):
    base = Path(config.OFFICIAL_DOC_TEMP_DIR).resolve()
    candidate = (base / Path(str(temp_filename or "")).name).resolve()
    if candidate.parent != base:
        raise OfficialDocumentError("잘못된 임시파일 경로입니다.")
    return candidate


def validate_form(connection, form):
    errors = {}
    required = {
        "category_code": "분류", "folder_category_code": "폴더구분",
        "manager": "담당", "receipt_date": "접수일",
        "organization": "기관명(회사명)", "request_content": "요청내용",
    }
    for field, label in required.items():
        if not str(form.get(field) or "").strip():
            errors[field] = f"{label}을(를) 입력해주세요."
    category = get_reference(connection, "category", form.get("category_code"))
    folder = get_reference(connection, "folder_category", form.get("folder_category_code"))
    if form.get("category_code") and not category:
        errors["category_code"] = "허용된 분류를 선택해주세요."
    if form.get("folder_category_code") and not folder:
        errors["folder_category_code"] = "허용된 폴더구분을 선택해주세요."
    if form.get("category_code") == "OTHER" and not str(form.get("category_detail") or "").strip():
        errors["category_detail"] = "기타 분류의 세부내용을 입력해주세요."
    if form.get("folder_category_code") == "078" and not str(form.get("folder_category_detail") or "").strip():
        errors["folder_category_detail"] = "기타 폴더구분의 세부내용을 입력해주세요."
    try:
        receipt_date = normalize_date(form.get("receipt_date"), required=True)
    except OfficialDocumentError as error:
        errors["receipt_date"] = str(error)
        receipt_date = None
    try:
        reply_date = normalize_date(form.get("reply_date"))
    except OfficialDocumentError as error:
        errors["reply_date"] = str(error)
        reply_date = None
    email = str(form.get("email") or "").strip()
    if email and not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", email):
        errors["email"] = "이메일 형식을 확인해주세요."
    video = form.get("video_exported") or "해당없음"
    pledge = form.get("export_pledge") or ("미접수" if video == "예" else "해당없음")
    if video not in VIDEO_EXPORT_VALUES:
        errors["video_exported"] = "영상반출여부 값이 올바르지 않습니다."
    if pledge not in EXPORT_PLEDGE_VALUES:
        errors["export_pledge"] = "반출확약서 상태가 올바르지 않습니다."
    handling = form.get("folder_handling_type") or "CREATE_NEW"
    if handling not in ("CREATE_NEW", "LINK_EXISTING"):
        errors["folder_handling_type"] = "폴더 처리방식을 다시 선택해주세요."
    requested_path = str(form.get("requested_folder_path") or "").strip()
    if handling == "LINK_EXISTING" and not requested_path:
        errors["requested_folder_path"] = "연결할 기존 폴더 경로를 입력하거나 검색 결과에서 선택해주세요."
    if requested_path and (".." in requested_path.replace("/", "\\").split("\\")):
        errors["requested_folder_path"] = "상위 경로 이동(..)은 사용할 수 없습니다."
    return errors, receipt_date, reply_date, category, folder, video, pledge


def find_duplicate_candidates(connection, form, receipt_date):
    if not receipt_date:
        return []
    comparisons = (
        ("category_code", form.get("category_code")),
        ("receipt_number", form.get("receipt_number")),
        ("organization", canonicalize_organization(connection, form.get("organization"))),
        ("requester", form.get("requester")),
        ("contact", form.get("contact")),
        ("case_name", form.get("case_name")),
        ("request_content", form.get("request_content")),
    )
    clauses, params = [], [receipt_date]
    for field, value in comparisons:
        value = str(value or "").strip()
        if value:
            clauses.append(f"{field} = ?")
            params.append(value)
    if not clauses:
        return []
    rows = connection.execute(
        f"""
        SELECT id, management_number, receipt_number, organization, case_name, request_content
        FROM official_documents
        WHERE is_active = 1 AND receipt_date = ? AND ({' OR '.join(clauses)})
        ORDER BY registered_at DESC LIMIT 10
        """,
        params,
    ).fetchall()
    return [dict(row) for row in rows]


def _next_management_number(connection, receipt_date, category_label):
    base = f"{receipt_date[2:4]}.{receipt_date[5:7]}.{receipt_date[8:10]}_{category_label}"
    rows = connection.execute(
        "SELECT management_number FROM official_documents WHERE management_number = ? OR management_number LIKE ?",
        (base, f"{base}_%"),
    ).fetchall()
    used = {row["management_number"] for row in rows}
    if base not in used:
        return base
    number = 2
    while f"{base}_{number}" in used:
        number += 1
    return f"{base}_{number}"


def _next_receipt_number(connection, receipt_date, manager):
    """Issue YYMMDD_manager_NNNN, incrementing per manager within each year."""
    manager_name = str(manager or "").strip()
    safe_manager = sanitize_windows_component(manager_name) or "담당자"
    year = receipt_date[:4]
    date_part = receipt_date[2:4] + receipt_date[5:7] + receipt_date[8:10]
    rows = connection.execute(
        """
        SELECT receipt_number FROM official_documents
        WHERE substr(receipt_date, 1, 4)=? AND manager=?
              AND receipt_number IS NOT NULL
        """,
        (year, manager_name),
    ).fetchall()
    pattern = re.compile(rf"^\d{{6}}_{re.escape(safe_manager)}_(\d{{4,}})$")
    highest = 0
    for row in rows:
        match = pattern.match(str(row["receipt_number"] or ""))
        if match:
            highest = max(highest, int(match.group(1)))
    counter = connection.execute(
        "SELECT last_sequence FROM official_receipt_counters WHERE year=? AND manager=?",
        (year, manager_name),
    ).fetchone()
    if counter:
        highest = max(highest, int(counter["last_sequence"]))
    sequence = highest + 1
    connection.execute(
        """
        INSERT INTO official_receipt_counters (year, manager, last_sequence, updated_at)
        VALUES (?, ?, ?, ?)
        ON CONFLICT(year, manager) DO UPDATE SET
            last_sequence=excluded.last_sequence, updated_at=excluded.updated_at
        """,
        (year, manager_name, sequence, now_kst().isoformat()),
    )
    return f"{date_part}_{safe_manager}_{sequence:04d}"


def log_history(connection, document_id, action, actor=None, attachment_id=None, client_name=None, detail=None):
    detail_json = json.dumps(detail or {}, ensure_ascii=False)
    cursor = connection.execute(
        """
        INSERT INTO official_document_history
            (document_id, attachment_id, action, actor, client_name, detail_json, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            document_id, attachment_id, action, actor, client_name,
            detail_json, now_kst().isoformat(),
        ),
    )
    management_number = None
    if document_id:
        row = connection.execute(
            "SELECT management_number FROM official_documents WHERE id=?", (document_id,)
        ).fetchone()
        management_number = row["management_number"] if row else None
    connection.execute(
        """
        INSERT INTO official_document_change_log
            (source_history_id, document_id, management_number, attachment_id,
             action, actor, client_name, detail_json, created_at)
        SELECT id, document_id, ?, attachment_id, action, actor, client_name,
               detail_json, created_at
        FROM official_document_history WHERE id=?
        """,
        (management_number, cursor.lastrowid),
    )


def soft_delete_document(connection, document_id, actor):
    row = connection.execute(
        "SELECT id, management_number, is_active FROM official_documents WHERE id=?",
        (document_id,),
    ).fetchone()
    if not row or not row["is_active"]:
        return False
    deleted_at = now_kst()
    delete_after = deleted_at + timedelta(days=30)
    connection.execute(
        """
        UPDATE official_documents
        SET is_active=0, deleted_at=?, delete_after=?, deleted_by=?,
            file_delete_status='PENDING', file_deleted_at=NULL,
            file_delete_client=NULL, file_delete_error=NULL, updated_at=?
        WHERE id=?
        """,
        (
            deleted_at.isoformat(), delete_after.isoformat(), actor,
            deleted_at.isoformat(), document_id,
        ),
    )
    log_history(
        connection, document_id, "DOCUMENT_MOVED_TO_TRASH", actor=actor,
        detail={"delete_after": delete_after.isoformat(), "retention_days": 30},
    )
    return True


def restore_document(connection, document_id, actor):
    row = connection.execute(
        "SELECT id, is_active, delete_after FROM official_documents WHERE id=?",
        (document_id,),
    ).fetchone()
    if not row or row["is_active"] or not row["delete_after"]:
        return False
    now_iso = now_kst().isoformat()
    connection.execute(
        """
        UPDATE official_documents
        SET is_active=1, deleted_at=NULL, delete_after=NULL, deleted_by=NULL,
            file_delete_status=NULL, file_deleted_at=NULL, file_delete_client=NULL,
            file_delete_error=NULL, updated_at=?
        WHERE id=?
        """,
        (now_iso, document_id),
    )
    log_history(connection, document_id, "DOCUMENT_RESTORED", actor=actor)
    return True


def purge_expired_documents(connection, now=None):
    now = now or now_kst()
    rows = connection.execute(
        """
        SELECT id, management_number FROM official_documents
        WHERE is_active=0 AND delete_after IS NOT NULL AND delete_after<=?
              AND file_delete_status='DELETED'
        """,
        (now.isoformat(),),
    ).fetchall()
    purged = 0
    for row in rows:
        attachments = connection.execute(
            "SELECT temp_filename FROM official_document_attachments WHERE document_id=?",
            (row["id"],),
        ).fetchall()
        log_history(
            connection, row["id"], "DOCUMENT_PURGED_AFTER_30_DAYS", actor="SYSTEM",
            detail={"management_number": row["management_number"]},
        )
        for attachment in attachments:
            if attachment["temp_filename"]:
                temp_file_path(attachment["temp_filename"]).unlink(missing_ok=True)
        connection.execute(
            "DELETE FROM official_document_attachments WHERE document_id=?", (row["id"],)
        )
        connection.execute(
            "DELETE FROM official_document_history WHERE document_id=?", (row["id"],)
        )
        connection.execute("DELETE FROM official_documents WHERE id=?", (row["id"],))
        purged += 1
    return purged


def list_deleted_documents(connection):
    return [
        dict(row) for row in connection.execute(
            """
            SELECT id, management_number, organization, receipt_date, deleted_at,
                   delete_after, deleted_by, file_delete_status, file_delete_error
            FROM official_documents
            WHERE is_active=0 AND delete_after IS NOT NULL
            ORDER BY deleted_at DESC
            """
        ).fetchall()
    ]


def create_document(connection, form, files, user):
    errors, receipt_date, reply_date, category, folder, video, pledge = validate_form(connection, form)
    handling = form.get("folder_handling_type") or "CREATE_NEW"
    if handling == "CREATE_NEW" and not files:
        errors["attachments"] = "PDF 파일을 1개 이상 등록해주세요."
    if errors:
        return None, errors
    saved = []
    try:
        for uploaded in files:
            if uploaded and uploaded.filename:
                saved.append(save_temp_pdf(uploaded))
        if handling == "CREATE_NEW" and not saved:
            return None, {"attachments": "PDF 파일을 1개 이상 등록해주세요."}
        hashes = [item["sha256"] for item in saved]
        if hashes:
            placeholders = ",".join("?" for _ in hashes)
            duplicates = connection.execute(
                f"SELECT original_filename FROM official_document_attachments WHERE sha256 IN ({placeholders})",
                hashes,
            ).fetchall()
            if duplicates:
                raise OfficialDocumentError(
                    "동일한 SHA-256 파일이 이미 등록되어 있습니다: "
                    + ", ".join(row["original_filename"] for row in duplicates)
                )
        connection.execute("BEGIN IMMEDIATE")
        management_number = _next_management_number(connection, receipt_date, category["label"])
        receipt_number = _next_receipt_number(connection, receipt_date, form.get("manager"))
        now_iso = now_kst().isoformat()
        organization = canonicalize_organization(connection, form.get("organization"))
        cursor = connection.execute(
            """
            INSERT INTO official_documents (
                management_number, receipt_number, manager, receipt_date, organization,
                case_name, request_content, special_note, requester, contact, email,
                dispatch_number, reply_date, location, legacy_location, video_exported,
                export_pledge, category_code, category_detail, folder_category_code,
                folder_category_detail, processing_result, registered_by, registered_user_id,
                registered_at, updated_at, temp_file_status, storage_status, sha256_hash,
                duplicate_warning_ack, folder_handling_type, requested_folder_path,
                folder_display_name, folder_link_status, folder_link_note
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                management_number, receipt_number, form.get("manager"), receipt_date,
                organization, form.get("case_name"), form.get("request_content"),
                form.get("special_note"), form.get("requester"), form.get("contact"),
                form.get("email"), form.get("dispatch_number"), reply_date, form.get("location"),
                form.get("location"), video, pledge, category["code"], form.get("category_detail"),
                folder["code"], form.get("folder_category_detail"),
                form.get("processing_result") or "처리 필요", user.get("username") or "unknown",
                user.get("id"), now_iso, now_iso,
                "UPLOADED" if saved else "LINK_PENDING",
                "UPLOADED",
                saved[0]["sha256"] if len(saved) == 1 else None,
                1 if str(form.get("duplicate_ack") or "") == "1" else 0,
                handling, str(form.get("requested_folder_path") or "").strip() or None,
                str(form.get("folder_display_name") or "").strip() or None,
                "LINK_PENDING" if handling == "LINK_EXISTING" else None,
                str(form.get("folder_link_note") or "").strip() or None,
            ),
        )
        document_id = cursor.lastrowid
        types = form.getlist("attachment_type") if hasattr(form, "getlist") else []
        for index, item in enumerate(saved):
            attachment_type = types[index] if index < len(types) else "일반자료"
            if attachment_type not in ATTACHMENT_TYPES:
                attachment_type = "일반자료"
            attachment_cursor = connection.execute(
                """
                INSERT INTO official_document_attachments (
                    document_id, attachment_type, original_filename, temp_filename,
                    file_size, mime_type, sha256, temp_status, registered_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, 'UPLOADED', ?)
                """,
                (
                    document_id, attachment_type, item["original_filename"], item["temp_filename"],
                    item["file_size"], item["mime_type"], item["sha256"], now_iso,
                ),
            )
            log_history(
                connection, document_id, "ATTACHMENT_UPLOADED",
                actor=user.get("username"), attachment_id=attachment_cursor.lastrowid,
                detail={"filename": item["original_filename"], "sha256": item["sha256"]},
            )
        log_history(
            connection, document_id, "DOCUMENT_REGISTERED", actor=user.get("username"),
            detail={"management_number": management_number, "receipt_number": receipt_number},
        )
        connection.commit()
        return document_id, None
    except Exception:
        connection.rollback()
        for item in saved:
            item["path"].unlink(missing_ok=True)
        raise


def review_reasons(document, today=None):
    today = today or date.today()
    reasons = []
    try:
        age = (today - date.fromisoformat(document["receipt_date"])).days
    except (TypeError, ValueError):
        age = 0
    incomplete = document.get("processing_result") != "완료"
    if incomplete:
        reasons.append("접수 후 7일 경과" if age >= 7 else "처리 필요")
    if document.get("storage_status") == "FAILED":
        reasons.append("Y디스크 저장 실패")
    if document.get("storage_status") == "MISSING":
        reasons.append("최종 파일 누락")
    if document.get("storage_status") == "STORED" and (
        not document.get("location") or not document.get("file_count")
    ):
        reasons.append("자료 부족")
    if document.get("video_exported") == "예" and document.get("export_pledge") != "확인완료":
        reasons.append("반출확약서 확인 필요")
    return reasons


def get_document(connection, document_id):
    row = connection.execute(
        """
        SELECT d.*, c.label AS category_label, f.label AS folder_category_label
        FROM official_documents d
        LEFT JOIN official_doc_reference_values c ON c.kind='category' AND c.code=d.category_code
        LEFT JOIN official_doc_reference_values f ON f.kind='folder_category' AND f.code=d.folder_category_code
        WHERE d.id = ?
        """,
        (document_id,),
    ).fetchone()
    if not row:
        return None
    item = dict(row)
    item["attachments"] = [
        dict(value) for value in connection.execute(
            "SELECT * FROM official_document_attachments WHERE document_id = ? ORDER BY id",
            (document_id,),
        ).fetchall()
    ]
    item["review_reasons"] = review_reasons(item)
    return item


def list_documents(connection, filters=None, page=1, per_page=30, review_only=False):
    filters = filters or {}
    clauses = ["d.is_active = 1"]
    params = []
    for field in (
        "category_code", "folder_category_code", "storage_status",
        "video_exported", "export_pledge", "processing_result",
    ):
        value = str(filters.get(field) or "").strip()
        if value:
            clauses.append(f"d.{field} = ?")
            params.append(value)
    manager_name = str(filters.get("manager") or "").strip()
    if manager_name:
        clauses.append("d.manager LIKE ?")
        params.append(f"%{manager_name}%")
    registered_by = str(filters.get("registered_by") or "").strip()
    if registered_by:
        clauses.append("d.registered_by LIKE ?")
        params.append(f"%{registered_by}%")
    organization = str(filters.get("organization") or "").strip()
    if organization:
        clauses.append("d.organization LIKE ?")
        params.append(f"%{organization}%")
    year = str(filters.get("year") or "").strip()
    if year:
        clauses.append("substr(d.receipt_date, 1, 4) = ?")
        params.append(year)
    registered_user_id = filters.get("registered_user_id")
    if registered_user_id:
        clauses.append("d.registered_user_id = ?")
        params.append(int(registered_user_id))
    term = str(filters.get("q") or "").strip()
    if term:
        pattern = f"%{term}%"
        clauses.append(
            "(d.management_number LIKE ? OR d.receipt_number LIKE ? OR d.organization LIKE ? "
            "OR d.case_name LIKE ? OR d.request_content LIKE ? OR d.requester LIKE ? OR d.dispatch_number LIKE ?)"
        )
        params.extend([pattern] * 7)
    if filters.get("date_from"):
        clauses.append("d.receipt_date >= ?")
        params.append(normalize_date(filters["date_from"]))
    if filters.get("date_to"):
        clauses.append("d.receipt_date <= ?")
        params.append(normalize_date(filters["date_to"]))
    if review_only:
        clauses.append(
            "(COALESCE(d.processing_result, '') != '완료' "
            "OR d.storage_status IN ('FAILED', 'MISSING') "
            "OR (d.storage_status = 'STORED' AND "
            "(d.location IS NULL OR TRIM(d.location) = '' OR d.file_count = 0)) "
            "OR (d.video_exported = '예' AND d.export_pledge != '확인완료'))"
        )
    sort_sql = ALLOWED_SORTS.get(filters.get("sort"), "d.receipt_date")
    direction = "ASC" if filters.get("direction") == "asc" else "DESC"
    where_sql = " AND ".join(clauses)
    total = connection.execute(
        f"SELECT COUNT(*) FROM official_documents d WHERE {where_sql}",
        params,
    ).fetchone()[0]
    page = max(1, int(page))
    per_page = max(1, int(per_page))
    offset = (page - 1) * per_page
    rows = connection.execute(
        f"""
        SELECT d.*, c.label AS category_label, f.label AS folder_category_label
        FROM official_documents d
        LEFT JOIN official_doc_reference_values c ON c.kind='category' AND c.code=d.category_code
        LEFT JOIN official_doc_reference_values f ON f.kind='folder_category' AND f.code=d.folder_category_code
        WHERE {where_sql}
        ORDER BY {sort_sql} {direction}, d.id DESC
        LIMIT ? OFFSET ?
        """,
        (*params, per_page, offset),
    ).fetchall()
    items = [dict(row) for row in rows]
    for item in items:
        item["review_reasons"] = review_reasons(item)
    return items, total


def list_documents_by_ids(connection, document_ids, registered_user_id=None):
    """Return only explicitly selected active documents, independent of list filters."""
    ids = [int(value) for value in dict.fromkeys(document_ids) if int(value) > 0]
    if not ids:
        return []
    placeholders = ",".join("?" for _ in ids)
    owner_clause = ""
    params = list(ids)
    if registered_user_id is not None:
        owner_clause = " AND d.registered_user_id=?"
        params.append(int(registered_user_id))
    rows = connection.execute(
        f"""
        SELECT d.*, c.label AS category_label, f.label AS folder_category_label
        FROM official_documents d
        LEFT JOIN official_doc_reference_values c
          ON c.kind='category' AND c.code=d.category_code
        LEFT JOIN official_doc_reference_values f
          ON f.kind='folder_category' AND f.code=d.folder_category_code
        WHERE d.is_active=1 AND d.id IN ({placeholders}){owner_clause}
        """,
        params,
    ).fetchall()
    by_id = {row["id"]: dict(row) for row in rows}
    return [by_id[item_id] for item_id in ids if item_id in by_id]


def dashboard_metrics(connection, filters=None):
    documents, _ = list_documents(connection, filters, per_page=100000)
    today_str = date.today().isoformat()
    return {
        "total": len(documents),
        "today": sum(item["receipt_date"] == today_str for item in documents),
        "incomplete": sum(item["processing_result"] != "완료" for item in documents),
        "overdue": sum("접수 후 7일 경과" in item["review_reasons"] for item in documents),
        "pending": sum(item["storage_status"] == "UPLOADED" for item in documents),
        "failed": sum(item["storage_status"] == "FAILED" for item in documents),
        "missing": sum(item["storage_status"] == "MISSING" for item in documents),
        "pledge": sum("반출확약서 확인 필요" in item["review_reasons"] for item in documents),
    }


def data_update_status(connection):
    document_row = connection.execute(
        "SELECT MAX(updated_at) AS updated_at FROM official_documents"
    ).fetchone()
    folder_row = connection.execute(
        "SELECT MAX(last_scanned_at) AS updated_at FROM official_folder_index"
    ).fetchone()
    document_updated_at = document_row["updated_at"] if document_row else None
    folder_updated_at = folder_row["updated_at"] if folder_row else None
    candidates = [value for value in (document_updated_at, folder_updated_at) if value]
    return {
        "document_updated_at": document_updated_at,
        "folder_updated_at": folder_updated_at,
        "latest_updated_at": max(candidates) if candidates else None,
    }


def list_history(connection, limit=300):
    return [
        dict(row) for row in connection.execute(
            """
            SELECT h.*, d.management_number
            FROM official_document_history h
            LEFT JOIN official_documents d ON d.id = h.document_id
            ORDER BY h.created_at DESC LIMIT ?
            """,
            (int(limit),),
        ).fetchall()
    ]


def list_change_log(connection, limit=500):
    return [
        dict(row) for row in connection.execute(
            """
            SELECT * FROM official_document_change_log
            ORDER BY created_at DESC LIMIT ?
            """,
            (int(limit),),
        ).fetchall()
    ]
