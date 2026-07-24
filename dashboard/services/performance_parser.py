"""
텔레그램으로 수신되는 데이터랩 실적 알림 메시지를 파싱한다.

이 파서는 로컬 PC의 datalab_capture.py(build_datalab_body/build_no_change_message)가
만드는 메시지 형식을 그대로 역으로 인식하도록 맞춰져 있다. 형식이 바뀌면
안전하게 parsing_status='failed'로 원문을 그대로 보존하고, 절대 존재하지 않는
지표를 임의로 만들어내지 않는다.

인식하는 헤더 4종:
  🚨 데이터랩 매출 큰 폭 변동          -> header_type = "big_change"
  📊 데이터랩 주요지표 요약             -> header_type = "summary"
  📊 데이터랩 주요지표: 이전과 변화없음   -> header_type = "no_change"
  📊 데이터랩 주요지표 (위 3개와 불일치)  -> header_type = "capture_failed"
                                          (로컬 스크립트가 수치 추출에 실패한 경우)
"""

import re
from dataclasses import dataclass, field
from typing import Optional

_HEADER_PATTERNS = (
    ("big_change", re.compile(r"^🚨\s*데이터랩\s*매출\s*큰\s*폭\s*변동")),
    ("no_change", re.compile(r"^📊\s*데이터랩\s*주요지표\s*:\s*이전과\s*변화없음")),
    ("summary", re.compile(r"^📊\s*데이터랩\s*주요지표\s*요약")),
    # 위 세 패턴에 안 걸리지만 "데이터랩 주요지표"로 시작하면 캡처 실패 케이스로 본다.
    ("capture_failed", re.compile(r"^📊\s*데이터랩\s*주요지표")),
)

_CAPTURED_AT_RE = re.compile(r"(\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2})\s*기준")
_GROUP_TODAY_RE = re.compile(r"그룹\s*매출\s*:\s*(-?[\d,]+백만원)\s*\(전일\s*대비\s*(-?\d+(?:\.\d+)?%)\)")
_GROUP_YESTERDAY_RE = re.compile(r"전일\s*:\s*(-?[\d,]+백만원)")
_CASINO_RE = re.compile(r"카지노\s*:\s*(-?[\d,]+백만원)")
_HOTEL_RE = re.compile(r"호텔\s*&\s*리조트\s*:\s*(-?[\d,]+백만원)")
_WALKERHILL_RE = re.compile(r"워커힐\s*:\s*(-?[\d,]+백만원)")


@dataclass
class ParsedPerformanceMessage:
    header_type: str
    captured_at_text: Optional[str] = None
    fields: dict = field(default_factory=dict)


def detect_header_type(text: str) -> Optional[str]:
    """데이터랩 실적 메시지인지 먼저 판별한다. 아니면 None(=이 파서의 대상이 아님)."""
    if not text:
        return None
    stripped = text.strip()
    for header_type, pattern in _HEADER_PATTERNS:
        if pattern.match(stripped):
            return header_type
    return None


def parse(text: str) -> tuple[Optional[ParsedPerformanceMessage], Optional[str]]:
    """(파싱결과, 오류사유) 튜플을 반환한다.

    header_type을 인식하지 못하면 (None, None) — 이 메시지는 데이터랩 실적
    메시지가 아니라는 뜻이므로 호출측에서 아예 저장하지 않아야 한다.
    header는 인식했지만 본문 추출에 실패하면 (None, "사유")를 반환한다.
    """
    header_type = detect_header_type(text)
    if header_type is None:
        return None, None

    captured_match = _CAPTURED_AT_RE.search(text)
    captured_at_text = captured_match.group(1) if captured_match else None

    fields = {}

    group_match = _GROUP_TODAY_RE.search(text)
    if group_match:
        fields["group_sales_today"] = group_match.group(1)
        fields["change_percent"] = group_match.group(2)

    yesterday_match = _GROUP_YESTERDAY_RE.search(text)
    if yesterday_match:
        fields["group_sales_yesterday"] = yesterday_match.group(1)

    casino_match = _CASINO_RE.search(text)
    if casino_match:
        fields["casino_sales"] = casino_match.group(1)

    hotel_match = _HOTEL_RE.search(text)
    if hotel_match:
        fields["hotel_resort_sales"] = hotel_match.group(1)

    walkerhill_match = _WALKERHILL_RE.search(text)
    if walkerhill_match:
        fields["walkerhill_sales"] = walkerhill_match.group(1)

    if header_type == "capture_failed":
        # 로컬 스크립트 자체가 수치를 못 뽑은 경우 - 우리도 지표가 없는 게 정상이다.
        return ParsedPerformanceMessage(header_type, captured_at_text, fields), None

    if not fields:
        return None, (
            f"헤더는 '{header_type}'로 인식했지만 본문에서 지표를 하나도 추출하지 "
            "못했습니다(메시지 형식이 바뀌었을 수 있음)."
        )

    return ParsedPerformanceMessage(header_type, captured_at_text, fields), None
