"""Database-backed tips board content and portfolio JSON migration helpers."""

import json
import re
import secrets
from dataclasses import dataclass
from datetime import date, datetime

import bleach
import markdown

from utils import now_kst


CATEGORIES = (
    "Excel", "VBA", "Python", "AI 활용", "업무 자동화", "보고서·PPT",
    "경영기획", "데이터 분석", "PC·시스템", "기타",
)
ALLOWED_TAGS = set(bleach.sanitizer.ALLOWED_TAGS).union({
    "p", "br", "hr", "h1", "h2", "h3", "h4", "h5", "h6", "pre", "code",
    "blockquote", "ul", "ol", "li", "table", "thead", "tbody", "tr", "th",
    "td", "img", "div", "span",
})
ALLOWED_ATTRIBUTES = {
    "a": ["href", "title", "rel"],
    "img": ["src", "alt", "title", "width", "height"],
    "code": ["class"],
    "div": ["class"],
    "span": ["class"],
    "th": ["align"],
    "td": ["align"],
}


@dataclass
class RenderedTip:
    record: dict
    html: str


def render_markdown(source):
    raw = markdown.markdown(
        source or "",
        extensions=["extra", "sane_lists", "toc", "codehilite"],
        extension_configs={"codehilite": {"css_class": "codehilite", "guess_lang": False}},
    )
    clean = bleach.clean(
        raw, tags=ALLOWED_TAGS, attributes=ALLOWED_ATTRIBUTES,
        protocols={"http", "https", "mailto"}, strip=True,
    )
    return bleach.linkify(clean)


def _row(row):
    if not row:
        return None
    item = dict(row)
    try:
        item["tags"] = json.loads(item.pop("tags_json") or "[]")
    except (TypeError, json.JSONDecodeError):
        item["tags"] = []
    item["featured"] = bool(item["featured"])
    item["draft"] = bool(item["draft"])
    item["is_deleted"] = bool(item["is_deleted"])
    return item


def list_tips(connection, query="", category="", include_drafts=False,
              include_deleted=False):
    clauses, params = [], []
    if not include_deleted:
        clauses.append("is_deleted=0")
    if not include_drafts:
        clauses.append("draft=0")
    if category:
        clauses.append("category=?")
        params.append(category)
    if query:
        like = f"%{query.strip()}%"
        clauses.append("(title LIKE ? OR summary LIKE ? OR body LIKE ? OR tags_json LIKE ?)")
        params.extend([like] * 4)
    where = " AND ".join(clauses) or "1=1"
    rows = connection.execute(
        f"""SELECT * FROM tips_articles WHERE {where}
            ORDER BY featured DESC, published_date DESC, created_at DESC""",
        params,
    ).fetchall()
    return [_row(row) for row in rows]


def get_tip(connection, slug, include_drafts=False, include_deleted=False):
    clauses, params = ["slug=?"], [slug]
    if not include_deleted:
        clauses.append("is_deleted=0")
    if not include_drafts:
        clauses.append("draft=0")
    row = connection.execute(
        f"SELECT * FROM tips_articles WHERE {' AND '.join(clauses)}", params
    ).fetchone()
    return _row(row)


def get_tip_by_id(connection, tip_id):
    return _row(connection.execute(
        "SELECT * FROM tips_articles WHERE id=?", (tip_id,)
    ).fetchone())


def attachments(connection, tip_id, include_deleted=False):
    sql = "SELECT * FROM tips_attachments WHERE tip_id=?"
    if not include_deleted:
        sql += " AND is_deleted=0"
    return [dict(row) for row in connection.execute(
        sql + " ORDER BY created_at", (tip_id,)
    ).fetchall()]


def comments(connection, tip_id):
    return [
        dict(row) for row in connection.execute(
            """SELECT c.*, u.username AS author_name
               FROM tips_comments c
               JOIN dashboard_users u ON u.id=c.author_id
               WHERE c.tip_id=? AND c.is_deleted=0
               ORDER BY c.created_at ASC, c.id ASC""",
            (tip_id,),
        ).fetchall()
    ]


