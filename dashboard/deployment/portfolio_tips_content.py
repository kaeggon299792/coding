"""TIPS 지식 아카이브의 콘텐츠 저장/로딩/렌더링/CRUD 계층.

- 콘텐츠는 static/data/tips.json — 이 저장소의 다른 관리자 편집 데이터
  (projects.json, about.json 등)와 동일한 패턴이다. /admin에서 프로젝트처럼
  글을 추가/수정/삭제한다. 더 이상 content/tips/*.md 파일을 읽지 않는다.
- 이 모듈은 저장소 접근 + 마크다운 렌더링만 담당한다 (프레젠테이션은 templates에서).
"""

from dataclasses import dataclass, field
import json
import os
import re
import secrets
import sqlite3

import bleach
import markdown as markdown_lib

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
TIPS_FILE = os.path.join(BASE_DIR, "static", "data", "tips.json")
DASHBOARD_TIPS_DB = os.getenv(
    "DASHBOARD_TIPS_DB_FILE",
    "/home/kaekun/coding-dashboard/dashboard/dashboard.db",
)

# 대시보드 자료실에서는 요약을 선택 입력으로 받으므로 요약이 비어 있어도
# 제목·분류·작성일·본문이 있으면 정상 공개 글로 취급한다.
REQUIRED_FIELDS = ("title", "category", "date", "body")

MAX_TITLE_LENGTH = 150
MAX_SUMMARY_LENGTH = 300
MAX_TAG_LENGTH = 40
MAX_BODY_LENGTH = 20000

ALLOWED_TAGS = [
    "p", "br", "hr",
    "h2", "h3", "h4",
    "strong", "em", "del", "code", "pre", "span", "div",
    "ul", "ol", "li",
    "blockquote",
    "a", "img",
    "table", "thead", "tbody", "tr", "th", "td",
    "input",
]

ALLOWED_ATTRS = {
    "a": ["href", "title", "rel", "target"],
    "img": ["src", "alt", "title", "loading"],
    "span": ["class"],
    "div": ["class"],
    "pre": ["class"],
    "code": ["class"],
    "th": ["align"],
    "td": ["align"],
    "input": ["type", "checked", "disabled"],
    "h2": ["id"],
    "h3": ["id"],
    "h4": ["id"],
}

ALLOWED_PROTOCOLS = ["http", "https", "mailto"]


@dataclass
class Article:
    id: str
    slug: str
    title: str
    summary: str
    category: str
    tags: list
    date: str
    updated: str
    reading_time: str
    featured: bool
    draft: bool
    cover_image: str
    body_markdown: str = field(repr=False)
    html: str = field(default="", repr=False)
    toc: list = field(default_factory=list)

    @property
    def seo_title(self):
        return self.title

    @property
    def seo_description(self):
        return self.summary


def _slugify_unicode(value, separator="-"):
    # markdown 라이브러리의 기본 slugify는 ASCII만 남겨 한글 제목이 전부 사라진다.
    # 한글을 그대로 유지하는 slugify를 직접 만들어 의미 있는 슬러그/앵커를 만든다.
    value = re.sub(r"[^\w\s-]", "", str(value), flags=re.UNICODE).strip().lower()
    return re.sub(r"[\s]+", separator, value)


def _estimate_reading_time(text):
    # 한글은 글자 수, 영문은 단어 수 기준으로 대략적인 분당 처리량을 가정해 추정한다.
    korean_chars = len(re.findall(r"[가-힣]", text))
    other_words = len(re.findall(r"[A-Za-z0-9]+", text))
    minutes = (korean_chars / 350) + (other_words / 200)
    return f"{max(1, round(minutes))} min"


def _render_markdown(body_markdown):
    md = markdown_lib.Markdown(
        extensions=["fenced_code", "tables", "sane_lists", "toc", "codehilite", "nl2br"],
        extension_configs={
            "toc": {"permalink": False, "slugify": _slugify_unicode},
            "codehilite": {"guess_lang": False, "css_class": "codehilite"},
        },
    )
    raw_html = md.convert(body_markdown)
    toc_tokens = getattr(md, "toc_tokens", [])

    safe_html = bleach.clean(
        raw_html,
        tags=ALLOWED_TAGS,
        attributes=ALLOWED_ATTRS,
        protocols=ALLOWED_PROTOCOLS,
        strip=True,
    )
    return safe_html, toc_tokens


