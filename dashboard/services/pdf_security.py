"""Shared PDF content validation and optional ClamAV scanning."""

import shutil
import subprocess
from io import BytesIO

from pypdf import PdfReader
from pypdf.errors import PdfReadError


class PdfSecurityError(ValueError):
    pass


def _resolved(value):
    return value.get_object() if hasattr(value, "get_object") else value


def validate_pdf_content(raw, max_pages=2000):
    if not raw.startswith(b"%PDF-"):
        raise PdfSecurityError("PDF 파일 시그니처가 올바르지 않습니다.")
    if b"%%EOF" not in raw[-8192:]:
        raise PdfSecurityError("완전한 PDF 파일이 아니거나 파일 끝부분이 손상되었습니다.")
    try:
        reader = PdfReader(BytesIO(raw), strict=False)
        if reader.is_encrypted:
            raise PdfSecurityError("암호화된 PDF는 업로드할 수 없습니다.")
        page_count = len(reader.pages)
        if page_count < 1:
            raise PdfSecurityError("페이지가 없는 PDF는 업로드할 수 없습니다.")
        if page_count > max_pages:
            raise PdfSecurityError(f"PDF 페이지 수는 {max_pages}쪽을 초과할 수 없습니다.")

        root = _resolved(reader.trailer.get("/Root")) or {}
        dangerous = {"/OpenAction", "/AA"}
        if any(key in root for key in dangerous):
            raise PdfSecurityError("자동 실행 기능이 포함된 PDF는 업로드할 수 없습니다.")
        names = _resolved(root.get("/Names")) if hasattr(root, "get") else None
        if names and any(key in names for key in ("/JavaScript", "/EmbeddedFiles")):
            raise PdfSecurityError("스크립트 또는 첨부파일이 포함된 PDF는 업로드할 수 없습니다.")
        if hasattr(root, "get") and root.get("/AcroForm"):
            form = _resolved(root.get("/AcroForm")) or {}
            if "/XFA" in form:
                raise PdfSecurityError("XFA 양식이 포함된 PDF는 업로드할 수 없습니다.")
        return page_count
    except PdfSecurityError:
        raise
    except (PdfReadError, OSError, ValueError, TypeError, KeyError) as error:
        raise PdfSecurityError("PDF 내부 구조를 읽을 수 없습니다.") from error


def scan_file(path):
    """Scan with ClamAV when installed. Returns clean or unavailable."""
    executable = shutil.which("clamscan")
    if not executable:
        return "unavailable"
    try:
        result = subprocess.run(
            [executable, "--no-summary", str(path)],
            capture_output=True,
            text=True,
            timeout=45,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        raise PdfSecurityError("악성코드 검사기를 정상 실행하지 못했습니다.") from error
    if result.returncode == 0:
        return "clean"
    if result.returncode == 1:
        raise PdfSecurityError("악성코드가 탐지되어 업로드가 차단되었습니다.")
    raise PdfSecurityError("악성코드 검사 중 오류가 발생했습니다.")
