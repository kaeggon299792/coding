"""Build the public CASINO IN RSS feed without mutating operational data."""

from datetime import datetime, timedelta, timezone
from email.utils import format_datetime
import html
import logging
import re
from xml.etree.ElementTree import Element, SubElement, tostring

from dashboard_db import queries
from services import news_reader, overseas_news


logger = logging.getLogger("dashboard")
KST = timezone(timedelta(hours=9))
MAX_ITEMS = 50


def _plain_text(value, limit=4000):
    text = html.unescape(re.sub(r"<[^>]*>", " ", str(value or "")))
    text = re.sub(r"\s+", " ", text).strip()
    if len(text) <= limit:
        return text
    return text[: limit - 1].rstrip() + "…"


def _published_datetime(value):
    if not value:
        return None
    if isinstance(value, datetime):
        parsed = value
    else:
        raw = str(value).strip()
        if not raw:
            return None
        try:
            parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        except ValueError:
            return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=KST)
    return parsed


def _feed_item(title, link, description, published_at, category):
    title = _plain_text(title, 300)
    link = str(link or "").strip()
    if not title or not link:
        return None
    description = _plain_text(description) or title
    return {
        "title": title,
        "link": link,
        "description": description,
        "published_at": _published_datetime(published_at),
        "category": category,
    }


def build_public_items(connection, public_url):
    """Return up to 50 recent items already visible without authentication."""
    base_url = public_url.rstrip("/")
    items = []

    try:
        domestic_articles = news_reader.list_articles(
            days=365, include_entertainment=False, limit=25
        )
    except Exception:
        logger.warning("RSS domestic news lookup failed", exc_info=True)
        domestic_articles = []
    for article in domestic_articles:
        article_id = article.get("article_id")
        if article_id is None:
            continue
        publisher = _plain_text(article.get("publisher"), 200)
        summary = (
            article.get("latest_summary")
            or article.get("issue_title")
            or article.get("title")
        )
        if publisher:
            summary = f"{summary} 출처: {publisher}"
        item = _feed_item(
            article.get("title"),
            f"{base_url}/news#news-{article_id}",
            summary,
            article.get("published_at") or article.get("collected_at"),
            "국내 뉴스",
        )
        if item:
            items.append(item)

    try:
        international_articles = overseas_news.list_articles(
            connection, days=365, limit=15
        )
    except Exception:
        logger.warning("RSS overseas news lookup failed", exc_info=True)
        international_articles = []
    for article in international_articles:
        article_id = article.get("id")
        if article_id is None:
            continue
        title = article.get("title_ko") or article.get("original_title")
        summary = (
            article.get("ai_analysis")
            or article.get("summary_ko")
            or article.get("original_summary")
            or title
        )
        publisher = _plain_text(article.get("publisher"), 200)
        if publisher:
            summary = f"{summary} 출처: {publisher}"
        item = _feed_item(
            title,
            f"{base_url}/news/overseas#overseas-news-{article_id}",
            summary,
            article.get("published_at") or article.get("collected_at"),
            "해외 뉴스",
        )
        if item:
            items.append(item)

    try:
        notice_rows = connection.execute(
            """
            SELECT id, title, content, created_at, updated_at
            FROM community_posts
            WHERE is_deleted=0 AND board_type='notice'
            ORDER BY COALESCE(updated_at, created_at) DESC, id DESC
            LIMIT 15
            """
        ).fetchall()
    except Exception:
        logger.warning("RSS notice lookup failed", exc_info=True)
        notice_rows = []
    for row in notice_rows:
        notice = dict(row)
        item = _feed_item(
            notice.get("title"),
            f"{base_url}/board/{notice['id']}",
            notice.get("content"),
            notice.get("updated_at") or notice.get("created_at"),
            "공지사항",
        )
        if item:
            items.append(item)

    try:
        research_documents = queries.list_research_documents(
            connection, limit=15, document_type="research"
        )
    except Exception:
        logger.warning("RSS research lookup failed", exc_info=True)
        research_documents = []
    for document in research_documents:
        document_id = document.get("id")
        if document_id is None:
            continue
        summary = (
            document.get("ai_summary")
            or document.get("extracted_text")
            or document.get("title")
        )
        publisher = _plain_text(document.get("publisher"), 200)
        if publisher:
            summary = f"{summary} 발행처: {publisher}"
        item = _feed_item(
            document.get("title"),
            f"{base_url}/companies/reports#research-{document_id}",
            summary,
            document.get("report_date") or document.get("created_at"),
            "리서치",
        )
        if item:
            items.append(item)

    minimum = datetime.min.replace(tzinfo=timezone.utc)
    items.sort(
        key=lambda item: (
            item["published_at"].astimezone(timezone.utc)
            if item["published_at"]
            else minimum
        ),
        reverse=True,
    )
    return items[:MAX_ITEMS]


def render(items, public_url):
    base_url = public_url.rstrip("/")
    rss = Element("rss", {"version": "2.0"})
    channel = SubElement(rss, "channel")
    SubElement(channel, "title").text = "CASINO IN 최신 콘텐츠"
    SubElement(channel, "link").text = f"{base_url}/"
    SubElement(channel, "description").text = (
        "카지노·관광산업 뉴스, 공지사항, 리서치 중 최신 공개 콘텐츠입니다."
    )
    SubElement(channel, "language").text = "ko-KR"
    SubElement(channel, "generator").text = "CASINO IN"
    dated_items = [item for item in items if item.get("published_at")]
    if dated_items:
        SubElement(channel, "lastBuildDate").text = format_datetime(
            max(item["published_at"] for item in dated_items)
        )
    for item in items:
        item_node = SubElement(channel, "item")
        SubElement(item_node, "title").text = item["title"]
        SubElement(item_node, "link").text = item["link"]
        SubElement(item_node, "guid", {"isPermaLink": "true"}).text = item["link"]
        SubElement(item_node, "description").text = item["description"]
        SubElement(item_node, "category").text = item["category"]
        if item.get("published_at"):
            SubElement(item_node, "pubDate").text = format_datetime(
                item["published_at"]
            )
    return tostring(rss, encoding="utf-8", xml_declaration=True)
