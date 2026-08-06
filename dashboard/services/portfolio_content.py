"""Native CASINO IN administration for the shingoon.me portfolio content.

The portfolio and CASINO IN applications run under the same PythonAnywhere
account.  This module edits only the portfolio's established JSON/image files;
it does not import the other Flask app or share its session cookies.
"""

from __future__ import annotations

import json
import os
import re
import secrets
from pathlib import Path
from urllib.parse import urlsplit

import config


MAX_TITLE = 150
MAX_TEXT = 5_000
MAX_LIST_ITEMS = 100
ALLOWED_IMAGE_EXTENSIONS = {"png", "jpg", "jpeg", "webp"}
_ID_RE = re.compile(r"^[a-zA-Z0-9_-]{1,80}$")


def _root() -> Path:
    return Path(config.PORTFOLIO_APP_DIR).resolve()


def _path(relative: str) -> Path:
    root = _root()
    target = (root / relative).resolve()
    if target != root and root not in target.parents:
        raise ValueError("허용되지 않은 포트폴리오 경로입니다.")
    return target


def _load_json(relative: str, default):
    path = _path(relative)
    if not path.is_file():
        return default.copy() if isinstance(default, dict) else list(default)
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"포트폴리오 데이터 파일을 읽을 수 없습니다: {path.name}") from exc
    if not isinstance(value, type(default)):
        raise ValueError(f"포트폴리오 데이터 형식이 올바르지 않습니다: {path.name}")
    return value


