"""Membership grades, board access thresholds, and safe badge icons."""

from __future__ import annotations

import hashlib
import re
from pathlib import Path
from xml.etree import ElementTree

from utils import now_kst


GRADE_CODES = ("silver", "gold", "platinum", "diamond", "black")
BOARD_KEYS = ("community", "notice", "bug_reports")
MAX_ICON_BYTES = 512 * 1024
STATIC_DIR = Path(__file__).resolve().parent.parent / "static"
UPLOAD_DIR = STATIC_DIR / "uploads" / "membership"


def list_grades(connection):
    return [
        dict(row) for row in connection.execute(
            "SELECT * FROM membership_grades ORDER BY rank_order"
        ).fetchall()
    ]


def grade_map(connection):
    return {row["code"]: row for row in list_grades(connection)}


def list_board_permissions(connection):
    return [
        dict(row) for row in connection.execute(
            "SELECT * FROM board_grade_permissions ORDER BY rowid"
        ).fetchall()
    ]


def user_grade(connection, user_id=None, role=None):
    grades = grade_map(connection)
    if role == "admin":
        return grades["black"]
    if not user_id:
        return grades["silver"]
    row = connection.execute(
        "SELECT membership_level, role FROM dashboard_users WHERE id=?",
        (int(user_id),),
    ).fetchone()
    if not row:
        return grades["silver"]
    code = "black" if row["role"] == "admin" else row["membership_level"]
    return grades.get(code) or grades["gold"]


def can_board(connection, board_key, action, user_id=None, role=None):
    if role == "admin":
        return True
    if board_key not in BOARD_KEYS or action not in {"read", "write", "comment"}:
        return False
    permission = connection.execute(
        "SELECT * FROM board_grade_permissions WHERE board_key=?", (board_key,)
    ).fetchone()
    if not permission:
        return False
    grades = grade_map(connection)
    current = user_grade(connection, user_id, role)
    required = grades.get(permission[f"{action}_grade"])
    return bool(required and current["rank_order"] >= required["rank_order"])


def update_user_grade(connection, user_id, grade_code, actor_id):
    if grade_code not in GRADE_CODES:
        raise ValueError("올바른 회원등급을 선택해주세요.")
    target = connection.execute(
        "SELECT id, role FROM dashboard_users WHERE id=?", (int(user_id),)
    ).fetchone()
    if not target:
        raise ValueError("회원을 찾을 수 없습니다.")
    if target["role"] == "admin" and grade_code != "black":
        raise ValueError("관리자 계정의 회원등급은 Black으로 유지됩니다.")
    if target["role"] != "admin" and grade_code == "black":
        raise ValueError("Black 등급은 관리자 역할 계정에만 지정할 수 있습니다.")
    connection.execute(
        "UPDATE dashboard_users SET membership_level=?, updated_at=? WHERE id=?",
        (grade_code, now_kst().isoformat(), int(user_id)),
    )


def update_board_permission(
    connection, board_key, read_grade, write_grade, comment_grade, actor_id
):
    if board_key not in BOARD_KEYS:
        raise ValueError("올바른 게시판을 선택해주세요.")
    levels = (read_grade, write_grade, comment_grade)
    if any(level not in GRADE_CODES for level in levels):
        raise ValueError("올바른 등급을 선택해주세요.")
    ranks = {row["code"]: row["rank_order"] for row in list_grades(connection)}
    if ranks[write_grade] < ranks[read_grade] or ranks[comment_grade] < ranks[read_grade]:
        raise ValueError("글쓰기·댓글 등급은 읽기 등급보다 낮을 수 없습니다.")
    connection.execute(
        """
        UPDATE board_grade_permissions
        SET read_grade=?, write_grade=?, comment_grade=?, updated_at=?, updated_by=?
        WHERE board_key=?
        """,
        (
            read_grade, write_grade, comment_grade,
            now_kst().isoformat(), actor_id, board_key,
        ),
    )


def update_grade_text(connection, grade_code, label, description, actor_id):
    if grade_code not in GRADE_CODES:
        raise ValueError("올바른 회원등급을 선택해주세요.")
    label = (label or "").strip()
    description = (description or "").strip()
    if not label or len(label) > 30 or not description or len(description) > 100:
        raise ValueError("등급명은 1~30자, 설명은 1~100자로 입력해주세요.")
    connection.execute(
        """
        UPDATE membership_grades
        SET label=?, description=?, updated_at=?, updated_by=? WHERE code=?
        """,
        (label, description, now_kst().isoformat(), actor_id, grade_code),
    )


def _validate_svg(data):
    text = data.decode("utf-8")
    lowered = text.casefold()
    if "<!doctype" in lowered or "<!entity" in lowered:
        raise ValueError("DOCTYPE 또는 ENTITY가 포함된 SVG는 사용할 수 없습니다.")
    try:
        root = ElementTree.fromstring(text)
    except (ElementTree.ParseError, UnicodeDecodeError) as error:
        raise ValueError("올바른 SVG 파일이 아닙니다.") from error
    if root.tag.rsplit("}", 1)[-1].casefold() != "svg":
        raise ValueError("SVG 루트 요소를 확인해주세요.")
    blocked_tags = {"script", "foreignobject", "iframe", "object", "embed"}
    for element in root.iter():
        if element.tag.rsplit("}", 1)[-1].casefold() in blocked_tags:
            raise ValueError("실행 가능한 요소가 포함된 SVG는 사용할 수 없습니다.")
        for name, value in element.attrib.items():
            local_name = name.rsplit("}", 1)[-1].casefold()
            if local_name.startswith("on") or re.search(
                r"(?:javascript|https?|data):", str(value), flags=re.I
            ):
                raise ValueError("외부 참조 또는 실행 속성이 포함된 SVG는 사용할 수 없습니다.")


def save_grade_icon(connection, grade_code, uploaded, actor_id):
    if grade_code not in GRADE_CODES or not uploaded or not uploaded.filename:
        raise ValueError("업로드할 등급 아이콘을 선택해주세요.")
    suffix = Path(uploaded.filename).suffix.casefold()
    data = uploaded.stream.read(MAX_ICON_BYTES + 1)
    if len(data) > MAX_ICON_BYTES:
        raise ValueError("등급 아이콘은 512KB 이하만 업로드할 수 있습니다.")
    if suffix == ".png":
        if not data.startswith(b"\x89PNG\r\n\x1a\n"):
            raise ValueError("올바른 PNG 파일이 아닙니다.")
    elif suffix == ".svg":
        _validate_svg(data)
    else:
        raise ValueError("등급 아이콘은 SVG 또는 PNG만 사용할 수 있습니다.")
    digest = hashlib.sha256(data).hexdigest()[:16]
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    filename = f"{grade_code}-{digest}{suffix}"
    destination = UPLOAD_DIR / filename
    if not destination.exists():
        destination.write_bytes(data)
    icon_path = f"uploads/membership/{filename}"
    connection.execute(
        """
        UPDATE membership_grades
        SET icon_path=?, updated_at=?, updated_by=? WHERE code=?
        """,
        (icon_path, now_kst().isoformat(), actor_id, grade_code),
    )
    return icon_path


def reset_grade_icon(connection, grade_code, actor_id):
    if grade_code not in GRADE_CODES:
        raise ValueError("올바른 회원등급을 선택해주세요.")
    connection.execute(
        """
        UPDATE membership_grades
        SET icon_path=?, updated_at=?, updated_by=? WHERE code=?
        """,
        (
            f"img/membership/{grade_code}.svg",
            now_kst().isoformat(), actor_id, grade_code,
        ),
    )
