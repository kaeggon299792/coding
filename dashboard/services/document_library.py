"""인증된 리서치 업로드 파일의 검증·보관·PDF 텍스트 추출."""

import hashlib
import json
import os
import subprocess
import sys
import unicodedata
import uuid
from pathlib import Path

import config
from services import pdf_security


class DocumentUploadError(ValueError):
    pass


def ensure_library_dir():
    path = Path(config.RESEARCH_LIBRARY_DIR).resolve()
    path.mkdir(parents=True, exist_ok=True)
    return path


def _validated_original_name(filename):
    # 실제 저장명은 UUID를 사용하므로 표시용 원본 파일명은 한글을 보존한다.
    # 브라우저가 Windows 경로를 보내는 경우와 경로 순회 문자열은 basename으로 제거한다.
    raw_name = unicodedata.normalize("NFKC", str(filename or "")).replace("\\", "/")
    name = raw_name.rsplit("/", 1)[-1].strip()
    name = "".join(character for character in name if character >= " " and character != "\x7f")
    if not name or not name.casefold().endswith(".pdf"):
        raise DocumentUploadError("PDF 파일만 업로드할 수 있습니다.")
    stem = name[:-4].strip().strip(".")
    if not stem:
        raise DocumentUploadError("파일명을 확인해주세요.")
    return f"{stem[:175]}.pdf"


def _extract_in_subprocess(raw):
    command = [
        sys.executable, str(Path(__file__).with_name("pdf_worker.py")),
        str(config.RESEARCH_MAX_FILE_BYTES), str(config.RESEARCH_MAX_PDF_PAGES),
        str(config.RESEARCH_MAX_EXTRACTED_CHARS),
        str(config.RESEARCH_PDF_PROCESS_MEMORY_MB),
        str(config.RESEARCH_PDF_PROCESS_CPU_SECONDS),
    ]
    try:
        completed = subprocess.run(
            command, input=raw, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
            timeout=config.RESEARCH_PDF_PROCESS_TIMEOUT_SECONDS, check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        raise DocumentUploadError(
            "PDF 처리 시간이 초과되었거나 처리기를 실행할 수 없습니다."
        ) from error
    try:
        payload = json.loads(completed.stdout.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError, AttributeError) as error:
        raise DocumentUploadError("PDF 처리 중 오류가 발생했습니다.") from error
    if not payload.get("ok"):
        if payload.get("kind") == "invalid" and payload.get("message"):
            raise DocumentUploadError(str(payload["message"]))
        raise DocumentUploadError("PDF 내용을 안전하게 처리할 수 없습니다.")
    return int(payload["page_count"]), str(payload.get("text") or "")


def save_and_extract(file_storage):
    original_name = _validated_original_name(file_storage.filename)
    raw = file_storage.read(config.RESEARCH_MAX_FILE_BYTES + 1)
    if not raw:
        raise DocumentUploadError("빈 파일은 업로드할 수 없습니다.")
    if len(raw) > config.RESEARCH_MAX_FILE_BYTES:
        max_mb = config.RESEARCH_MAX_FILE_BYTES // (1024 * 1024)
        raise DocumentUploadError(f"파일은 {max_mb}MB 이하만 업로드할 수 있습니다.")
    digest = hashlib.sha256(raw).hexdigest()
    stored_name = f"{uuid.uuid4().hex}.pdf"
    target = ensure_library_dir() / stored_name
    target.write_bytes(raw)

    try:
        pdf_security.scan_file(target)
        page_count, extracted_text = _extract_in_subprocess(raw)
        status = "complete" if extracted_text else "no_text"
        return {
            "original_filename": original_name,
            "stored_filename": stored_name,
            "mime_type": "application/pdf",
            "file_size": len(raw),
            "sha256": digest,
            "page_count": page_count,
            "extracted_text": extracted_text,
            "extraction_status": status,
            "path": target,
        }
    except (DocumentUploadError, pdf_security.PdfSecurityError) as error:
        target.unlink(missing_ok=True)
        if isinstance(error, (DocumentUploadError, pdf_security.PdfSecurityError)):
            if isinstance(error, pdf_security.PdfSecurityError):
                raise DocumentUploadError(str(error)) from error
            raise
        raise DocumentUploadError("PDF 내용을 읽을 수 없습니다.") from error
    except Exception as error:
        target.unlink(missing_ok=True)
        raise DocumentUploadError("PDF 처리 중 오류가 발생했습니다.") from error


def document_path(stored_filename):
    base = ensure_library_dir()
    candidate = (base / os.path.basename(stored_filename or "")).resolve()
    if candidate.parent != base:
        raise DocumentUploadError("잘못된 파일 경로입니다.")
    return candidate


def remove_file(stored_filename):
    document_path(stored_filename).unlink(missing_ok=True)
