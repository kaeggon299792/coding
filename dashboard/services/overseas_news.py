"""Collect and serve Macau/Japan casino news with grounded Korean analysis."""

from __future__ import annotations

import hashlib
import html
import json
import logging
import re
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from urllib.parse import quote_plus
import config
from defusedxml import ElementTree
from services import ai_insights, ai_runtime_settings
from services.http_utils import get_with_hard_timeout

logger = logging.getLogger("dashboard")

GOOGLE_NEWS_RSS = "https://news.google.com/rss/search"
FEEDS = (
    {
        "region": "macau",
        "label": "마카오",
        "query": 'Macau (casino OR gaming OR "integrated resort") when:14d',
        "locale": "hl=en-HK&gl=HK&ceid=HK:en",
    },
    {
        "region": "macau",
        "label": "마카오",
        "query": "澳門 (博彩 OR 賭場 OR 綜合度假村) when:14d",
        "locale": "hl=zh-TW&gl=HK&ceid=HK:zh-Hant",
    },
    {
        "region": "japan",
        "label": "일본",
        "query": 'Japan (casino OR "integrated resort" OR "Osaka IR") when:14d',
        "locale": "hl=en&gl=JP&ceid=JP:en",
    },
    {
        "region": "japan",
        "label": "일본",
        "query": "日本 (カジノ OR 統合型リゾート OR 大阪IR) when:14d",
        "locale": "hl=ja&gl=JP&ceid=JP:ja",
    },
)

_TAG_RE = re.compile(r"<[^>]+>")
_SPACE_RE = re.compile(r"\s+")
_TITLE_SOURCE_RE = re.compile(r"\s+-\s+[^-]{2,80}$")


def _utc_now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _clean_text(value, limit=700):
    value = html.unescape(_TAG_RE.sub(" ", value or ""))
    return _SPACE_RE.sub(" ", value).strip()[:limit]


def _parse_published(value):
    if not value:
        return None
    try:
        return parsedate_to_datetime(value).astimezone(timezone.utc).isoformat(timespec="seconds")
    except (TypeError, ValueError, OverflowError):
        return None


def _article_key(region, title, publisher):
    normalized = "|".join(
        [region.strip().lower(), _SPACE_RE.sub(" ", title).strip().lower(), (publisher or "").strip().lower()]
    )
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def _feed_url(feed):
    return f"{GOOGLE_NEWS_RSS}?q={quote_plus(feed['query'])}&{feed['locale']}"


def _fetch_feed(feed, limit=25):
    response = get_with_hard_timeout(
        _feed_url(feed),
        hard_timeout_seconds=18,
        retry_attempts=3,
        timeout=(5, 15),
        headers={
            "User-Agent": "CasinoIN/1.0 (+https://www.casinoin.kr/credits)",
            "Accept": "application/rss+xml, application/xml;q=0.9, text/xml;q=0.8",
        },
    )
    response.raise_for_status()
    root = ElementTree.fromstring(response.content)
    rows = []
    for item in root.findall("./channel/item")[: max(1, int(limit))]:
        title = _clean_text(item.findtext("title"), 350)
        link = (item.findtext("link") or "").strip()
        source_node = item.find("source")
        publisher = _clean_text(source_node.text if source_node is not None else "", 120)
        if not title or not link:
            continue
        # Google appends the publisher to many titles. Keep the exact source
        # headline when the suffix matches the explicit RSS source element.
        if publisher and title.lower().endswith(f" - {publisher}".lower()):
            title = title[: -(len(publisher) + 3)].rstrip()
        description = _clean_text(item.findtext("description"), 700)
        if description and title.lower() in description.lower():
            description = ""
        rows.append(
            {
                "article_key": _article_key(feed["region"], title, publisher),
                "region": feed["region"],
                "original_title": title,
                "original_summary": description,
                "publisher": publisher,
                "original_url": link,
                "source_feed": _feed_url(feed),
                "published_at": _parse_published(item.findtext("pubDate")),
            }
        )
    return rows


