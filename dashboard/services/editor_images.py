"""Safe storage helpers for images pasted into protected editors."""

import os
import re
import uuid
from pathlib import Path


SAFE_FILENAME_RE = re.compile(r"\A[0-9a-f]{32}\.(?:png|jpg|gif|webp)\Z")


def image_suffix(data):
    """Return a safe extension based on file bytes, never the client filename."""
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return ".png"
    if data.startswith(b"\xff\xd8\xff"):
        return ".jpg"
    if data.startswith((b"GIF87a", b"GIF89a")):
        return ".gif"
    if data.startswith(b"RIFF") and len(data) >= 12 and data[8:12] == b"WEBP":
        return ".webp"
    return None


def save_pasted_image(uploaded, directory, max_bytes):
    """Validate a pasted image by signature and save it under a random name."""
    if not uploaded:
        raise ValueError("붙여넣을 이미지를 찾지 못했습니다.")
    data = uploaded.read(max_bytes + 1)
    if not data:
        raise ValueError("빈 이미지는 등록할 수 없습니다.")
    if len(data) > max_bytes:
        raise ValueError(f"이미지는 {max_bytes // 1048576}MB 이하만 가능합니다.")
    suffix = image_suffix(data)
    if not suffix:
        raise ValueError("PNG, JPG, GIF, WebP 이미지만 붙여넣을 수 있습니다.")
    root = Path(directory)
    root.mkdir(parents=True, exist_ok=True)
    filename = f"{uuid.uuid4().hex}{suffix}"
    (root / filename).write_bytes(data)
    return filename


def safe_image_path(directory, filename):
    """Resolve only application-generated image names inside ``directory``."""
    value = str(filename or "")
    if not SAFE_FILENAME_RE.fullmatch(value):
        raise ValueError("Invalid editor image name")
    root = Path(directory).resolve()
    candidate = (root / value).resolve()
    if candidate.parent != root:
        raise ValueError("Invalid editor image path")
    return candidate


def migrate_legacy_image(filename, legacy_directory, protected_directory):
    """Move one legacy static image into protected storage, race-safely."""
    target = safe_image_path(protected_directory, filename)
    if target.is_file():
        return target
    source = safe_image_path(legacy_directory, filename)
    if not source.is_file():
        return target
    target.parent.mkdir(parents=True, exist_ok=True)
    try:
        os.replace(source, target)
    except FileNotFoundError:
        # Another WSGI worker may have completed the same lazy migration.
        pass
    return target


def migrate_legacy_directory(legacy_directory, protected_directory):
    """Move all generated legacy images out of the public static tree."""
    legacy = Path(legacy_directory).resolve()
    protected = Path(protected_directory).resolve()
    if legacy == protected or not legacy.is_dir():
        return 0
    migrated = 0
    for source in legacy.iterdir():
        if not source.is_file() or not SAFE_FILENAME_RE.fullmatch(source.name):
            continue
        target = protected / source.name
        protected.mkdir(parents=True, exist_ok=True)
        try:
            os.replace(source, target)
            migrated += 1
        except FileNotFoundError:
            pass
    return migrated
