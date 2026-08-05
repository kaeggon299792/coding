"""Database-backed runtime policies for each OpenAI workload.

API secrets remain in server environment variables.  Only non-secret operational
settings (enabled state, model and limits) are stored in ``site_settings``.
"""

import re

import config
from utils import now_kst


PURPOSES = {
    "translation": {
        "label": "사이트 번역",
        "description": "Localization 및 사용자 노출 콘텐츠 번역",
        "default_model": lambda: config.OPENAI_TRANSLATION_MODEL,
        "default_limit": 50,
    },
    "news_importance": {
        "label": "해외뉴스 분석·중요도",
        "description": "해외뉴스 한국어 분석, 중요도 산정 및 중요기사 웹 검증",
        "default_model": lambda: config.OPENAI_NEWS_MODEL,
        "default_limit": 30,
        "importance_threshold": 60,
        "web_importance_threshold": lambda: config.OPENAI_NEWS_WEB_IMPORTANCE_THRESHOLD,
    },
    "disclosure_ir": {
        "label": "공시·IR 분석",
        "description": "DART 공시와 기업 IR 자료 분석",
        "default_model": lambda: config.OPENAI_INSIGHT_MODEL,
        "default_limit": 30,
    },
    "research": {
        "label": "리서치 PDF 분석",
        "description": "리서치·PDF 제목 생성과 본문 분석",
        "default_model": lambda: config.OPENAI_INSIGHT_MODEL,
        "default_limit": 30,
    },
    "legal": {
        "label": "법률·입법 분석",
        "description": "현행법령, 정부입법예고 및 국회 의안 분석",
        "default_model": lambda: config.OPENAI_INSIGHT_MODEL,
        "default_limit": 30,
    },
    "executive": {
        "label": "경영 인사이트",
        "description": "경영 관점 일일 인사이트와 기타 분석",
        "default_model": lambda: config.OPENAI_INSIGHT_MODEL,
        "default_limit": 30,
    },
}

_MODEL_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,79}\Z")


def classify_request_type(request_type):
    value = str(request_type or "")
    if value.startswith(("localization_translation_", "content_translation_")):
        return "translation"
    if value.startswith("overseas_news_"):
        return "news_importance"
    if value == "disclosure_summary" or value.startswith("ir_document_"):
        return "disclosure_ir"
    if value.startswith("research_document_"):
        return "research"
    if value.startswith(("law_", "legislative_")):
        return "legal"
    return "executive"


def _default_value(purpose, field):
    definition = PURPOSES[purpose]
    value = definition.get(field)
    return value() if callable(value) else value


def _setting_key(purpose, field):
    return f"ai_purpose_{purpose}_{field}"


def get_purpose_settings(connection, purpose):
    if purpose not in PURPOSES:
        raise ValueError("지원하지 않는 AI 용도입니다.")
    values = {}
    try:
        rows = connection.execute(
            "SELECT setting_key,setting_value FROM site_settings WHERE setting_key LIKE ?",
            (f"ai_purpose_{purpose}_%",),
        ).fetchall()
        values = {row["setting_key"]: row["setting_value"] for row in rows}
    except Exception:
        # Lightweight unit-test databases and first-start recovery must retain
        # the safe environment defaults.
        values = {}

    enabled_raw = values.get(_setting_key(purpose, "enabled"), "1")
    model = values.get(_setting_key(purpose, "model")) or _default_value(
        purpose, "default_model"
    )
    limit_raw = values.get(_setting_key(purpose, "daily_call_limit"))
    try:
        daily_limit = int(limit_raw) if limit_raw is not None else int(
            _default_value(purpose, "default_limit")
        )
    except (TypeError, ValueError):
        daily_limit = int(_default_value(purpose, "default_limit"))
    result = {
        "purpose": purpose,
        "label": PURPOSES[purpose]["label"],
        "description": PURPOSES[purpose]["description"],
        "enabled": str(enabled_raw).strip().lower() in {"1", "true", "yes", "on"},
        "model": str(model or "").strip(),
        "daily_call_limit": max(1, min(daily_limit, 100000)),
    }
    if purpose == "news_importance":
        for field in ("importance_threshold", "web_importance_threshold"):
            raw = values.get(_setting_key(purpose, field))
            try:
                value = int(raw) if raw is not None else int(_default_value(purpose, field))
            except (TypeError, ValueError):
                value = int(_default_value(purpose, field))
            result[field] = max(0, min(value, 100))
    return result