def get_comment(connection, comment_id):
    row = connection.execute(
        """SELECT c.*, u.username AS author_name
           FROM tips_comments c
           JOIN dashboard_users u ON u.id=c.author_id
           WHERE c.id=?""",
        (comment_id,),
    ).fetchone()
    return dict(row) if row else None


def add_comment(connection, tip_id, author_id, content):
    content = (content or "").strip()
    if not content:
        raise ValueError("댓글 내용을 입력해주세요.")
    if len(content) > 1000:
        raise ValueError("댓글은 1,000자 이하로 입력해주세요.")
    recent = connection.execute(
        """SELECT created_at FROM tips_comments
           WHERE author_id=? ORDER BY id DESC LIMIT 1""",
        (author_id,),
    ).fetchone()
    if recent:
        try:
            elapsed = now_kst() - datetime.fromisoformat(recent["created_at"])
        except (TypeError, ValueError):
            # 과거 형식의 시간이 있더라도 댓글 작성을 막지 않는다.
            elapsed = None
        if elapsed is not None and elapsed.total_seconds() < 5:
            raise ValueError("댓글은 5초 후 다시 등록할 수 있습니다.")
    now = now_kst().isoformat(timespec="seconds")
    cursor = connection.execute(
        """INSERT INTO tips_comments
           (tip_id, author_id, content, is_deleted, created_at, updated_at)
           VALUES (?, ?, ?, 0, ?, ?)""",
        (tip_id, author_id, content, now, now),
    )
    connection.commit()
    return cursor.lastrowid


def update_comment(connection, comment_id, content):
    content = (content or "").strip()
    if not content:
        raise ValueError("댓글 내용을 입력해주세요.")
    if len(content) > 1000:
        raise ValueError("댓글은 1,000자 이하로 입력해주세요.")
    connection.execute(
        """UPDATE tips_comments SET content=?, updated_at=?
           WHERE id=? AND is_deleted=0""",
        (content, now_kst().isoformat(timespec="seconds"), comment_id),
    )
    connection.commit()


def delete_comment(connection, comment_id, user_id):
    now = now_kst().isoformat(timespec="seconds")
    connection.execute(
        """UPDATE tips_comments SET is_deleted=1, deleted_at=?, deleted_by=?,
           updated_at=? WHERE id=? AND is_deleted=0""",
        (now, user_id, now, comment_id),
    )
    connection.commit()


def adjacent_tips(connection, tip):
    rows = list_tips(connection)
    ids = [item["id"] for item in rows]
    try:
        index = ids.index(tip["id"])
    except ValueError:
        return None, None
    previous = rows[index - 1] if index > 0 else None
    following = rows[index + 1] if index + 1 < len(rows) else None
    return previous, following


def increment_view(connection, tip_id):
    connection.execute(
        "UPDATE tips_articles SET view_count=view_count+1 WHERE id=?", (tip_id,)
    )
    connection.commit()


def make_slug(title, preferred=""):
    base = (preferred or "").strip().lower()
    if not base:
        base = re.sub(r"[^a-z0-9가-힣]+", "-", (title or "").lower()).strip("-")
    return base[:120] or f"tip-{secrets.token_hex(4)}"


def unique_slug(connection, title, preferred="", excluding_id=None):
    base = make_slug(title, preferred)
    candidate, number = base, 2
    while connection.execute(
        "SELECT 1 FROM tips_articles WHERE slug=? AND id<>?",
        (candidate, excluding_id or ""),
    ).fetchone():
        candidate = f"{base}-{number}"
        number += 1
    return candidate


