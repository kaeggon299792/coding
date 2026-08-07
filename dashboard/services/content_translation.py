"""Daily cached English translations for public dynamic content."""

import hashlib
import json
import re

import config
from services import ai_insights, news_reader
from utils import now_kst


SOURCE_FIELDS = {
    "tip": ("title", "summary", "body", "category", "tags_json"),
    "tip_comment": ("content",),
    "related_site": ("title", "description", "category", "tags"),
    "research": ("title", "ai_summary", "key_points_json", "risks_json", "industry_impact"),
    "news": ("title", "issue_title", "category", "latest_summary"),
}

CJK_RE = re.compile(r"[\u3040-\u30ff\u3400-\u9fff\uac00-\ud7a3]")


def _as_dict(item):
    return dict(item) if item is not None else {}


def source_hash(fields):
    payload = json.dumps(fields, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def make_entry(content_type, content_id, item):
    data = _as_dict(item)
    fields = {name: data.get(name) or "" for name in SOURCE_FIELDS[content_type]}
    return {
        "key": f"{content_type}:{content_id}",
        "content_type": content_type,
        "content_id": str(content_id),
        "fields": fields,
        "source_hash": source_hash(fields),
    }


def apply_cached(connection, content_type, items, id_field="id"):
    """Overlay matching English cache entries; stale translations are not displayed."""
    results = []
    for original in items or []:
        item = _as_dict(original)
        content_id = item.get(id_field)
        if content_id is None:
            results.append(item)
            continue
        entry = make_entry(content_type, content_id, item)
        row = connection.execute(
            """SELECT translated_json FROM content_translations
               WHERE content_type=? AND content_id=? AND locale='en'
                 AND status='success' AND source_hash=?""",
            (content_type, str(content_id), entry["source_hash"]),
        ).fetchone()
        if row and row["translated_json"]:
            try:
                item.update(json.loads(row["translated_json"]))
            except (TypeError, ValueError):
                pass
        results.append(item)
    return results


def apply_one(connection, content_type, item, id_field="id"):
    translated = apply_cached(connection, content_type, [item], id_field=id_field)
    return translated[0] if translated else item


def mask_cjk_fallbacks(items, field_fallbacks):
    """Prevent untranslated CJK source text from leaking into English pages."""
    results = []
    for original in items or []:
        item = _as_dict(original)
        for field, fallback in field_fallbacks.items():
            value = str(item.get(field) or "")
            if value and CJK_RE.search(value):
                item[field] = fallback
        results.append(item)
    return results


def _collect_dashboard_entries(connection):
    entries = []
    selections = (
        ("tip", "SELECT * FROM tips_articles WHERE is_deleted=0 AND draft=0"),
        ("tip_comment", """SELECT c.* FROM tips_comments c JOIN tips_articles t ON t.id=c.tip_id
                            WHERE c.is_deleted=0 AND t.is_deleted=0 AND t.draft=0"""),
        ("related_site", "SELECT * FROM related_sites WHERE is_deleted=0 AND is_public=1"),
        ("research", "SELECT * FROM research_documents"),
    )
    for content_type, sql in selections:
        for row in connection.execute(sql).fetchall():
            entries.append(make_entry(content_type, row["id"], row))
    return entries


def _collect_news_entries():
    articles = []
    while len(articles) < config.CONTENT_TRANSLATION_NEWS_SCAN_LIMIT:
        page_size = min(100, config.CONTENT_TRANSLATION_NEWS_SCAN_LIMIT - len(articles))
        page = news_reader.list_articles(
            days=config.CONTENT_TRANSLATION_NEWS_DAYS,
            limit=page_size,
            offset=len(articles),
        )
        articles.extend(page)
        if len(page) < page_size:
            break
    return [make_entry("news", item["article_id"], item) for item in articles]


def _needs_translation(connection, entry):
    row = connection.execute(
        """SELECT source_hash, status FROM content_translations
           WHERE content_type=? AND content_id=? AND locale='en'""",
        (entry["content_type"], entry["content_id"]),
    ).fetchone()
    return not row or row["source_hash"] != entry["source_hash"] or row["status"] != "success"


def _batches(entries):
    batch, characters = [], 0
    for entry in entries:
        size = sum(len(str(value or "")) for value in entry["fields"].values())
        if batch and (len(batch) >= config.CONTENT_TRANSLATION_BATCH_SIZE or
                      characters + size > config.CONTENT_TRANSLATION_MAX_CHARS_PER_BATCH):
            yield batch
            batch, characters = [], 0
        batch.append(entry)
        characters += size
    if batch:
        yield batch


def _save(connection, entry, translated=None, error=None):
    timestamp = now_kst().isoformat(timespec="seconds")
    status = "success" if translated is not None else "error"
    connection.execute(
        """INSERT INTO content_translations
               (content_type, content_id, locale, source_hash, translated_json,
                status, error_message, translated_at, updated_at)
           VALUES (?, ?, 'en', ?, ?, ?, ?, ?, ?)
           ON CONFLICT(content_type, content_id, locale) DO UPDATE SET
               source_hash=excluded.source_hash,
               translated_json=CASE WHEN excluded.status='success'
                                    THEN excluded.translated_json
                                    ELSE content_translations.translated_json END,
               status=excluded.status, error_message=excluded.error_message,
               translated_at=CASE WHEN excluded.status='success'
                                  THEN excluded.translated_at
                                  ELSE content_translations.translated_at END,
               updated_at=excluded.updated_at""",
        (entry["content_type"], entry["content_id"], entry["source_hash"],
         json.dumps(translated, ensure_ascii=False) if translated is not None else None,
         status, (error or "")[:500] or None,
         timestamp if translated is not None else None, timestamp),
    )


def run_daily_translation(connection):
    """Translate only new or modified public records."""
    entries = _collect_dashboard_entries(connection) + _collect_news_entries()
    pending = [entry for entry in entries if _needs_translation(connection, entry)]
    pending = pending[:config.CONTENT_TRANSLATION_MAX_ITEMS_PER_RUN]
    summary = {"found": len(entries), "pending": len(pending), "translated": 0, "failed": 0}
    for batch in _batches(pending):
        translated, error = ai_insights.translate_content_batch(connection, batch)
        if translated is None:
            for entry in batch:
                _save(connection, entry, error=error)
                summary["failed"] += 1
            connection.commit()
            continue
        for entry in batch:
            result = translated.get(entry["key"])
            if result is None:
                _save(connection, entry, error="Translation response omitted this item")
                summary["failed"] += 1
            else:
                _save(connection, entry, translated=result)
                summary["translated"] += 1
        connection.commit()
    summary["completed_at"] = now_kst().isoformat(timespec="minutes")
    return summary
