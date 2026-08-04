"""Ground overseas-news analysis in Google Search and public article URLs."""

from __future__ import annotations

import json
import ipaddress
import logging
import re
import time
from urllib.parse import urlparse

import requests

import config

logger = logging.getLogger("dashboard")

_API_ROOT = "https://generativelanguage.googleapis.com/v1beta/models"
_JSON_FENCE_RE = re.compile(r"^```(?:json)?\s*|\s*```$", re.IGNORECASE)
_ALLOWED_IMPACTS = {"positive", "negative", "neutral", "mixed"}
_ALLOWED_CATEGORIES = {
    "실적·시장",
    "규제·정책",
    "투자·개발",
    "기업·경영",
    "관광·수요",
    "인사·채용",
    "기타",
}


class GeminiNewsError(RuntimeError):
    """Safe operational error. The API key and response body are never included."""

    def __init__(self, message, usage_records=None):
        super().__init__(message)
        self.usage_records = list(usage_records or [])


def _is_public_web_url(value):
    try:
        parsed = urlparse((value or "").strip())
    except ValueError:
        return False
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        return False
    hostname = parsed.hostname.lower().rstrip(".")
    if hostname in {"localhost", "localhost.localdomain"} or hostname.endswith(".local"):
        return False
    try:
        address = ipaddress.ip_address(hostname)
    except ValueError:
        return True
    return not (address.is_private or address.is_loopback or address.is_link_local)


def _resolve_grounding_citations(citations):
    """Convert Google's citation redirects to publisher URLs without fetching publishers."""
    resolved = []
    for citation in citations:
        url = (citation.get("url") or "").strip()
        title = (citation.get("title") or "").strip()[:240]
        parsed = urlparse(url)
        if parsed.hostname == "vertexaisearch.cloud.google.com":
            try:
                response = requests.get(
                    url,
                    allow_redirects=False,
                    timeout=min(config.GEMINI_REQUEST_TIMEOUT_SECONDS, 20),
                    headers={"User-Agent": "CasinoIN/1.0 (+https://www.casinoin.kr/credits)"},
                )
                location = (response.headers.get("Location") or "").strip()
                if 300 <= response.status_code < 400 and _is_public_web_url(location):
                    url = location
            except requests.RequestException:
                pass
        if not _is_public_web_url(url):
            continue
        item = {"url": url, "title": title}
        if item not in resolved:
            resolved.append(item)
    return resolved[:8]


def _extract_text(payload):
    candidates = payload.get("candidates") or []
    if not candidates:
        return ""
    parts = (candidates[0].get("content") or {}).get("parts") or []
    return "\n".join(part.get("text", "") for part in parts if part.get("text")).strip()


def _parse_json_text(text):
    cleaned = _JSON_FENCE_RE.sub("", (text or "").strip()).strip()
    try:
        value = json.loads(cleaned)
    except json.JSONDecodeError:
        start = cleaned.find("{")
        end = cleaned.rfind("}")
        if start < 0 or end <= start:
            raise GeminiNewsError("Gemini 응답을 구조화된 분석으로 변환하지 못했습니다.")
        try:
            value = json.loads(cleaned[start : end + 1])
        except json.JSONDecodeError as error:
            raise GeminiNewsError("Gemini 응답 JSON 형식이 올바르지 않습니다.") from error
    if not isinstance(value, dict):
        raise GeminiNewsError("Gemini 분석 응답 형식이 올바르지 않습니다.")
    return value


def _metadata(payload):
    candidate = (payload.get("candidates") or [{}])[0]
    url_metadata = candidate.get("urlContextMetadata") or payload.get("urlContextMetadata") or {}
    url_rows = url_metadata.get("urlMetadata") or []
    retrieval_statuses = [
        str(row.get("urlRetrievalStatus") or row.get("retrievalStatus") or "")
        for row in url_rows
    ]
    full_text = any("SUCCESS" in status.upper() for status in retrieval_statuses)

    grounding = candidate.get("groundingMetadata") or {}
    citations = []
    for chunk in grounding.get("groundingChunks") or []:
        web = chunk.get("web") or {}
        uri = (web.get("uri") or "").strip()
        if not _is_public_web_url(uri):
            continue
        citation = {"url": uri, "title": (web.get("title") or "").strip()[:240]}
        if citation not in citations:
            citations.append(citation)
    grounded = bool(citations or grounding.get("webSearchQueries"))
    if full_text:
        basis = "full_text"
    elif grounded:
        basis = "search_grounded"
    else:
        basis = "title_only"
    return basis, retrieval_statuses, citations[:8]


