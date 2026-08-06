"""Native CASINO IN controls for the portfolio's public Sharepoint files."""

import mimetypes
import os
import re
import secrets
import unicodedata
from pathlib import Path
from urllib.parse import quote

import config


PUBLIC_BASE = "https://shingoon.me/Sharepoint/"
ALLOWED_EXTENSIONS = {
    "csv", "docx", "gif", "jpeg", "jpg", "pdf", "png", "pptx",
    "txt", "webp", "xlsx", "zip",
}
_SAFE_NAME = re.compile(r"^[^/\\\x00-\x1f\x7f]+$")


def _root():
    return Path(config.PORTFOLIO_SHAREPOINT_DIR).resolve()


def _normalized_name(raw_name):
    name = unicodedata.normalize("NFC", str(raw_name or "").strip())
    if not name or name in {".", ".."} or not _SAFE_NAME.fullmatch(name):
        raise ValueError("안전하지 않은 파일명입니다.")
    if name.startswith(".") or len(name) > 180:
        raise ValueError("허용되지 않는 파일명입니다.")
    extension = Path(name).suffix.lower().lstrip(".")
    if extension not in ALLOWED_EXTENSIONS:
        raise ValueError("허용되지 않는 파일 형식입니다.")
    return name


def _validate_signature(extension, head):
    signatures = {
        "png": (b"\x89PNG\r\n\x1a\n",),
        "jpg": (b"\xff\xd8\xff",), "jpeg": (b"\xff\xd8\xff",),
        "gif": (b"GIF87a", b"GIF89a"),
        "pdf": (b"%PDF-",),
        "webp": (b"RIFF",),
        "zip": (b"PK\x03\x04", b"PK\x05\x06", b"PK\x07\x08"),
        "docx": (b"PK\x03\x04",), "xlsx": (b"PK\x03\x04",),
        "pptx": (b"PK\x03\x04",),
    }
    if extension in signatures and not any(head.startswith(sig) for sig in signatures[extension]):
        raise ValueError("파일 내용과 확장자가 일치하지 않습니다.")
    if extension == "webp" and (len(head) < 12 or head[8:12] != b"WEBP"):
        raise ValueError("올바른 WebP 파일이 아닙니다.")
    if extension in {"csv", "txt"} and b"\x00" in head:
        raise ValueError("텍스트 파일에 실행 가능한 바이너리 내용이 포함되어 있습니다.")


def list_files():
    root = _root()
    if not root.is_dir():
        return []
    rows = []
    for path in root.iterdir():
        if not path.is_file() or path.name.startswith(".upload-"):
            continue
        stat = path.stat()
        rows.append({
            "name": path.name,
            "size": stat.st_size,
            "modified_at": stat.st_mtime,
            "content_type": mimetypes.guess_type(path.name)[0] or "application/octet-stream",
            "url": PUBLIC_BASE + quote(path.name),
        })
    return sorted(rows, key=lambda row: (-row["modified_at"], row["name"].lower()))


def save_upload(upload):
    name = _normalized_name(upload.filename)
    extension = Path(name).suffix.lower().lstrip(".")
    root = _root()
    root.mkdir(parents=True, exist_ok=True)
    candidate = root / name
    stem, suffix = candidate.stem, candidate.suffix
    counter = 2
    while candidate.exists():
        candidate = root / f"{stem}-{counter}{suffix}"
        counter += 1
    temp = root / f".upload-{secrets.token_hex(16)}.tmp"
    total = 0
    head = b""
    try:
        with temp.open("xb") as output:
            while True:
                chunk = upload.stream.read(64 * 1024)
                if not chunk:
                    break
                if len(head) < 512:
                    head += chunk[: 512 - len(head)]
                total += len(chunk)
                if total > config.PORTFOLIO_SHAREPOINT_MAX_BYTES:
                    raise ValueError("파일은 최대 20MB까지 업로드할 수 있습니다.")
                output.write(chunk)
        if total == 0:
            raise ValueError("빈 파일은 업로드할 수 없습니다.")
        _validate_signature(extension, head)
        os.replace(temp, candidate)
        try:
            candidate.chmod(0o644)
        except OSError:
            pass
    except Exception:
        temp.unlink(missing_ok=True)
        raise
    return next(row for row in list_files() if row["name"] == candidate.name)


def delete_file(raw_name):
    name = _normalized_name(raw_name)
    root = _root()
    target = (root / name).resolve()
    if target.parent != root or not target.is_file():
        raise FileNotFoundError(name)
    target.unlink()
