"""Incremental, validated OpenAI translation for the localization inventory."""

from __future__ import annotations

import json
import re

import config
from dashboard_db import queries
from services import ai_insights, localization_management


TARGETS = {
    "ja": {
        "name": "Japanese",
        "rule": (
            "Use natural Japanese suitable for a professional casino-industry website. "
            "Do not return English-only text when the Korean source requires translation."
        ),
    },
    "yue-HK": {
        "name": "Hong Kong Cantonese in Traditional Chinese",
        "rule": (
            "Use natural written Cantonese for Hong Kong readers in Traditional Chinese, "
            "not Simplified Chinese or English-only text."
        ),
    },
}

URL_RE = re.compile(r"https?://[^\s<>'\"]+")
NUMBER_RE = re.compile(r"(?<![\w])[-+]?\d[\d,.]*%?")
TARGET_SCRIPT_RE = {
    "ja": re.compile(r"[ぁ-ゖァ-ヺ一-龯]"),
    "yue-HK": re.compile(r"[一-龯]"),
}

TRANSLATION_SCHEMA = {
    "type": "object",
    "properties": {
        "translations": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "id": {"type": "integer"},
                    "text": {"type": "string"},
                },
                "required": ["id", "text"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["translations"],
    "additionalProperties": False,
}


def configured_languages():
    values = [
        value.strip()
        for value in config.LOCALIZATION_TRANSLATION_LANGUAGES.split(",")
        if value.strip()
    ]
    return [value for value in values if value in TARGETS]


def pending_rows(connection, language_code, limit=None):
    limit = max(1, int(limit or config.LOCALIZATION_TRANSLATION_MAX_ITEMS_PER_RUN))
    rows = connection.execute(
        """SELECT s.id, s.language_key, s.source_text, s.page_name, s.string_type
           FROM localization_strings s
           LEFT JOIN localization_translations t
             ON t.string_id=s.id AND t.language_code=?
           JOIN localization_languages l
             ON l.language_code=? AND l.is_active=1 AND l.is_source=0
           WHERE s.deleted_at IS NULL AND s.status<>'Ignored'
             AND COALESCE(t.status,'Pending')<>'Completed'
           ORDER BY CASE s.priority WHEN 'Critical' THEN 0 WHEN 'High' THEN 1
                    WHEN 'Medium' THEN 2 ELSE 3 END,
                    s.created_at, s.id
           LIMIT ?""",
        (language_code, language_code, limit),
    ).fetchall()
    return [dict(row) for row in rows]


def _batches(rows):
    max_items = max(1, config.LOCALIZATION_TRANSLATION_BATCH_SIZE)
    max_chars = max(1000, config.LOCALIZATION_TRANSLATION_MAX_CHARS_PER_BATCH)
    batches, current, current_chars = [], [], 0
    for row in rows:
        size = len(row["source_text"])
        if current and (len(current) >= max_items or current_chars + size > max_chars):
            batches.append(current)
            current, current_chars = [], 0
        current.append(row)
        current_chars += size
    if current:
        batches.append(current)
    return batches


def _system_prompt(language_code, glossary):
    target = TARGETS[language_code]
    glossary_text = "\n".join(
        f"- {item['source_text']} => {item['target_text']}" for item in glossary
    ) or "- No glossary entries"
    return (
        "You translate Korean website localization strings. Return every supplied numeric "
        "id exactly once and provide only its translation in the requested JSON schema. "
        "Preserve meaning, numbers, dates, currencies, URLs, line breaks, HTML tags, "
        "Markdown syntax, and placeholders exactly. Never add facts, explanations, or labels. "
        "Keep company, brand, and product identities accurate. "
        f"Target language: {target['name']}. {target['rule']}\n\n"
        f"Required glossary:\n{glossary_text}"
    )


def _call_openai(connection, language_code, rows, glossary):
    payload = {
        "items": [
            {
                "id": row["id"],
                "page": row["page_name"],
                "type": row["string_type"],
                "source": row["source_text"],
            }
            for row in rows
        ]
    }
    return ai_insights._call(
        connection,
        f"localization_translation_{language_code}",
        _system_prompt(language_code, glossary),
        json.dumps(payload, ensure_ascii=False),
        f"localization_translation_{language_code.replace('-', '_')}",
        TRANSLATION_SCHEMA,
        model=config.OPENAI_TRANSLATION_MODEL,
    )


def _validation_error(source, target, language_code):
    text = str(target or "").strip()
    if not text:
        return "empty translation"
    if localization_management.HANGUL_RE.search(text):
        return "Korean text remains"
    if not TARGET_SCRIPT_RE[language_code].search(text):
        return "target-language script is missing"
    if sorted(localization_management.VARIABLE_RE.findall(source)) != sorted(
        localization_management.VARIABLE_RE.findall(text)
    ):
        return "placeholder mismatch"
    if localization_management.TAG_RE.findall(source) != localization_management.TAG_RE.findall(text):
        return "HTML tag mismatch"
    if sorted(URL_RE.findall(source)) != sorted(URL_RE.findall(text)):
        return "URL mismatch"
    if sorted(NUMBER_RE.findall(source)) != sorted(NUMBER_RE.findall(text)):
        return "number or date mismatch"
    if source.count("\n") != text.count("\n"):
        return "line-break mismatch"
    if len(text) > max(500, len(source) * 6):
        return "translation is unexpectedly long"
    return None


def translate_batch(connection, language_code, rows, call_openai=None):
    glossary = localization_management.list_glossary(
        connection, language_code, active_only=True
    )
    caller = call_openai or _call_openai
    data, error = caller(connection, language_code, rows, glossary)
    if not data:
        return {"saved": 0, "rejected": len(rows), "error": error or "empty API response"}

    expected = {row["id"]: row for row in rows}
    seen, saved, rejected = set(), 0, 0
    for item in data.get("translations", []):
        string_id = item.get("id")
        if string_id in seen or string_id not in expected:
            rejected += 1
            continue
        seen.add(string_id)
        row = expected[string_id]
        translated_text = str(item.get("text") or "").strip()
        validation_error = _validation_error(
            row["source_text"], translated_text, language_code
        )
        if validation_error:
            rejected += 1
            continue
        localization_management.save_translation(
            connection,
            string_id,
            language_code,
            translated_text,
            actor_id=None,
            status="Completed",
        )
        saved += 1
    rejected += len(expected) - len(seen)
    connection.commit()
    return {"saved": saved, "rejected": rejected, "error": None}


def run_daily(connection, project_root, *, scan=True, call_openai=None):
    if not config.OPENAI_API_KEY:
        raise RuntimeError("OPENAI_API_KEY is not configured")
    if not config.OPENAI_TRANSLATION_MODEL:
        raise RuntimeError("OPENAI_TRANSLATION_MODEL is not configured")

    summary = {
        "scan": localization_management.scan_project(connection, project_root) if scan else None,
        "model": config.OPENAI_TRANSLATION_MODEL,
        "languages": {},
        "stopped_reason": None,
    }
    stop = False
    for language_code in configured_languages():
        rows = pending_rows(connection, language_code)
        result = {"pending": len(rows), "saved": 0, "rejected": 0, "batches": 0}
        for batch in _batches(rows):
            batch_result = translate_batch(
                connection, language_code, batch, call_openai=call_openai
            )
            result["batches"] += 1
            result["saved"] += batch_result["saved"]
            result["rejected"] += batch_result["rejected"]
            if batch_result["error"]:
                summary["stopped_reason"] = batch_result["error"]
                queries.log_error(
                    connection,
                    "localization_auto_translation",
                    language_code,
                    batch_result["error"],
                )
                stop = True
                break
        summary["languages"][language_code] = result
        if stop:
            break
    return summary