def _usage_record(payload, request_stage):
    """Return billable usage from one successful GenerateContent response.

    Gemini reports thinking tokens separately while its output list price includes
    them, so the billable output count is candidates + thoughts. Search cost is a
    gross list-price estimate; account-wide free allowances are intentionally not
    subtracted because this application cannot see usage from other API clients.
    """
    usage = payload.get("usageMetadata") or {}
    candidate = (payload.get("candidates") or [{}])[0]
    grounding = candidate.get("groundingMetadata") or {}
    queries = {
        str(query).strip()
        for query in (grounding.get("webSearchQueries") or [])
        if str(query).strip()
    }

    def token_count(name):
        try:
            return max(0, int(usage.get(name) or 0))
        except (TypeError, ValueError):
            return 0

    prompt_tokens = token_count("promptTokenCount")
    candidate_tokens = token_count("candidatesTokenCount")
    thought_tokens = token_count("thoughtsTokenCount")
    total_tokens = token_count("totalTokenCount")
    if not total_tokens:
        total_tokens = prompt_tokens + candidate_tokens + thought_tokens
    billable_output_tokens = candidate_tokens + thought_tokens
    input_cost_usd = (
        prompt_tokens / 1_000_000 * config.GEMINI_INPUT_COST_PER_1M_USD
    )
    output_cost_usd = (
        billable_output_tokens / 1_000_000 * config.GEMINI_OUTPUT_COST_PER_1M_USD
    )
    search_cost_usd = (
        len(queries) / 1_000 * config.GEMINI_SEARCH_COST_PER_1000_USD
    )
    return {
        "request_stage": request_stage,
        "model": config.GEMINI_MODEL,
        "input_tokens": prompt_tokens,
        "output_tokens": candidate_tokens,
        "thought_tokens": thought_tokens,
        "total_tokens": total_tokens,
        "search_query_count": len(queries),
        "input_cost_usd": input_cost_usd,
        "output_cost_usd": output_cost_usd,
        "search_cost_usd": search_cost_usd,
        "estimated_cost_usd": input_cost_usd + output_cost_usd + search_cost_usd,
    }


def _normalize_result(raw, payload, article):
    basis, retrieval_statuses, citations = _metadata(payload)
    impact = str(raw.get("impact_direction") or "neutral").strip().lower()
    if impact not in _ALLOWED_IMPACTS:
        impact = "neutral"
    category = str(raw.get("category") or "기타").strip()
    if category not in _ALLOWED_CATEGORIES:
        category = "기타"
    try:
        importance = max(0, min(int(raw.get("importance_score") or 0), 100))
    except (TypeError, ValueError):
        importance = 0
    canonical_url = str(raw.get("canonical_url") or "").strip()
    if not _is_public_web_url(canonical_url):
        canonical_url = article.get("original_url", "")
    return {
        "title_ko": str(raw.get("title_ko") or article.get("original_title") or "").strip()[:500],
        "summary_ko": str(raw.get("summary_ko") or "").strip()[:3000],
        "category": category,
        "impact_direction": impact,
        "importance_score": importance,
        "ai_analysis": str(raw.get("ai_analysis") or "").strip()[:5000],
        "canonical_url": canonical_url,
        "analysis_basis": basis,
        "retrieval_status": ",".join(retrieval_statuses)[:500] or None,
        "source_citations_json": json.dumps(citations, ensure_ascii=False),
        "gemini_model": config.GEMINI_MODEL,
    }