def _analysis_fingerprint(item):
    title = _SPACE_RE.sub(" ", (item.get("original_title") or "").lower()).strip()
    return re.sub(r"[^0-9a-z가-힣\u3040-\u30ff\u3400-\u9fff]+", "", title)


def _chunks(items, size):
    size = max(1, int(size))
    for index in range(0, len(items), size):
        yield items[index:index + size]


def _safe_source_citations(fields):
    citations = []
    for value in fields.get("source_urls") or []:
        value = str(value or "").strip()
        if value.startswith(("https://", "http://")):
            item = {"url": value, "title": "웹 검색 검증 출처"}
            if item not in citations:
                citations.append(item)
    return json.dumps(citations[:5], ensure_ascii=False)


def _save_analysis(connection, article_id, fields, analyzed_at, *, basis, web_verified=False):
    canonical_url = str(fields.get("canonical_url") or "").strip()
    if not canonical_url.startswith(("https://", "http://")):
        canonical_url = None
    connection.execute(
        """
        UPDATE overseas_news_articles
        SET title_ko=?, summary_ko=?, category=?, impact_direction=?,
            importance_score=?, ai_analysis=?, analyzed_at=?, translated_at=?,
            translation_status='translated', translation_error=NULL,
            canonical_url=COALESCE(?, canonical_url, original_url), analysis_basis=?,
            retrieval_status=?, source_citations_json=?, gemini_model=?,
            gemini_analyzed_at=?, analysis_error=NULL, analysis_provider='openai',
            analysis_model=?, web_verified_at=?
        WHERE id=?
        """,
        (
            str(fields.get("title_ko") or "")[:500],
            str(fields.get("summary_ko") or "")[:3000],
            fields.get("category") or "기타",
            fields.get("impact_direction") or "neutral",
            max(0, min(int(fields.get("importance_score") or 0), 100)),
            str(fields.get("ai_analysis") or "")[:5000],
            analyzed_at, analyzed_at, canonical_url, basis,
            "web_verified" if web_verified else "rss_only",
            _safe_source_citations(fields) if web_verified else "[]",
            ai_runtime_settings.get_purpose_settings(
                connection, "news_importance"
            )["model"],
            analyzed_at,
            ai_runtime_settings.get_purpose_settings(
                connection, "news_importance"
            )["model"],
            analyzed_at if web_verified else None, article_id,
        ),
    )


