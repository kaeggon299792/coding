"""
OpenAI Responses API 호출 모듈 (경영진 시사점 / 공시 분석 / 법률 분석 공통).

casino_news_watch/openai_analyzer.py의 패턴을 그대로 재사용한다: Responses API +
json_schema strict 구조화 출력, 호출 전 일일 한도 확인, 토큰/비용을 dashboard.db의
api_usage 테이블에 기록. 이 모듈만의 독립적인 예산(MAX_GPT_CALLS_PER_DAY,
DAILY_OPENAI_BUDGET_USD)을 쓰며, 기존 뉴스/이메일 프로그램의 예산과는 완전히
분리되어 있다(서로 다른 DB에 각자 기록).

OPENAI_API_KEY가 없거나 호출이 실패해도 예외를 상위로 던지지 않고
{"ai_summary": None, "error": "..."} 형태로 반환한다 - 호출측이 이 error를
그대로 DB의 error_message 컬럼에 저장해 나중에 재시도할 수 있게 한다.
"""

import json
import logging

import config
from dashboard_db import queries

logger = logging.getLogger("dashboard")

_client = None


class DailyLimitExceeded(Exception):
    pass


def _get_client():
    global _client
    if _client is None:
        from openai import OpenAI

        _client = OpenAI(
            api_key=config.OPENAI_API_KEY,
            timeout=config.OPENAI_REQUEST_TIMEOUT_SECONDS,
            max_retries=config.OPENAI_MAX_RETRIES,
        )
    return _client


def _check_daily_limits(connection):
    summary = queries.get_today_usage_summary(connection)
    if summary["call_count"] >= config.MAX_GPT_CALLS_PER_DAY:
        raise DailyLimitExceeded(f"하루 GPT 호출 한도({config.MAX_GPT_CALLS_PER_DAY}회)에 도달했습니다.")
    if summary["total_cost"] >= config.DAILY_OPENAI_BUDGET_USD:
        raise DailyLimitExceeded(f"하루 예상 비용 한도(${config.DAILY_OPENAI_BUDGET_USD:.2f})에 도달했습니다.")


def _estimate_cost(input_tokens, output_tokens):
    if config.OPENAI_INPUT_COST_PER_1M is None or config.OPENAI_OUTPUT_COST_PER_1M is None:
        return 0.0
    return (input_tokens / 1_000_000) * config.OPENAI_INPUT_COST_PER_1M + (
        output_tokens / 1_000_000
    ) * config.OPENAI_OUTPUT_COST_PER_1M


def _call(connection, request_type, system_prompt, user_prompt, schema_name, schema):
    """공통 호출 헬퍼. 실패해도 예외를 던지지 않고 (data, error) 튜플을 반환한다."""

    if not config.OPENAI_API_KEY or not config.OPENAI_INSIGHT_MODEL:
        return None, "OPENAI_API_KEY 또는 OPENAI_INSIGHT_MODEL이 설정되지 않았습니다."

    try:
        _check_daily_limits(connection)
    except DailyLimitExceeded as error:
        return None, str(error)

    input_tokens = 0
    output_tokens = 0
    success = False
    data = None
    error_message = None

    try:
        client = _get_client()
        response = client.responses.create(
            model=config.OPENAI_INSIGHT_MODEL,
            input=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            text={
                "format": {
                    "type": "json_schema",
                    "name": schema_name,
                    "schema": schema,
                    "strict": True,
                }
            },
        )
        if response.usage is not None:
            input_tokens = response.usage.input_tokens
            output_tokens = response.usage.output_tokens

        data = json.loads(response.output_text)
        success = True
    except (json.JSONDecodeError, ValueError) as error:
        error_message = f"응답 검증 실패: {error}"
        logger.error("AI 응답 검증 실패(%s): %s", request_type, error)
    except Exception as error:
        error_message = f"API 호출 실패: {type(error).__name__}"
        logger.error("AI 호출 실패(%s): %s", request_type, error)
    finally:
        cost = _estimate_cost(input_tokens, output_tokens)
        queries.record_api_usage(
            connection, config.OPENAI_INSIGHT_MODEL, request_type, input_tokens, output_tokens, cost, success
        )

    return data, error_message


# ============================================================
# 공시 분석
# ============================================================

_DISCLOSURE_SCHEMA = {
    "type": "object",
    "properties": {
        "ai_summary": {"type": "string", "description": "공시 핵심 내용 3~5문장 요약"},
        "financial_impact": {"type": "string", "description": "재무적 영향(확인된 사실과 추정을 구분해서 서술)"},
        "competitive_impact": {"type": "string", "description": "경쟁 구도에 미치는 영향"},
        "risk_category": {"type": "string", "description": "리스크 분류(예: 재무, 소송, 지배구조, 규제 등)"},
        "needs_executive_review": {"type": "boolean"},
    },
    "required": ["ai_summary", "financial_impact", "competitive_impact", "risk_category", "needs_executive_review"],
    "additionalProperties": False,
}

_DISCLOSURE_SYSTEM_PROMPT = (
    "당신은 카지노·관광 그룹 경영기획팀의 공시 분석 보조자입니다. "
    "주어진 공시 메타데이터(제목/기업/유형/접수일)만으로 판단하세요. "
    "공시 원문을 직접 읽지 못했으므로 구체적 수치를 임의로 만들어내지 말고, "
    "확실하지 않은 내용은 '추정' 또는 '원문 확인 필요'로 표현하세요."
)


