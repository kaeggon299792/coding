"""인증된 자료실 업로드 파일의 검증·보관·PDF 텍스트 추출."""

import hashlib
import os
import unicodedata
import uuid
from pathlib import Path

from pypdf import PdfReader
from pypdf.errors import PdfReadError
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


def save_and_extract(file_storage):
    original_name = _validated_original_name(file_storage.filename)
    raw = file_storage.read(config.RESEARCH_MAX_FILE_BYTES + 1)
    if not raw:
        raise DocumentUploadError("빈 파일은 업로드할 수 없습니다.")
    if len(raw) > config.RESEARCH_MAX_FILE_BYTES:
        max_mb = config.RESEARCH_MAX_FILE_BYTES // (1024 * 1024)
        raise DocumentUploadError(f"파일은 {max_mb}MB 이하만 업로드할 수 있습니다.")
    try:
        page_count = pdf_security.validate_pdf_content(raw)
    except pdf_security.PdfSecurityError as error:
        raise DocumentUploadError(str(error)) from error

    digest = hashlib.sha256(raw).hexdigest()
    stored_name = f"{uuid.uuid4().hex}.pdf"
    target = ensure_library_dir() / stored_name
    target.write_bytes(raw)

    try:
        pdf_security.scan_file(target)
        reader = PdfReader(str(target))
        chunks = []
        current_chars = 0
        for page in reader.pages[: config.RESEARCH_MAX_PDF_PAGES]:
            text = (page.extract_text() or "").strip()
            if not text:
                continue
            remaining = config.RESEARCH_MAX_EXTRACTED_CHARS - current_chars
            if remaining <= 0:
                break
            chunks.append(text[:remaining])
            current_chars += len(chunks[-1])
        extracted_text = "\n\n".join(chunks).strip()
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
    except (PdfReadError, DocumentUploadError, pdf_security.PdfSecurityError) as error:
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
