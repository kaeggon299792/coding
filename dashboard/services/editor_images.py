"""Safe storage helpers for images pasted into Markdown editors."""

import uuid
from pathlib import Path


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
