"""Persist and summarize per-request Gemini usage for overseas-news analysis."""

from __future__ import annotations

import sqlite3
from datetime import datetime

import config


def _now_kst():
    return datetime.now(config.KST).isoformat(timespec="seconds")


def _usd_krw_rate(connection):
    """Use the latest collected USD rate, with a documented config fallback."""
    try:
        row = connection.execute(
            """
            SELECT value FROM economic_series
            WHERE series_code='FX_USD' AND value>0
            ORDER BY observation_date DESC LIMIT 1
            """
        ).fetchone()
    except sqlite3.OperationalError:
        row = None
    if row and float(row["value"] or 0) > 0:
        return float(row["value"])
    return float(config.GEMINI_USD_KRW_FALLBACK_RATE)


def record_article_usage(connection, article, usage_records, called_at=None, success=True):
    """Append every successful Gemini API response associated with one article."""
    if not usage_records:
        return 0
    rate = _usd_krw_rate(connection)
    called_at = called_at or _now_kst()
    rows = []
    for usage in usage_records:
        estimated_cost_usd = max(0.0, float(usage.get("estimated_cost_usd") or 0))
        rows.append(
            (
                called_at,
                usage.get("model") or config.GEMINI_MODEL,
                "overseas_news_article",
                max(0, int(usage.get("input_tokens") or 0)),
                max(0, int(usage.get("output_tokens") or 0)),
                estimated_cost_usd,
                1 if success else 0,
                "gemini",
                article.get("id"),
                (article.get("original_title") or "")[:500],
                (article.get("original_url") or "")[:2000],
                (usage.get("request_stage") or "generate_content")[:80],
                max(0, int(usage.get("thought_tokens") or 0)),
                max(0, int(usage.get("total_tokens") or 0)),
                max(0, int(usage.get("search_query_count") or 0)),
                max(0.0, float(usage.get("input_cost_usd") or 0)),
                max(0.0, float(usage.get("output_cost_usd") or 0)),
                max(0.0, float(usage.get("search_cost_usd") or 0)),
                rate,
                estimated_cost_usd * rate,
            )
        )
    connection.executemany(
        """
        INSERT INTO api_usage (
            called_at, model, request_type, input_tokens, output_tokens,
            estimated_cost, success, provider, article_id, article_title,
            article_url, request_stage, thought_tokens, total_tokens,
            search_query_count, input_cost_usd, output_cost_usd,
            search_cost_usd, usd_krw_rate, estimated_cost_krw
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        rows,
    )
    return len(rows)


def _summary(connection, where="", params=()):
    row = connection.execute(
        f"""
        SELECT COUNT(*) AS call_count,
               COUNT(DISTINCT article_id) AS article_count,
               COALESCE(SUM(input_tokens), 0) AS input_tokens,
               COALESCE(SUM(output_tokens), 0) AS output_tokens,
               COALESCE(SUM(thought_tokens), 0) AS thought_tokens,
               COALESCE(SUM(total_tokens), 0) AS total_tokens,
               COALESCE(SUM(search_query_count), 0) AS search_query_count,
               COALESCE(SUM(estimated_cost), 0) AS estimated_cost_usd,
               COALESCE(SUM(estimated_cost_krw), 0) AS estimated_cost_krw
        FROM api_usage
        WHERE provider='gemini' {where}
        """,
        params,
    ).fetchone()
    return dict(row)


def admin_dashboard(connection):
    today = datetime.now(config.KST).strftime("%Y-%m-%d")
    month = datetime.now(config.KST).strftime("%Y-%m")
    recent_articles = [
        dict(row)
        for row in connection.execute(
            """
            SELECT u.article_id,
                   COALESCE(NULLIF(a.title_ko, ''), u.article_title) AS article_title,
                   COALESCE(NULLIF(a.canonical_url, ''), u.article_url) AS article_url,
                   a.publisher,
                   COUNT(*) AS call_count,
                   GROUP_CONCAT(DISTINCT u.request_stage) AS request_stages,
                   SUM(u.input_tokens) AS input_tokens,
                   SUM(u.output_tokens) AS output_tokens,
                   SUM(u.thought_tokens) AS thought_tokens,
                   SUM(u.search_query_count) AS search_query_count,
                   SUM(u.estimated_cost) AS estimated_cost_usd,
                   SUM(u.estimated_cost_krw) AS estimated_cost_krw,
                   MAX(u.called_at) AS called_at,
                   MAX(u.model) AS model
            FROM api_usage u
            LEFT JOIN overseas_news_articles a ON a.id=u.article_id
            WHERE u.provider='gemini'
            GROUP BY u.article_id, u.article_title, u.article_url
            ORDER BY MAX(u.called_at) DESC
            LIMIT 100
            """
        ).fetchall()
    ]
    daily = [
        dict(row)
        for row in connection.execute(
            """
            SELECT SUBSTR(called_at, 1, 10) AS usage_date,
                   COUNT(*) AS call_count,
                   COUNT(DISTINCT article_id) AS article_count,
                   SUM(input_tokens) AS input_tokens,
                   SUM(output_tokens) AS output_tokens,
                   SUM(thought_tokens) AS thought_tokens,
                   SUM(search_query_count) AS search_query_count,
                   SUM(estimated_cost) AS estimated_cost_usd,
                   SUM(estimated_cost_krw) AS estimated_cost_krw
            FROM api_usage
            WHERE provider='gemini'
            GROUP BY SUBSTR(called_at, 1, 10)
            ORDER BY usage_date DESC
            LIMIT 31
            """
        ).fetchall()
    ]
    return {
        "today": _summary(connection, "AND called_at LIKE ?", (f"{today}%",)),
        "month": _summary(connection, "AND called_at LIKE ?", (f"{month}%",)),
        "all_time": _summary(connection),
        "daily": daily,
        "recent_articles": recent_articles,
        "pricing": {
            "input_per_million_usd": config.GEMINI_INPUT_COST_PER_1M_USD,
            "output_per_million_usd": config.GEMINI_OUTPUT_COST_PER_1M_USD,
            "search_per_thousand_usd": config.GEMINI_SEARCH_COST_PER_1000_USD,
            "fallback_rate": config.GEMINI_USD_KRW_FALLBACK_RATE,
        },
    }