def _analyze_pending(connection, limit=None):
    limit = config.OPENAI_NEWS_MAX_PER_RUN if limit is None else max(1, int(limit))
    pending = [
        dict(row)
        for row in connection.execute(
            """
            SELECT id, region, publisher, original_title, original_summary, original_url,
                   title_ko, summary_ko
            FROM overseas_news_articles
            WHERE ai_analysis IS NULL OR ai_analysis=''
            ORDER BY COALESCE(published_at, collected_at) DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
    ]
    groups = {}
    for item in pending:
        groups.setdefault(_analysis_fingerprint(item) or str(item["id"]), []).append(item)
    representatives = [items[0] for items in groups.values()]
    representative_groups = {str(items[0]["id"]): items for items in groups.values()}

    analyzed_count = 0
    errors = []
    important = []
    for batch in _chunks(representatives, config.OPENAI_NEWS_BATCH_SIZE):
        translated, error = ai_insights.translate_overseas_news_batch(connection, batch)
        if not translated:
            message = str(error or "OpenAI 일괄 분석에 실패했습니다.")[:500]
            ids = [member["id"] for item in batch for member in representative_groups[str(item["id"])]]
            placeholders = ",".join("?" for _ in ids)
            connection.execute(
                f"UPDATE overseas_news_articles SET translation_status='retry', "
                f"translation_error=?, analysis_error=? WHERE id IN ({placeholders})",
                [message, message, *ids],
            )
            connection.commit()
            errors.append(message)
            continue
        analyzed_at = _utc_now()
        for item in batch:
            fields = translated.get(str(item["id"]))
            members = representative_groups[str(item["id"])]
            if not fields:
                message = f"OpenAI 일괄 응답에서 기사 {item['id']} 결과가 누락됐습니다."
                for member in members:
                    connection.execute(
                        "UPDATE overseas_news_articles SET translation_status='retry', "
                        "translation_error=?, analysis_error=? WHERE id=?",
                        (message, message, member["id"]),
                    )
                errors.append(message)
                continue
            fields["canonical_url"] = item.get("original_url")
            for index, member in enumerate(members):
                member_fields = dict(fields)
                member_fields["canonical_url"] = member.get("original_url")
                _save_analysis(
                    connection, member["id"], member_fields, analyzed_at,
                    basis="rss_batch" if index == 0 else "rss_batch_deduplicated",
                )
                analyzed_count += 1
            if int(fields.get("importance_score") or 0) >= ai_runtime_settings.web_importance_threshold(connection):
                important.append((item, fields, members))
        connection.commit()

    important.sort(key=lambda row: int(row[1].get("importance_score") or 0), reverse=True)
    for item, preliminary, members in important[:max(0, config.OPENAI_NEWS_WEB_MAX_PER_RUN)]:
        web_item = dict(item)
        web_item.update(preliminary)
        verified, error = ai_insights.analyze_important_overseas_news_with_web(connection, web_item)
        if not verified:
            message = f"중요 뉴스 웹 검증 실패: {str(error or '알 수 없는 오류')[:400]}"
            connection.execute(
                "UPDATE overseas_news_articles SET analysis_error=? WHERE id=?",
                (message, item["id"]),
            )
            errors.append(message)
            connection.commit()
            continue
        analyzed_at = _utc_now()
        for member in members:
            member_fields = dict(verified)
            if member["id"] != item["id"]:
                member_fields["canonical_url"] = member.get("original_url")
            _save_analysis(
                connection, member["id"], member_fields, analyzed_at,
                basis="web_search", web_verified=True,
            )
        connection.commit()
    return analyzed_count, list(dict.fromkeys(errors))


def analyze_article(connection, article_id, *, bypass_daily_limits=False):
    """Analyze one selected article without touching other pending articles."""
    row = connection.execute(
        """
        SELECT id, region, publisher, original_title, original_summary, original_url,
               title_ko, summary_ko
        FROM overseas_news_articles
        WHERE id=?
        """,
        (article_id,),
    ).fetchone()
    if not row:
        return None, "해외뉴스를 찾을 수 없습니다."

    article = dict(row)
    translated, error = ai_insights.translate_overseas_news_batch(
        connection, [article], bypass_daily_limits=bypass_daily_limits
    )
    fields = (translated or {}).get(str(article_id))
    if not fields:
        message = str(error or "AI 분석 결과가 비어 있습니다.")[:500]
        connection.execute(
            """
            UPDATE overseas_news_articles
            SET translation_status='retry', translation_error=?, analysis_error=?
            WHERE id=?
            """,
            (message, message, article_id),
        )
        connection.commit()
        return None, message

    fields["canonical_url"] = article.get("original_url")
    _save_analysis(
        connection, article_id, fields, _utc_now(), basis="rss_manual"
    )
    connection.commit()

    if int(fields.get("importance_score") or 0) >= ai_runtime_settings.web_importance_threshold(
        connection
    ):
        web_item = dict(article)
        web_item.update(fields)
        verified, web_error = ai_insights.analyze_important_overseas_news_with_web(
            connection, web_item, bypass_daily_limits=bypass_daily_limits
        )
        if verified:
            _save_analysis(
                connection, article_id, verified, _utc_now(),
                basis="web_search", web_verified=True,
            )
            connection.commit()
            fields = verified
        elif web_error:
            warning = f"중요 뉴스 웹 검증 실패: {str(web_error)[:400]}"
            connection.execute(
                "UPDATE overseas_news_articles SET analysis_error=? WHERE id=?",
                (warning, article_id),
            )
            connection.commit()
            return fields, warning

    return fields, None


def sync(connection, per_feed=25, translate_limit=None):
    """Collect RSS, batch-analyze cheaply, then web-verify only important items."""
    checked_at = _utc_now()
    inserted = 0
    feed_errors = []
    for feed in FEEDS:
        try:
            for article in _fetch_feed(feed, limit=per_feed):
                cursor = connection.execute(
                    """
                    INSERT OR IGNORE INTO overseas_news_articles (
                        article_key, region, original_title, original_summary,
                        publisher, original_url, source_feed, published_at,
                        collected_at, translation_status
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'pending')
                    """,
                    (
                        article["article_key"], article["region"], article["original_title"],
                        article["original_summary"], article["publisher"], article["original_url"],
                        article["source_feed"], article["published_at"], checked_at,
                    ),
                )
                inserted += max(0, cursor.rowcount)
        except Exception as error:  # one feed failure must not block the other region
            message = f"{feed['label']} RSS: {type(error).__name__}: {str(error)[:240]}"
            feed_errors.append(message)
            logger.warning("해외 뉴스 수집 실패: %s", message)
    connection.commit()

    translated, translation_errors = _analyze_pending(connection, limit=translate_limit)
    all_errors = feed_errors + translation_errors
    previous = connection.execute(
        "SELECT last_changed_at FROM overseas_news_sync_state WHERE id=1"
    ).fetchone()
    last_changed_at = checked_at if inserted else (previous["last_changed_at"] if previous else None)
    status = "success" if not all_errors else ("partial" if inserted or translated else "failed")
    connection.execute(
        """
        INSERT INTO overseas_news_sync_state (
            id, last_checked_at, last_changed_at, last_status, last_error, updated_at
        ) VALUES (1, ?, ?, ?, ?, ?)
        ON CONFLICT(id) DO UPDATE SET
            last_checked_at=excluded.last_checked_at,
            last_changed_at=excluded.last_changed_at,
            last_status=excluded.last_status,
            last_error=excluded.last_error,
            updated_at=excluded.updated_at
        """,
        (checked_at, last_changed_at, status, "\n".join(all_errors)[:2000] or None, checked_at),
    )
    connection.commit()
    return {
        "inserted": inserted,
        "translated": translated,
        "status": status,
        "errors": all_errors,
        "checked_at": checked_at,
        "changed_at": last_changed_at,
    }


def _article_filters(
    connection, days=30, region="", term="", category="", impact="",
    important_only=False,
):
    clauses = ["COALESCE(published_at, collected_at) >= datetime('now', ?)"]
    params = [f"-{max(1, int(days))} days"]
    if region in {"macau", "japan"}:
        clauses.append("region=?")
        params.append(region)
    term = (term or "").strip()
    if term:
        like = f"%{term}%"
        clauses.append(
            "(original_title LIKE ? OR title_ko LIKE ? OR original_summary LIKE ? "
            "OR summary_ko LIKE ? OR publisher LIKE ? OR ai_analysis LIKE ?)"
        )
        params.extend([like] * 6)
    category = (category or "").strip()
    if category:
        clauses.append("category=?")
        params.append(category)
    impact = (impact or "").strip().lower()
    if impact in {"positive", "negative", "neutral", "mixed"}:
        clauses.append("impact_direction=?")
        params.append(impact)
    if important_only:
        clauses.append("COALESCE(importance_score, 0) >= ?")
        params.append(ai_runtime_settings.importance_threshold(connection))
    return clauses, params


def list_articles(
    connection, days=30, region="", term="", category="", impact="",
    important_only=False, limit=10, offset=0,
):
    clauses, params = _article_filters(
        connection, days, region, term, category, impact, important_only
    )
    params.extend([max(1, min(int(limit), 100)), max(0, int(offset))])
    articles = [
        dict(row)
        for row in connection.execute(
            f"""
            SELECT * FROM overseas_news_articles
            WHERE {' AND '.join(clauses)}
            ORDER BY COALESCE(published_at, collected_at) DESC, id DESC
            LIMIT ? OFFSET ?
            """,
            params,
        ).fetchall()
    ]
    return _prepare_articles(articles)


def _prepare_articles(articles):
    for article in articles:
        try:
            citations = json.loads(article.get("source_citations_json") or "[]")
        except (TypeError, ValueError, json.JSONDecodeError):
            citations = []
        article["source_citations"] = [
            item for item in citations
            if isinstance(item, dict) and item.get("url")
        ][:3]
        article["display_url"] = article.get("canonical_url") or article.get("original_url")
    return articles


def list_ai_insights(
    connection, days=30, region="", term="", category="", impact="",
    important_only=False, limit=8,
):
    clauses, params = _article_filters(
        connection, days, region, term, category, impact, important_only
    )
    clauses.append("ai_analysis IS NOT NULL AND TRIM(ai_analysis)<>''")
    params.append(max(1, min(int(limit), 30)))
    articles = [
        dict(row)
        for row in connection.execute(
            f"""
            SELECT * FROM overseas_news_articles
            WHERE {' AND '.join(clauses)}
            ORDER BY COALESCE(published_at, collected_at) DESC, id DESC
            LIMIT ?
            """,
            params,
        ).fetchall()
    ]
    return _prepare_articles(articles)


def count_articles(
    connection, days=30, region="", term="", category="", impact="", important_only=False,
):
    clauses, params = _article_filters(
        connection, days, region, term, category, impact, important_only
    )
    row = connection.execute(
        f"SELECT COUNT(*) AS count FROM overseas_news_articles WHERE {' AND '.join(clauses)}",
        params,
    ).fetchone()
    return row["count"] if row else 0


def stats(connection, days=30):
    threshold = ai_runtime_settings.importance_threshold(connection)
    row = connection.execute(
        """
        SELECT COUNT(*) AS total_count,
               SUM(CASE WHEN region='macau' THEN 1 ELSE 0 END) AS macau_count,
               SUM(CASE WHEN region='japan' THEN 1 ELSE 0 END) AS japan_count,
               SUM(CASE WHEN ai_analysis IS NOT NULL THEN 1 ELSE 0 END) AS analyzed_count,
               SUM(CASE WHEN analysis_basis LIKE 'rss_batch%' THEN 1 ELSE 0 END) AS batch_count,
               SUM(CASE WHEN analysis_basis='web_search' THEN 1 ELSE 0 END) AS web_verified_count,
               SUM(CASE WHEN COALESCE(importance_score, 0) >= ? THEN 1 ELSE 0 END) AS important_count,
               SUM(CASE WHEN impact_direction='negative' THEN 1 ELSE 0 END) AS negative_count
        FROM overseas_news_articles
        WHERE COALESCE(published_at, collected_at) >= datetime('now', ?)
        """,
        (threshold, f"-{max(1, int(days))} days"),
    ).fetchone()
    return dict(row) if row else {}


def list_categories(connection, days=365):
    return [
        dict(row)
        for row in connection.execute(
            """
            SELECT category, COUNT(*) AS article_count
            FROM overseas_news_articles
            WHERE category IS NOT NULL AND category<>''
              AND COALESCE(published_at, collected_at) >= datetime('now', ?)
            GROUP BY category
            ORDER BY article_count DESC, category
            """,
            (f"-{max(1, int(days))} days",),
        ).fetchall()
    ]


def sync_state(connection):
    row = connection.execute("SELECT * FROM overseas_news_sync_state WHERE id=1").fetchone()
    return dict(row) if row else {}