def get_request_settings(connection, request_type, fallback_model=""):
    purpose = classify_request_type(request_type)
    settings = get_purpose_settings(connection, purpose)
    if not settings["model"]:
        settings["model"] = str(fallback_model or "").strip()
    return settings


def save_purpose_settings(connection, purpose, values, actor_id=None):
    current = get_purpose_settings(connection, purpose)
    enabled = str(values.get("enabled") or "").lower() in {"1", "true", "yes", "on"}
    model = str(values.get("model") or "").strip()
    if not _MODEL_RE.fullmatch(model):
        raise ValueError(f"{current['label']} 모델명을 확인해주세요.")
    try:
        daily_limit = int(values.get("daily_call_limit"))
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{current['label']} 일일 한도는 숫자로 입력해주세요.") from exc
    if not 1 <= daily_limit <= 100000:
        raise ValueError(f"{current['label']} 일일 한도는 1~100,000회로 설정해주세요.")

    fields = {
        "enabled": "1" if enabled else "0",
        "model": model,
        "daily_call_limit": str(daily_limit),
    }
    if purpose == "news_importance":
        for field, label in (
            ("importance_threshold", "중요 뉴스 기준"),
            ("web_importance_threshold", "웹 검증 기준"),
        ):
            try:
                threshold = int(values.get(field))
            except (TypeError, ValueError) as exc:
                raise ValueError(f"{label}은 0~100 사이 숫자로 입력해주세요.") from exc
            if not 0 <= threshold <= 100:
                raise ValueError(f"{label}은 0~100 사이로 설정해주세요.")
            fields[field] = str(threshold)

    updated_at = now_kst().isoformat()
    for field, value in fields.items():
        connection.execute(
            """INSERT INTO site_settings(setting_key,setting_value,updated_by,updated_at)
               VALUES (?,?,?,?)
               ON CONFLICT(setting_key) DO UPDATE SET
                 setting_value=excluded.setting_value,
                 updated_by=excluded.updated_by,updated_at=excluded.updated_at""",
            (_setting_key(purpose, field), value, actor_id, updated_at),
        )
    return get_purpose_settings(connection, purpose)


def _usage_since(connection):
    now = now_kst()
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0).isoformat()
    try:
        row = connection.execute(
            "SELECT setting_value FROM site_settings WHERE setting_key='openai_usage_reset_at'"
        ).fetchone()
    except Exception:
        row = None
    reset_at = row["setting_value"] if row else ""
    return reset_at if reset_at.startswith(now.strftime("%Y-%m-%d")) else today_start


def usage_by_purpose(connection):
    since = _usage_since(connection)
    rows = connection.execute(
        """SELECT request_type,estimated_cost FROM api_usage
           WHERE called_at>=? AND (provider='openai' OR provider IS NULL)""",
        (since,),
    ).fetchall()
    result = {
        purpose: {"call_count": 0, "total_cost": 0.0}
        for purpose in PURPOSES
    }
    for row in rows:
        item = result[classify_request_type(row["request_type"])]
        item["call_count"] += 1
        item["total_cost"] += float(row["estimated_cost"] or 0)
    return result


def get_purpose_usage(connection, purpose):
    return usage_by_purpose(connection)[purpose]


def dashboard(connection):
    usage = usage_by_purpose(connection)
    result = []
    for purpose in PURPOSES:
        item = get_purpose_settings(connection, purpose)
        item["usage"] = usage[purpose]
        result.append(item)
    return result


def importance_threshold(connection):
    return get_purpose_settings(connection, "news_importance")["importance_threshold"]


def web_importance_threshold(connection):
    return get_purpose_settings(connection, "news_importance")["web_importance_threshold"]