def _save_json(relative: str, value) -> None:
    path = _path(relative)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(f".{path.name}.{secrets.token_hex(8)}.tmp")
    try:
        temp.write_text(
            json.dumps(value, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        os.replace(temp, path)
    finally:
        temp.unlink(missing_ok=True)


def _text(value, label: str, *, required=False, maximum=MAX_TEXT) -> str:
    result = str(value or "").strip()
    if required and not result:
        raise ValueError(f"{label}은(는) 필수입니다.")
    if len(result) > maximum:
        raise ValueError(f"{label}은(는) {maximum:,}자 이하로 입력해주세요.")
    return result


def _lines(value, label: str) -> list[str]:
    rows = [_text(row, label) for row in str(value or "").splitlines() if str(row).strip()]
    if len(rows) > MAX_LIST_ITEMS:
        raise ValueError(f"{label}은(는) 최대 {MAX_LIST_ITEMS}개까지 입력할 수 있습니다.")
    return rows


def _record_id(raw: str) -> str:
    value = str(raw or "").strip()
    if value and not _ID_RE.fullmatch(value):
        raise ValueError("유효하지 않은 항목 ID입니다.")
    return value


def _url(value, label: str, *, required=False) -> str:
    result = _text(value, label, required=required, maximum=500)
    if result and urlsplit(result).scheme not in {"http", "https"}:
        raise ValueError(f"{label}은(는) http:// 또는 https:// 주소여야 합니다.")
    return result


def _image_signature(extension: str, head: bytes) -> bool:
    if extension == "png":
        return head.startswith(b"\x89PNG\r\n\x1a\n")
    if extension in {"jpg", "jpeg"}:
        return head.startswith(b"\xff\xd8\xff")
    if extension == "webp":
        return len(head) >= 12 and head.startswith(b"RIFF") and head[8:12] == b"WEBP"
    return False


def _save_image(upload, relative_directory: str) -> str:
    filename = str(getattr(upload, "filename", "") or "")
    extension = Path(filename).suffix.lower().lstrip(".")
    if extension not in ALLOWED_IMAGE_EXTENSIONS:
        raise ValueError("PNG, JPG, JPEG, WebP 이미지만 업로드할 수 있습니다.")
    data = upload.stream.read(config.PORTFOLIO_IMAGE_MAX_BYTES + 1)
    if not data:
        raise ValueError("빈 이미지 파일은 업로드할 수 없습니다.")
    if len(data) > config.PORTFOLIO_IMAGE_MAX_BYTES:
        raise ValueError("이미지는 최대 2MB까지 업로드할 수 있습니다.")
    if not _image_signature(extension, data[:32]):
        raise ValueError("파일 내용과 이미지 확장자가 일치하지 않습니다.")
    directory = _path(relative_directory)
    directory.mkdir(parents=True, exist_ok=True)
    stored_name = f"{secrets.token_hex(12)}.{extension}"
    destination = directory / stored_name
    temp = directory / f".{stored_name}.tmp"
    try:
        temp.write_bytes(data)
        os.replace(temp, destination)
        try:
            destination.chmod(0o644)
        except OSError:
            pass
    finally:
        temp.unlink(missing_ok=True)
    return stored_name


def _delete_image(relative_directory: str, reference: str) -> None:
    filename = Path(str(reference or "").replace("\\", "/")).name
    if not filename or filename.startswith("."):
        return
    directory = _path(relative_directory)
    target = (directory / filename).resolve()
    if target.parent == directory and target.is_file():
        target.unlink()


def snapshot() -> dict:
    return {
        "projects": _load_json("static/data/projects.json", []),
        "about": _load_json("private_data/about.json", {}),
        "contact": _load_json("private_data/contact.json", {}),
        "logos": _load_json("private_data/logos.json", []),
        "skills": _load_json("static/data/skills.json", []),
    }


def save_project(values) -> dict:
    projects = _load_json("static/data/projects.json", [])
    project_id = _record_id(values.get("id")) or secrets.token_hex(6)
    record = {
        "id": project_id,
        "title": _text(values.get("title"), "제목", required=True, maximum=MAX_TITLE),
        "date": _text(values.get("date"), "날짜", maximum=50),
        "summary": _text(values.get("summary"), "요약", required=True),
        "period": _text(values.get("period"), "기간", maximum=100),
        "content": _text(values.get("content"), "내용"),
        "outcome": _text(values.get("outcome"), "성과"),
    }
    existing = next((item for item in projects if str(item.get("id")) == project_id), None)
    if existing is None:
        projects.append(record)
    else:
        existing.update(record)
    _save_json("static/data/projects.json", projects)
    return record


def delete_project(project_id: str) -> None:
    project_id = _record_id(project_id)
    projects = _load_json("static/data/projects.json", [])
    remaining = [item for item in projects if str(item.get("id")) != project_id]
    if len(remaining) == len(projects):
        raise FileNotFoundError(project_id)
    _save_json("static/data/projects.json", remaining)


def save_about(values) -> dict:
    current = _load_json("private_data/about.json", {})
    current.update({
        "name": _text(values.get("name"), "이름", required=True, maximum=MAX_TITLE),
        "subtitle": _text(values.get("subtitle"), "소개 문구", required=True, maximum=MAX_TITLE),
        "bioIntro": _text(values.get("bioIntro"), "소개 본문"),
        "education": _lines(values.get("education"), "학력"),
        "experience": _lines(values.get("experience"), "경력"),
        "competencies": _lines(values.get("competencies"), "핵심 역량"),
        "philosophy": _lines(values.get("philosophy"), "업무 철학"),
    })
    _save_json("private_data/about.json", current)
    return current


def save_about_photo(upload) -> str:
    current = _load_json("private_data/about.json", {})
    old = current.get("photo", "")
    filename = _save_image(upload, "private_data")
    current["photo"] = filename
    try:
        _save_json("private_data/about.json", current)
    except Exception:
        _delete_image("private_data", filename)
        raise
    _delete_image("private_data", old)
    return filename


def save_contact(values) -> dict:
    record = {
        "phone": _text(values.get("phone"), "전화번호", required=True, maximum=100),
        "fax": _text(values.get("fax"), "팩스", maximum=100),
        "email": _text(values.get("email"), "이메일", required=True, maximum=254),
        "website": _url(values.get("website"), "웹사이트"),
    }
    if "@" not in record["email"]:
        raise ValueError("올바른 이메일 주소를 입력해주세요.")
    _save_json("private_data/contact.json", record)
    return record


def save_logo(values, upload) -> dict:
    logos = _load_json("private_data/logos.json", [])
    logo_id = secrets.token_hex(6)
    name = _text(values.get("name"), "로고명", required=True, maximum=MAX_TITLE)
    link = _url(values.get("link"), "링크", required=True)
    filename = _save_image(upload, "private_data/logos")
    record = {
        "id": logo_id,
        "name": name,
        "link": link,
        "image": filename,
    }
    logos.append(record)
    try:
        _save_json("private_data/logos.json", logos)
    except Exception:
        _delete_image("private_data/logos", filename)
        raise
    return record


def delete_logo(logo_id: str) -> None:
    logo_id = _record_id(logo_id)
    logos = _load_json("private_data/logos.json", [])
    target = next((item for item in logos if str(item.get("id")) == logo_id), None)
    if target is None:
        raise FileNotFoundError(logo_id)
    _save_json("private_data/logos.json", [item for item in logos if str(item.get("id")) != logo_id])
    _delete_image("private_data/logos", target.get("image", ""))


def save_skill(values, upload=None) -> dict:
    skills = _load_json("static/data/skills.json", [])
    skill_id = _record_id(values.get("id")) or secrets.token_hex(6)
    try:
        percentage = int(values.get("percentage"))
    except (TypeError, ValueError) as exc:
        raise ValueError("숙련도는 0~100 사이의 숫자여야 합니다.") from exc
    if percentage < 0 or percentage > 100:
        raise ValueError("숙련도는 0~100 사이의 숫자여야 합니다.")
    name = _text(values.get("name"), "기술명", required=True, maximum=MAX_TITLE)
    description = _text(values.get("description"), "설명")
    target = next((item for item in skills if str(item.get("id")) == skill_id), None)
    old_icon = (target or {}).get("icon", "")
    icon = old_icon
    if upload and getattr(upload, "filename", ""):
        filename = _save_image(upload, "static/uploads")
        icon = f"/uploads/{filename}"
    if not icon:
        raise ValueError("기술 아이콘 이미지가 필요합니다.")
    record = {
        "id": skill_id,
        "name": name,
        "description": description,
        "percentage": percentage,
        "icon": icon,
    }
    if target is None:
        skills.append(record)
    else:
        target.update(record)
    try:
        _save_json("static/data/skills.json", skills)
    except Exception:
        if icon != old_icon:
            _delete_image("static/uploads", icon)
        raise
    if icon != old_icon:
        _delete_image("static/uploads", old_icon)
    return record


def delete_skill(skill_id: str) -> None:
    skill_id = _record_id(skill_id)
    skills = _load_json("static/data/skills.json", [])
    target = next((item for item in skills if str(item.get("id")) == skill_id), None)
    if target is None:
        raise FileNotFoundError(skill_id)
    _save_json("static/data/skills.json", [item for item in skills if str(item.get("id")) != skill_id])
    _delete_image("static/uploads", target.get("icon", ""))