def summarize_disclosure(connection, disclosure_info):
    user_prompt = (
        f"기업: {disclosure_info.get('corp_name')}\n"
        f"공시명: {disclosure_info.get('report_nm')}\n"
        f"접수일: {disclosure_info.get('rcept_dt')}\n"
        f"제출인: {disclosure_info.get('flr_nm')}\n\n"
        "이 공시가 경쟁사/당사에 미칠 수 있는 영향을 분석하세요."
    )
    data, error = _call(
        connection, "disclosure_summary", _DISCLOSURE_SYSTEM_PROMPT, user_prompt,
        "disclosure_summary", _DISCLOSURE_SCHEMA,
    )
    if error or not data:
        return {"ai_summary": None, "financial_impact": None, "competitive_impact": None,
                "risk_category": None, "needs_executive_review": True, "error": error}
    data["error"] = None
    return data


# ============================================================
# 법률 변경 분석
# ============================================================

_LAW_SCHEMA = {
    "type": "object",
    "properties": {
        "ai_summary": {"type": "string", "description": "확인된 법적 사실과 핵심 변경 내용 요약"},
        "affected_scope": {"type": "string", "description": "적용 대상"},
        "company_impact": {"type": "string", "description": "당사에 미치는 직접/간접 영향(추정은 반드시 '추정'으로 표시)"},
        "action_needed": {"type": "string", "description": "준비해야 할 사항 및 법무 확인 필요 여부"},
    },
    "required": ["ai_summary", "affected_scope", "company_impact", "action_needed"],
    "additionalProperties": False,
}

_LAW_SYSTEM_PROMPT = (
    "당신은 카지노·관광업 법무 담당자를 보조하는 분석가입니다. 법률 자문을 대체하지 않으며, "
    "불확실한 내용은 반드시 '법무팀 확인 필요'로 표시하세요. 시행 여부·시행일을 단정하지 말고 "
    "주어진 정보 범위 내에서만 답하세요."
)


def summarize_law_change(connection, law_info):
    user_prompt = (
        f"법령명: {law_info.get('law_name')}\n"
        f"상태: {law_info.get('status')}\n"
        f"시행일자: {law_info.get('effective_date')}\n\n"
        "이 법령 변경이 카지노·호텔·관광업(당사)에 미치는 영향을 분석하세요."
    )
    data, error = _call(
        connection, "law_summary", _LAW_SYSTEM_PROMPT, user_prompt, "law_summary", _LAW_SCHEMA,
    )
    if error or not data:
        return {"ai_summary": None, "affected_scope": None, "company_impact": None,
                "action_needed": None, "error": error}
    data["error"] = None
    return data


# ============================================================
# 경영진 관점 종합 시사점 (일 1회 배치)
# ============================================================

_EXEC_INSIGHT_SCHEMA = {
    "type": "object",
    "properties": {
        "insights": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "title": {"type": "string"},
                    "importance": {"type": "string", "enum": ["high", "medium", "low"]},
                    "facts": {"type": "string", "description": "확인된 사실만"},
                    "ai_interpretation": {"type": "string"},
                    "expected_impact": {"type": "string"},
                    "recommended_action": {"type": "string"},
                    "needs_executive_review": {"type": "boolean"},
                    "category": {"type": "string", "enum": ["fact", "estimate", "opinion", "action"]},
                    "evidence_refs": {"type": "array", "items": {"type": "string"}},
                },
                "required": [
                    "title", "importance", "facts", "ai_interpretation", "expected_impact",
                    "recommended_action", "needs_executive_review", "category", "evidence_refs",
                ],
                "additionalProperties": False,
            },
        }
    },
    "required": ["insights"],
    "additionalProperties": False,
}

_EXEC_INSIGHT_SYSTEM_PROMPT = (
    "당신은 카지노·복합리조트 그룹 경영기획팀의 AI 분석 보조자입니다. "
    "제공된 오늘의 중요 뉴스, 임원 확인 필요 이메일, 실적 변동 데이터를 종합해 "
    "경영진 관점의 시사점을 작성하세요.\n"
    "반드시 지킬 것:\n"
    "- 근거 데이터에 없는 내용을 단정적으로 만들어내지 마세요.\n"
    "- 상관관계를 인과관계로 단정하지 마세요. 원인이 데이터로 확인되지 않으면 "
    "'가능성' 또는 '추정'으로 표현하세요.\n"
    "- 각 시사점은 사실(fact)/추정(estimate)/의견(opinion)/대응제안(action) 중 "
    "하나로 명확히 분류하세요.\n"
    "- 제공된 데이터가 부족하면 시사점 개수를 억지로 늘리지 말고, 근거가 확실한 것만 작성하세요."
)


def generate_daily_insights(connection, context_text):
    """context_text: 뉴스/이메일/실적 요약을 사람이 읽을 수 있는 텍스트로 미리 만든 것."""
    data, error = _call(
        connection, "daily_executive_insight", _EXEC_INSIGHT_SYSTEM_PROMPT, context_text,
        "executive_insights", _EXEC_INSIGHT_SCHEMA,
    )
    if error or not data:
        return [], error
    return data.get("insights", []), None
