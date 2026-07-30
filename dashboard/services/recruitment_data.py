"""카지노 관련 채용공고 수집 및 구조화."""

import hashlib
import html
import re
from html.parser import HTMLParser
from urllib.parse import urljoin

import config
from services import ai_insights
from services.http_utils import get_with_hard_timeout
from utils import now_kst


SEARCH_SOURCES = (
    {
        "name": "잡코리아",
        "url": "https://www.jobkorea.co.kr/Search/",
        "params": {"stext": "카지노"},
        "host": "https://www.jobkorea.co.kr",
        "link_pattern": re.compile(r"/Recruit/GI_Read/\d+", re.I),
    },
    {
        "name": "사람인",
        "url": "https://www.saramin.co.kr/zf_user/search",
        "params": {"searchword": "카지노"},
        "host": "https://www.saramin.co.kr",
        "link_pattern": re.compile(r"/zf_user/jobs/relay/view\?rec_idx=\d+", re.I),
    },
    {
        "name": "인크루트",
        "url": "https://job.incruit.com/jobdb_list/searchjob.asp",
        "params": {"col": "job_all", "kw": "카지노"},
        "host": "https://job.incruit.com",
        "link_pattern": re.compile(r"jobpost\.asp\?job=\d+", re.I),
    },
)


class _LinkParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.links = []

    def handle_starttag(self, tag, attrs):
        if tag.lower() == "a":
            href = dict(attrs).get("href")
            if href:
                self.links.append(href)


def _get(url, **kwargs):
    response = get_with_hard_timeout(
        url,
        hard_timeout_seconds=config.RECRUITMENT_REQUEST_TIMEOUT_SECONDS,
        retry_attempts=2,
        timeout=(5, config.RECRUITMENT_REQUEST_TIMEOUT_SECONDS),
        headers={"User-Agent": "Mozilla/5.0 AppleWebKit/537.36 Chrome/126 Safari/537.36"},
        **kwargs,
    )
    response.raise_for_status()
    response.encoding = response.apparent_encoding or response.encoding
    return response.text


def _plain_text(value):
    value = re.sub(r"<(script|style).*?</\1>", " ", value, flags=re.I | re.S)
    value = re.sub(r"<[^>]+>", " ", value)
    return re.sub(r"\s+", " ", html.unescape(value)).strip()


def _meta(html_text, name):
    match = re.search(
        rf'<meta[^>]+(?:name|property)=["\']{re.escape(name)}["\'][^>]+content=["\']([^"\']+)',
        html_text, re.I,
    )
    if not match:
        match = re.search(
            rf'<meta[^>]+content=["\']([^"\']+)["\'][^>]+(?:name|property)=["\']{re.escape(name)}["\']',
            html_text, re.I,
        )
    return html.unescape(match.group(1)).strip() if match else ""


def _rule_analysis(text):
    employment = "계약직" if re.search(r"계약직|기간제|인턴", text) else (
        "정규직" if "정규직" in text else "미표시"
    )
    compensation_parts = []
    for pattern in (
        r"연봉\s*[0-9,~\-]+\s*만원",
        r"월급\s*[0-9,~\-]+\s*만원",
        r"급여\s*[:：]?\s*[^|·]{2,30}",
    ):
        match = re.search(pattern, text)
        if match:
            compensation_parts.append(match.group(0).strip())
            break
    benefits = [
        keyword for keyword in
        ("성과급", "인센티브", "기숙사", "식사 제공", "교통비", "복지포인트", "퇴직금")
        if keyword in text
    ]
    return {
        "employment_type": employment,
        "compensation_summary": compensation_parts[0] if compensation_parts else "공고 내 명시 없음",
        "benefits_summary": " · ".join(benefits) if benefits else "공고 내 명시 없음",
        "treatment_level": "확인 필요",
        "ai_summary": (
            f"{employment} 채용입니다. 처우는 "
            f"{compensation_parts[0] if compensation_parts else '공고 원문 확인이 필요합니다'}."
        ),
    }


def analyze_with_ai(connection, item):
    data, error = ai_insights._call(
        connection,
        "recruitment_analysis",
        "채용공고만 분석하세요. 없는 처우를 추정하지 말고 명시되지 않았다고 답하세요.",
        (item.get("raw_text") or "")[:12000],
        "recruitment_analysis",
        {
            "type": "object",
            "properties": {
                "employment_type": {"type": "string"},
                "compensation_summary": {"type": "string"},
                "benefits_summary": {"type": "string"},
                "treatment_level": {"type": "string", "enum": ["좋음", "보통", "낮음", "판단불가"]},
                "ai_summary": {"type": "string"},
            },
            "required": ["employment_type", "compensation_summary", "benefits_summary", "treatment_level", "ai_summary"],
            "additionalProperties": False,
        },
    )
    return (data or _rule_analysis(item.get("raw_text") or "")), error


def collect_source(source, limit=15):
    search_html = _get(source["url"], params=source["params"])
    parser = _LinkParser()
    parser.feed(search_html)
    urls = []
    for href in parser.links:
        absolute = urljoin(source["host"], href)
        if source["link_pattern"].search(absolute) and absolute not in urls:
            urls.append(absolute)
        if len(urls) >= limit:
            break
    items, errors = [], []
    timestamp = now_kst().isoformat()
    for url in urls:
        try:
            detail = _get(url)
            title = _meta(detail, "og:title") or _plain_text(
                re.search(r"<title[^>]*>(.*?)</title>", detail, re.I | re.S).group(1)
            )
            description = _meta(detail, "description") or _meta(detail, "og:description")
            raw_text = _plain_text(detail)[:30000]
            identifier = hashlib.sha256(url.encode()).hexdigest()[:24]
            rules = _rule_analysis(raw_text)
            items.append({
                "source_name": source["name"], "source_job_id": identifier,
                "company_name": "", "title": title[:300] or "채용공고",
                "source_url": url, "raw_text": raw_text,
                "posted_at": None, "deadline": None, "location": None,
                "first_seen_at": timestamp, "last_seen_at": timestamp,
                **rules,
            })
        except Exception as error:  # noqa: BLE001
            errors.append(f"{url}: {error}")
    return items, errors


def fetch_all():
    items, errors = [], []
    for source in SEARCH_SOURCES:
        try:
            source_items, source_errors = collect_source(source)
            items.extend(source_items)
            errors.extend(source_errors)
        except Exception as error:  # noqa: BLE001
            errors.append(f"{source['name']}: {error}")
    return {"items": items, "errors": errors}