def save_tip(connection, values, author_id, tip_id=None):
    now = now_kst().isoformat(timespec="seconds")
    title = (values.get("title") or "").strip()
    body = (values.get("body") or "").strip()
    if not title or not body:
        raise ValueError("제목과 본문은 필수입니다.")
    # 기존 포트폴리오에는 "AI"처럼 새 권장 목록에 없는 분류도 있다.
    # 이관 시 원본 값을 보존하고, 새 글에서 비어 있을 때만 기타를 사용한다.
    category = (values.get("category") or "기타").strip() or "기타"
    tags = values.get("tags", [])
    if isinstance(tags, str):
        tags = [tag.strip() for tag in tags.split(",") if tag.strip()]
    tags_json = json.dumps(tags[:20], ensure_ascii=False)
    published = (values.get("published_date") or date.today().isoformat()).strip()
    featured = 1 if values.get("featured") else 0
    draft = 1 if values.get("draft") else 0

    if tip_id:
        current = get_tip_by_id(connection, tip_id)
        if not current:
            raise ValueError("수정할 자료를 찾을 수 없습니다.")
        slug = unique_slug(
            connection, title, values.get("slug") or current["slug"], tip_id
        )
        connection.execute(
            """UPDATE tips_articles SET slug=?, title=?, summary=?, body=?,
               category=?, tags_json=?, published_date=?, updated_date=?,
               reading_time=?, featured=?, draft=?, cover_image=?, updated_at=?
               WHERE id=?""",
            (slug, title, (values.get("summary") or "").strip(), body, category,
             tags_json, published, date.today().isoformat(),
             (values.get("reading_time") or "").strip(), featured, draft,
             (values.get("cover_image") or "").strip(), now, tip_id),
        )
    else:
        tip_id = values.get("id") or secrets.token_hex(6)
        slug = unique_slug(connection, title, values.get("slug", ""))
        connection.execute(
            """INSERT INTO tips_articles
               (id, slug, title, summary, body, category, tags_json,
                published_date, updated_date, reading_time, featured, draft,
                cover_image, author_id, view_count, is_deleted, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, ?, ?)""",
            (tip_id, slug, title, (values.get("summary") or "").strip(), body,
             category, tags_json, published,
             (values.get("updated_date") or published), values.get("reading_time", ""),
             featured, draft, values.get("cover_image", ""), author_id,
             int(values.get("view_count") or 0), now, now),
        )
    connection.commit()
    return get_tip_by_id(connection, tip_id)


def soft_delete(connection, tip_id, user_id):
    connection.execute(
        """UPDATE tips_articles SET is_deleted=1, deleted_at=?, deleted_by=?,
           updated_at=? WHERE id=?""",
        (now_kst().isoformat(timespec="seconds"), user_id,
         now_kst().isoformat(timespec="seconds"), tip_id),
    )
    connection.commit()


def restore(connection, tip_id):
    connection.execute(
        """UPDATE tips_articles SET is_deleted=0, deleted_at=NULL, deleted_by=NULL,
           updated_at=? WHERE id=?""",
        (now_kst().isoformat(timespec="seconds"), tip_id),
    )
    connection.commit()


def import_portfolio_records(connection, records, author_id=None):
    inserted = skipped = 0
    for raw in records:
        if connection.execute(
            "SELECT 1 FROM tips_articles WHERE id=? OR slug=?",
            (str(raw.get("id", "")), raw.get("slug", "")),
        ).fetchone():
            skipped += 1
            continue
        save_tip(connection, {
            "id": str(raw.get("id") or secrets.token_hex(6)),
            "slug": raw.get("slug", ""),
            "title": raw.get("title", ""),
            "summary": raw.get("summary", ""),
            "body": raw.get("body", ""),
            "category": raw.get("category", "기타"),
            "tags": raw.get("tags", []),
            "published_date": raw.get("date", date.today().isoformat()),
            "updated_date": raw.get("updated") or raw.get("date") or date.today().isoformat(),
            "reading_time": raw.get("readingTime", ""),
            "featured": raw.get("featured", False),
            "draft": raw.get("draft", False),
            "cover_image": raw.get("coverImage", ""),
        }, author_id)
        inserted += 1
    return inserted, skipped