def analyze_article(article, _support_urls=None, _allow_retry=True):
    """Analyze one article without storing or reproducing its copyrighted body."""
    if not config.GEMINI_API_KEY:
        raise GeminiNewsError("GEMINI_API_KEY가 설정되지 않았습니다.")
    source_url = (article.get("original_url") or "").strip()
    if not _is_public_web_url(source_url):
        raise GeminiNewsError("분석할 기사 URL이 올바르지 않습니다.")

    support_urls = [url for url in (_support_urls or []) if _is_public_web_url(url)][:8]
    support_block = "\n".join(f"- {url}" for url in support_urls) or "- none"
    prompt = f"""
You are a Korean casino-industry intelligence analyst. Verify and analyze the
news article below using BOTH URL Context and Google Search. Read the public
article body when accessible, and use search grounding to confirm the publisher,
date, and material facts. Do not invent facts. Do not reproduce the article.
If the page is paywalled, login-only, blocked, or unavailable, use only facts
supported by Google Search and keep the analysis conservative.

Region: {article.get('region', '')}
Publisher: {article.get('publisher', '')}
Original title: {article.get('original_title', '')}
Candidate URL: {source_url}
RSS snippet: {article.get('original_summary', '')}
Supporting publisher URLs found by the first grounded search:
{support_block}

Return ONLY one JSON object with these fields:
- canonical_url: direct publisher article URL when verifiable, otherwise candidate URL
- title_ko: natural Korean translation of the headline
- summary_ko: 2-4 Korean sentences summarizing verified article facts
- category: exactly one of 실적·시장, 규제·정책, 투자·개발, 기업·경영, 관광·수요, 인사·채용, 기타
- impact_direction: exactly one of positive, negative, neutral, mixed
- importance_score: integer 0-100 for casino-industry professionals
- ai_analysis: 2-4 Korean sentences explaining the industry impact, uncertainty,
  and what should be monitored next. Never use confidential internal performance data.
""".strip()
    # The first pass discovers corroborating publisher URLs with Google Search.
    # On the second pass, URL Context alone forces Gemini to read those URLs
    # instead of satisfying the prompt from search snippets again.
    tools = [{"url_context": {}}] if support_urls else [
        {"google_search": {}}, {"url_context": {}}
    ]
    body = {
        "contents": [{"role": "user", "parts": [{"text": prompt}]}],
        "tools": tools,
        "generationConfig": {
            "temperature": 0.1,
            "responseMimeType": "application/json",
            "responseSchema": {
                "type": "OBJECT",
                "properties": {
                    "canonical_url": {"type": "STRING"},
                    "title_ko": {"type": "STRING"},
                    "summary_ko": {"type": "STRING"},
                    "category": {"type": "STRING"},
                    "impact_direction": {"type": "STRING"},
                    "importance_score": {"type": "INTEGER"},
                    "ai_analysis": {"type": "STRING"},
                },
                "required": [
                    "canonical_url", "title_ko", "summary_ko", "category",
                    "impact_direction", "importance_score", "ai_analysis",
                ],
            },
        },
    }
    url = f"{_API_ROOT}/{config.GEMINI_MODEL}:generateContent"
    last_error = None
    for attempt in range(max(1, config.GEMINI_MAX_RETRIES + 1)):
        try:
            response = requests.post(
                url,
                headers={
                    "x-goog-api-key": config.GEMINI_API_KEY,
                    "Content-Type": "application/json",
                },
                json=body,
                timeout=config.GEMINI_REQUEST_TIMEOUT_SECONDS,
            )
        except requests.RequestException as error:
            last_error = f"네트워크 오류({type(error).__name__})"
        else:
            if response.ok:
                payload = response.json()
                current_usage = _usage_record(
                    payload,
                    "url_context_retry" if support_urls else "grounded_search",
                )
                try:
                    raw = _parse_json_text(_extract_text(payload))
                    result = _normalize_result(raw, payload, article)
                except GeminiNewsError as error:
                    error.usage_records.insert(0, current_usage)
                    raise
                result["gemini_usage_records"] = [current_usage]
                try:
                    citations = json.loads(result["source_citations_json"] or "[]")
                except (TypeError, ValueError, json.JSONDecodeError):
                    citations = []
                citations = _resolve_grounding_citations(citations)
                result["source_citations_json"] = json.dumps(citations, ensure_ascii=False)
                direct_urls = [
                    item["url"] for item in citations
                    if urlparse(item["url"]).hostname != "vertexaisearch.cloud.google.com"
                ]
                if result["analysis_basis"] != "full_text" and _allow_retry and direct_urls:
                    retry_article = dict(article)
                    retry_article["original_url"] = direct_urls[0]
                    try:
                        retry = analyze_article(
                            retry_article,
                            _support_urls=direct_urls,
                            _allow_retry=False,
                        )
                    except GeminiNewsError as error:
                        result["gemini_usage_records"].extend(error.usage_records)
                        result["canonical_url"] = direct_urls[0]
                        return result
                    retry["gemini_usage_records"] = (
                        result.get("gemini_usage_records", [])
                        + retry.get("gemini_usage_records", [])
                    )
                    retry_citations = json.loads(retry.get("source_citations_json") or "[]")
                    merged = []
                    for item in retry_citations + citations:
                        if item not in merged:
                            merged.append(item)
                    retry["source_citations_json"] = json.dumps(merged[:8], ensure_ascii=False)
                    if not _is_public_web_url(retry.get("canonical_url")):
                        retry["canonical_url"] = direct_urls[0]
                    return retry
                return result
            try:
                error_status = (response.json().get("error") or {}).get("status") or "API_ERROR"
            except (ValueError, AttributeError):
                error_status = "API_ERROR"
            if response.status_code == 429:
                raise GeminiNewsError(f"Gemini 사용량 또는 결제 한도 초과({error_status})")
            if 400 <= response.status_code < 500:
                raise GeminiNewsError(f"Gemini 요청 거절({error_status})")
            last_error = f"Gemini 서버 오류({response.status_code})"
        if attempt < config.GEMINI_MAX_RETRIES:
            time.sleep(min(2 ** attempt, 4))
    raise GeminiNewsError(last_error or "Gemini 분석 요청에 실패했습니다.")
