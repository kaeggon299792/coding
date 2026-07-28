"""회사별 뉴스·공시·규제 신호를 비교 가능한 형태로 조립한다."""

import json
from collections import Counter
from datetime import datetime, timedelta, timezone

from dashboard_db import queries
from services import news_reader


DEFAULT_COMPANIES = [
    {
        "name": "파라다이스",
        "aliases": ["파라다이스", "파라다이스시티", "Paradise City"],
        "dart_corp_code": None,
    },
    {
        "name": "GKL",
        "aliases": ["GKL", "그랜드코리아레저", "세븐럭"],
        "dart_corp_code": None,
    },
    {
        "name": "강원랜드",
        "aliases": ["강원랜드", "하이원"],
        "dart_corp_code": None,
    },
    {
        "name": "롯데관광개발",
        "aliases": ["롯데관광개발", "제주드림타워", "드림타워"],
        "dart_corp_code": None,
    },
]

SIGNAL_KEYWORDS = {
    "leadership": ["대표", "임원", "인사", "조직", "사장", "CEO", "선임", "사임"],
    "investment": ["투자", "시설", "증설", "확장", "리뉴얼", "개장", "복합리조트", "신규"],
    "hiring": ["채용", "공채", "인재", "구인", "일자리"],
    "finance": ["실적", "매출", "영업이익", "순이익", "증자", "배당", "주가", "재무"],
}

STRATEGY_TOPICS = {
    "투자·시설": SIGNAL_KEYWORDS["investment"],
    "인사·조직": SIGNAL_KEYWORDS["leadership"],
    "채용": SIGNAL_KEYWORDS["hiring"],
    "재무·실적": SIGNAL_KEYWORDS["finance"],
    "마케팅·고객": ["마케팅", "프로모션", "고객", "VIP", "관광객", "멤버십"],
    "규제·정책": ["규제", "정책", "법", "허가", "관광진흥법", "카지노업"],
}


def _parse_aliases(raw):
    try:
        value = json.loads(raw or "[]")
    except (TypeError, ValueError):
        value = []
    return [str(item).strip() for item in value if str(item).strip()]


def _company_profiles(connection):
    registered = queries.list_monitored_companies(connection)
    by_name = {item["name"].casefold(): item for item in registered}
    profiles = []
    for default in DEFAULT_COMPANIES:
        row = by_name.get(default["name"].casefold())
        aliases = list(default["aliases"])
        if row:
            aliases.extend(_parse_aliases(row.get("aliases_json")))
        profiles.append(
            {
                "name": default["name"],
                "aliases": list(dict.fromkeys(aliases)),
                "dart_corp_code": (row or {}).get("dart_corp_code"),
            }
        )
    known = {profile["name"].casefold() for profile in profiles}
    for row in registered:
        if row["name"].casefold() in known:
            continue
        profiles.append(
            {
                "name": row["name"],
                "aliases": list(dict.fromkeys([row["name"], *_parse_aliases(row.get("aliases_json"))])),
                "dart_corp_code": row.get("dart_corp_code"),
            }
        )
    return profiles


def _matches_keywords(item, keywords):
    text = " ".join(
        str(item.get(key) or "")
        for key in ("title", "issue_title", "category", "latest_summary", "report_nm", "ai_summary")
    ).casefold()
    return any(keyword.casefold() in text for keyword in keywords)


def _strategy_change(news):
    now = datetime.now(timezone.utc)
    boundary = now - timedelta(days=30)
    current = Counter()
    previous = Counter()
    for item in news:
        raw_date = item.get("published_at") or item.get("collected_at") or ""
        try:
            parsed = datetime.fromisoformat(str(raw_date).replace("Z", "+00:00"))
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=timezone.utc)
        except (TypeError, ValueError):
            parsed = now
        bucket = current if parsed >= boundary else previous
        for topic, keywords in STRATEGY_TOPICS.items():
            if _matches_keywords(item, keywords):
                bucket[topic] += 1
    changes = []
    for topic in STRATEGY_TOPICS:
        delta = current[topic] - previous[topic]
        if delta:
            changes.append({"topic": topic, "current": current[topic], "previous": previous[topic], "delta": delta})
    changes.sort(key=lambda item: (abs(item["delta"]), item["current"]), reverse=True)
    return changes[:3]


def _format_financials(financials):
    labels = {
        "revenue": "매출액",
        "operating_profit": "영업이익",
        "net_income": "당기순이익",
        "assets": "자산",
        "liabilities": "부채",
        "equity": "자본",
    }
    result = []
    for key, label in labels.items():
        value = financials.get(key)
        if value is None:
            continue
        result.append(
            {
                "key": key,
                "label": label,
                "value": value,
                "display": f"{value / 100_000_000:,.0f}억원",
            }
        )
    return result


def build_company_comparison(connection, days=90):
    companies = []
    regulations = queries.list_recent_law_updates(connection, days=days)
    research_by_name = {
        item["company_name"].casefold(): item
        for item in queries.list_company_research(connection)
    }
    for profile in _company_profiles(connection):
        research = research_by_name.get(profile["name"].casefold())
        if research:
            research["financial_metrics"] = _format_financials(research.get("financials") or {})
        news = news_reader.articles_for_aliases(profile["aliases"], days=days, limit=150)
        strategy_history = (
            news
            if days >= 60
            else news_reader.articles_for_aliases(profile["aliases"], days=60, limit=200)
        )
        disclosures = queries.list_disclosures_for_company(
            connection,
            company_name=profile["name"],
            dart_corp_code=profile["dart_corp_code"],
            days=days,
        )
        research_documents = queries.list_research_documents(
            connection, company_name=profile["name"], limit=6
        )
        disclosure_analyses = {
            item["id"]: queries.get_disclosure_analysis(connection, item["id"])
            for item in disclosures
        }
        finance_signals = [item for item in news if _matches_keywords(item, SIGNAL_KEYWORDS["finance"])]
        finance_signals.extend(
            {
                **item,
                "title": item.get("report_nm"),
                "published_at": item.get("rcept_dt"),
                "original_url": item.get("dart_link"),
                "source_kind": "공시",
            }
            for item in disclosures
            if _matches_keywords(
                {**item, "ai_summary": (disclosure_analyses.get(item["id"]) or {}).get("ai_summary")},
                SIGNAL_KEYWORDS["finance"],
            )
        )
        companies.append(
            {
                **profile,
                "research": research,
                "research_documents": research_documents,
                "news": news[:8],
                "disclosures": disclosures[:8],
                "leadership": [item for item in news if _matches_keywords(item, SIGNAL_KEYWORDS["leadership"])][:6],
                "investment": [item for item in news if _matches_keywords(item, SIGNAL_KEYWORDS["investment"])][:6],
                "hiring": [item for item in news if _matches_keywords(item, SIGNAL_KEYWORDS["hiring"])][:6],
                "finance": finance_signals[:6],
                "regulations": regulations[:5],
                "strategy_changes": _strategy_change(strategy_history),
                "counts": {
                    "news": len(news),
                    "disclosures": len(disclosures),
                    "leadership": sum(_matches_keywords(item, SIGNAL_KEYWORDS["leadership"]) for item in news),
                    "investment": sum(_matches_keywords(item, SIGNAL_KEYWORDS["investment"]) for item in news),
                    "hiring": sum(_matches_keywords(item, SIGNAL_KEYWORDS["hiring"]) for item in news),
                    "finance": len(finance_signals),
                    "research_documents": len(research_documents),
                },
            }
        )
    return companies
