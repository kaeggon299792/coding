"""Versioned CASINOINBOT policy for concise casino-news alerts."""

from __future__ import annotations

import html
import logging
import re

from extensions import dashboard_db
from services import member_telegram, telegram_alert

logger = logging.getLogger("dashboard")


DETAIL_SYSTEM_PROMPT = """\
당신은 카지노·관광산업 경영기획 담당자를 위한 뉴스 알림 분석 AI입니다.
워커힐 카지노와 파라다이스 경영진이 30초 안에 판단할 수 있도록 분석합니다.

반드시 지켜야 할 규칙:
1. 기사 또는 공식자료로 확인된 사실만 evidence에 작성하고 최대 2개로 제한합니다.
2. summary는 가장 중요한 변화·수치·진행 단계·확정 여부를 한 문장으로 작성합니다.
3. company_impact는 파라다이스 또는 워커힐 카지노의 실적·비용·고객·규제·경쟁
   영향만 최대 두 문장으로 작성합니다. 직접 근거가 없으면 반드시 가능성·전망·추정으로
   표시하며, 근거 없는 재무 금액을 계산하지 않습니다.
4. follow_up_items는 실제로 추가 확인할 사항만 최대 2개로 제한합니다.
5. 적용 기준, 시행일 또는 법안 확정 여부가 불명확하면 반드시 '미확정'이라고 씁니다.
6. 같은 의미를 반복하거나 기사 전체를 순서대로 요약하지 않습니다.
7. importance는 매출·이익·기금·세금·면허·규제·대규모 투자·주요 경쟁사 전략에
   직접 영향을 주면 high, 부분적 영업·시장 영향이면 medium, 참고성이면 low입니다.
8. executive_report_required는 importance가 high인 경우에만 true로 설정합니다.
9. inferences에는 company_impact와 중복되지 않는 필수 추정만 최대 1개를 넣습니다.
10. 각 문장은 가급적 50자 안팎으로 간결하게 작성합니다.
11. 최종 알림은 앱이 700~1,000자, 최대 15줄의 모바일 형식으로 조립합니다.
12. 설명을 덧붙이지 말고 지정된 JSON 스키마 형식으로만 응답합니다.
"""


IMPORTANCE_LABELS = {"high": "높음", "medium": "보통", "low": "낮음"}
IMPACT_LABELS = {
    "positive": "긍정",
    "negative": "부정",
    "neutral": "중립",
    "mixed": "혼재",
}


def _sentences(value, limit):
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    if not text:
        return []
    parts = [part.strip() for part in re.split(r"(?<=[.!?。])\s+", text) if part.strip()]
    return (parts or [text])[:limit]


def build_issue_lines(issue_title, detail_result, articles, escape_html):
    """Return at most 15 non-empty lines in the approved mobile-alert format."""
    first_article = articles[0] if articles else None
    title = getattr(first_article, "title", "원문 확인")
    url = getattr(first_article, "original_url", "")
    importance = getattr(detail_result, "importance", "low")
    impact = getattr(detail_result, "impact_direction", "neutral")

    lines = [
        f"📌 {escape_html(issue_title)}",
        (
            f"중요도: {IMPORTANCE_LABELS.get(importance, importance)} | "
            f"영향: {IMPACT_LABELS.get(impact, impact)}"
        ),
        "핵심",
    ]
    summary = _sentences(getattr(detail_result, "summary", ""), 1)
    evidence = list(getattr(detail_result, "evidence", None) or [])[:2]
    for item in (summary + evidence)[:3]:
        lines.append(f"• {escape_html(item)}")

    lines.append("당사 영향")
    company_impact = _sentences(getattr(detail_result, "company_impact", ""), 2)
    if len(company_impact) < 2:
        for item in list(getattr(detail_result, "inferences", None) or []):
            company_impact.append(f"추정: {item}")
            if len(company_impact) == 2:
                break
    for item in company_impact[:2]:
        lines.append(f"• {escape_html(item)}")

    lines.append("확인 필요")
    for item in list(getattr(detail_result, "follow_up_items", None) or [])[:2]:
        lines.append(f"• {escape_html(item)}")

    lines.extend((f"기사: {escape_html(title)}", escape_html(url)))
    if importance == "high":
        lines.append("⚠️ 경영진 보고 검토 필요")
    return lines[:15]


def apply_news_alert_policy(openai_analyzer, telegram_sender):
    """Apply this versioned policy to the legacy worker loaded by CASINOINBOT."""
    openai_analyzer.DETAIL_SYSTEM_PROMPT = DETAIL_SYSTEM_PROMPT

    def build_issue_message(issue_title, detail_result, articles, is_update=False):
        del is_update
        return "\n".join(
            build_issue_lines(
                issue_title,
                detail_result,
                articles,
                telegram_sender.escape_html,
            )
        )

    telegram_sender.build_issue_message = build_issue_message

    def send_issue_notifications(entries):
        """Deliver casino-news issues through the member assistant bot only."""
        if not entries:
            return []
        connection = dashboard_db()
        delivered = []
        try:
            for entry in entries:
                message = build_issue_message(
                    entry["issue_title"], entry["detail_result"],
                    entry["articles"], entry.get("is_update", False),
                )
                result = member_telegram.broadcast(
                    connection, "news", html.unescape(message)
                )
                # With no subscribers there is nothing to retry. When subscribers
                # exist, retain the legacy retry behavior only if every send failed.
                if result["recipients"] == 0 or result["sent"] > 0:
                    delivered.append(entry)
        finally:
            connection.close()
        return delivered

    telegram_sender.send_issue_notifications = send_issue_notifications

    def send_daily_limit_notice(reason):
        """Route the news-watcher's own daily GPT-limit notice to the admin bot."""
        message = telegram_sender.build_daily_limit_message(reason)
        try:
            telegram_alert.send_alert(message)
        except Exception:
            logger.exception("일일 GPT 한도 알림 전송 실패")

    telegram_sender.send_daily_limit_notice = send_daily_limit_notice

    def send_error_alert(stage, error_message, retry_result="재시도 없음", needs_user_check=True):
        """Route the news-watcher's own fatal-error notice to the admin bot."""
        message = telegram_sender.build_error_alert_message(
            stage,
            error_message,
            telegram_sender.now_kst().strftime("%Y-%m-%d %H:%M:%S"),
            retry_result,
            needs_user_check,
        )
        try:
            telegram_alert.send_alert(message)
        except Exception:
            logger.exception("뉴스워처 오류 알림 전송 실패")

    telegram_sender.send_error_alert = send_error_alert