def _load_raw():
    """대시보드 DB를 단일 원본으로 읽고, 전환 전에는 JSON으로 안전하게 폴백한다."""
    if os.path.isfile(DASHBOARD_TIPS_DB):
        try:
            connection = sqlite3.connect(DASHBOARD_TIPS_DB)
            connection.row_factory = sqlite3.Row
            rows = connection.execute(
                """SELECT id, slug, title, summary, category, tags_json,
                          published_date, updated_date, reading_time, featured,
                          draft, cover_image, body
                   FROM tips_articles
                   WHERE is_deleted=0
                   ORDER BY featured DESC, published_date DESC"""
            ).fetchall()
            connection.close()
            return [
                {
                    "id": row["id"], "slug": row["slug"], "title": row["title"],
                    "summary": row["summary"], "category": row["category"],
                    "tags": json.loads(row["tags_json"] or "[]"),
                    "date": row["published_date"], "updated": row["updated_date"],
                    "readingTime": row["reading_time"] or "",
                    "featured": bool(row["featured"]), "draft": bool(row["draft"]),
                    "coverImage": row["cover_image"] or "", "body": row["body"],
                }
                for row in rows
            ]
        except (sqlite3.Error, json.JSONDecodeError):
            # 배포 중 DB 스키마가 아직 준비되지 않은 짧은 구간에는 기존 JSON을 제공한다.
            pass
    if not os.path.isfile(TIPS_FILE):
        return []
    with open(TIPS_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def _save_raw(records):
    """기존 포트폴리오 관리자 API도 같은 DB에 쓰도록 호환성을 유지한다."""
    connection = sqlite3.connect(DASHBOARD_TIPS_DB)
    now = __import__("datetime").datetime.now().isoformat(timespec="seconds")
    incoming_ids = {str(record.get("id")) for record in records}
    for record in records:
        connection.execute(
            """INSERT INTO tips_articles
               (id, slug, title, summary, body, category, tags_json,
                published_date, updated_date, reading_time, featured, draft,
                cover_image, view_count, is_deleted, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, 0, ?, ?)
               ON CONFLICT(id) DO UPDATE SET
                 title=excluded.title, summary=excluded.summary, body=excluded.body,
                 category=excluded.category, tags_json=excluded.tags_json,
                 published_date=excluded.published_date,
                 updated_date=excluded.updated_date,
                 reading_time=excluded.reading_time, featured=excluded.featured,
                 draft=excluded.draft, cover_image=excluded.cover_image,
                 is_deleted=0, deleted_at=NULL, deleted_by=NULL,
                 updated_at=excluded.updated_at""",
            (
                str(record.get("id")), record.get("slug"), record.get("title", ""),
                record.get("summary", ""), record.get("body", ""),
                record.get("category", "기타"),
                json.dumps(record.get("tags", []), ensure_ascii=False),
                record.get("date", ""), record.get("updated") or record.get("date", ""),
                record.get("readingTime", ""), int(bool(record.get("featured"))),
                int(bool(record.get("draft"))), record.get("coverImage", ""), now, now,
            ),
        )
    existing = connection.execute(
        "SELECT id FROM tips_articles WHERE is_deleted=0"
    ).fetchall()
    for (tip_id,) in existing:
        if tip_id not in incoming_ids:
            connection.execute(
                "UPDATE tips_articles SET is_deleted=1, deleted_at=?, updated_at=? WHERE id=?",
                (now, now, tip_id),
            )
    connection.commit()
    connection.close()


def _parse_tags(raw):
    if isinstance(raw, list):
        items = raw
    else:
        items = re.split(r"[,\n]", str(raw or ""))
    return [t.strip() for t in items if t.strip()]


def _record_to_article(record):
    body = str(record.get("body", ""))
    html, toc = _render_markdown(body)

    return Article(
        id=record.get("id", ""),
        slug=record.get("slug", ""),
        title=str(record.get("title", "")).strip(),
        summary=str(record.get("summary", "")).strip(),
        category=str(record.get("category", "")).strip(),
        tags=_parse_tags(record.get("tags")),
        date=str(record.get("date", "")).strip(),
        updated=str(record.get("updated") or record.get("date", "")).strip(),
        reading_time=str(record.get("readingTime") or "").strip() or _estimate_reading_time(body),
        featured=bool(record.get("featured", False)),
        draft=bool(record.get("draft", False)),
        cover_image=str(record.get("coverImage", "")).strip(),
        body_markdown=body,
        html=html,
        toc=toc,
    )


def load_all_articles(include_drafts=False):
    """공개용 글 목록(최신순). include_drafts=True면 관리자용으로 초안도 포함."""
    records = _load_raw()
    articles = []
    for record in records:
        missing = [f for f in REQUIRED_FIELDS if not record.get(f)]
        if missing:
            continue
        if record.get("draft") and not include_drafts:
            continue
        articles.append(_record_to_article(record))

    articles.sort(key=lambda a: a.date, reverse=True)
    return articles


def get_article_by_slug(slug):
    for article in load_all_articles():
        if article.slug == slug:
            return article
    return None


def get_prev_next(slug):
    """실제 발행일 기준(오래된 -> 최신) 이전/다음 글을 반환한다."""
    chronological = sorted(load_all_articles(), key=lambda a: a.date)
    index = next((i for i, a in enumerate(chronological) if a.slug == slug), None)
    if index is None:
        return None, None

    prev_article = chronological[index - 1] if index > 0 else None
    next_article = chronological[index + 1] if index < len(chronological) - 1 else None
    return prev_article, next_article


def get_related_articles(article, limit=3):
    others = [a for a in load_all_articles() if a.slug != article.slug]

    def score(candidate):
        shared_tags = len(set(candidate.tags) & set(article.tags))
        same_category = 1 if candidate.category == article.category else 0
        return (shared_tags + same_category, candidate.date)

    others.sort(key=score, reverse=True)
    relevant = [a for a in others if score(a)[0] > 0]
    return relevant[:limit] if relevant else others[:limit]


def get_categories():
    counts = {}
    for article in load_all_articles():
        counts[article.category] = counts.get(article.category, 0) + 1
    return counts


def build_search_index():
    """검색/필터용 경량 인덱스. 본문 전체는 포함하지 않아 인덱스 페이지 payload를 작게 유지한다."""
    index = []
    for article in load_all_articles():
        index.append(
            {
                "slug": article.slug,
                "title": article.title,
                "summary": article.summary,
                "category": article.category,
                "tags": article.tags,
                "date": article.date,
                "readingTime": article.reading_time,
                "featured": article.featured,
            }
        )
    return index


def canonical_url(base_url, slug=None):
    base_url = base_url.rstrip("/")
    if slug:
        return f"{base_url}/resources/{slug}"
    return f"{base_url}/resources"


# ==================== 관리자 CRUD ====================

def _generate_unique_slug(title, existing_slugs):
    base = _slugify_unicode(title) or secrets.token_hex(4)
    slug = base
    counter = 2
    while slug in existing_slugs:
        slug = f"{base}-{counter}"
        counter += 1
    return slug


def _validate_fields(data):
    title = str(data.get("title", "")).strip()
    summary = str(data.get("summary", "")).strip()
    category = str(data.get("category", "")).strip()
    date = str(data.get("date", "")).strip()
    body = str(data.get("body", "")).strip()
    tags = _parse_tags(data.get("tags"))

    if not title or not summary or not category or not date or not body:
        return None, "제목, 요약, 카테고리, 날짜, 본문은 모두 필수입니다."

    if (
        len(title) > MAX_TITLE_LENGTH
        or len(summary) > MAX_SUMMARY_LENGTH
        or len(body) > MAX_BODY_LENGTH
        or any(len(t) > MAX_TAG_LENGTH for t in tags)
    ):
        return None, "입력값이 너무 깁니다."

    fields = {
        "title": title,
        "summary": summary,
        "category": category,
        "date": date,
        "body": body,
        "tags": tags,
        "updated": str(data.get("updated") or date).strip(),
        "readingTime": str(data.get("readingTime") or "").strip(),
        "featured": bool(data.get("featured")),
        "draft": bool(data.get("draft")),
        "coverImage": str(data.get("coverImage", "")).strip(),
    }
    return fields, None


def list_all_for_admin():
    """관리자 페이지 목록용: 초안 포함, 최신순."""
    records = sorted(_load_raw(), key=lambda r: r.get("date", ""), reverse=True)
    return records


def create_article(data):
    fields, error = _validate_fields(data)
    if error:
        return None, error

    records = _load_raw()
    existing_slugs = {r.get("slug") for r in records}

    preferred_slug = _slugify_unicode(str(data.get("slug", "")).strip())
    slug = _generate_unique_slug(preferred_slug or fields["title"], existing_slugs)

    record = {"id": secrets.token_hex(6), "slug": slug, **fields}
    records.append(record)
    _save_raw(records)
    return record, None


def update_article(article_id, data):
    fields, error = _validate_fields(data)
    if error:
        return None, error

    records = _load_raw()
    target = next((r for r in records if r.get("id") == article_id), None)
    if target is None:
        return None, "해당 글을 찾을 수 없습니다."

    # 슬러그는 최초 생성 시 한 번만 정해지고 이후 수정에서는 바뀌지 않는다
    # (이미 공유된 링크가 깨지지 않도록).
    target.update(fields)
    _save_raw(records)
    return target, None


def delete_article(article_id):
    records = _load_raw()
    remaining = [r for r in records if r.get("id") != article_id]
    if len(remaining) == len(records):
        return False
    _save_raw(remaining)
    return True
