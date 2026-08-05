"""회사별 뉴스·공시·규제 신호를 비교 가능한 형태로 조립한다."""

import json
import re
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
    {
        "name": "인스파이어",
        "aliases": ["인스파이어", "인스파이어 리조트", "인스파이어인티그레이티드리조트"],
        "dart_corp_code": "01144125",
    },
    {
        "name": "파라다이스세가사미",
        "aliases": ["파라다이스세가사미", "파라다이스 시티", "Paradise Segasammy"],
        "dart_corp_code": None,
    },
]

SIGNAL_KEYWORDS = {
    "leadership": ["대표", "임원", "인사", "조직", "사장", "CEO", "선임", "사임"],
    "investment": ["투자", "시설", "증설", "확장", "리뉴얼", "개장", "복합리조트", "신규"],
    "hiring": ["채용", "공채", "인재", "구인", "일자리"],
    "finance": ["실적", "매출", "영업이익", "순이익", "증자", "배당", "주가", "재무"],
}

COMPANY_NEWS_CATEGORY_LABELS = {
    "management": "경영·인사",
    "investment": "투자·시설",
    "finance": "재무·실적",
    "hiring": "채용",
    "other": "기타",
}

COMPANY_DISPLAY_NAMES_EN = {
    "파라다이스": "Paradise Co., Ltd.",
    "GKL": "Grand Korea Leisure (GKL)",
    "강원랜드": "Kangwon Land",
    "롯데관광개발": "Lotte Tour Development",
    "인스파이어": "INSPIRE Entertainment Resort",
    "파라다이스세가사미": "Paradise Segasammy Co., Ltd.",
}

COMPANY_ALIAS_NAMES_EN = {
    "파라다이스": "Paradise",
    "파라다이스시티": "Paradise City",
    "그랜드코리아레저": "Grand Korea Leisure",
    "세븐럭": "Seven Luck",
    "강원랜드": "Kangwon Land",
    "하이원": "High1 Resort",
    "롯데관광개발": "Lotte Tour Development",
    "제주드림타워": "Jeju Dream Tower",
    "드림타워": "Dream Tower",
    "인스파이어": "INSPIRE Entertainment Resort",
    "인스파이어 리조트": "INSPIRE Entertainment Resort",
    "인스파이어인티그레이티드리조트": "INSPIRE Integrated Resort",
    "파라다이스세가사미": "Paradise Segasammy",
    "파라다이스 시티": "Paradise City",
}


_COMPANY_SLUG_RE = re.compile(r"[^0-9a-z가-힣]+", re.IGNORECASE)


def _company_slug(name):
    normalized = _COMPANY_SLUG_RE.sub("-", str(name).strip().casefold())
    normalized = normalized.strip("-")
    return normalized or "company"


def _with_company_slug(profile):
    item = dict(profile)
    item["slug"] = _company_slug(profile["name"])
    return item


def _find_profile_by_slug(profiles, company_slug):
    normalized = str(company_slug).strip().casefold()
    for profile in profiles:
        if _company_slug(profile["name"]) == normalized:
            return profile
        for alias in profile.get("aliases", []):
            if _company_slug(alias) == normalized:
                return profile
    return None


def company_display_name(name, locale="ko"):
    """Return an English display label without changing the stored filter key."""

    if locale != "en":
        return name
    return COMPANY_DISPLAY_NAMES_EN.get(name, name)


def company_display_aliases(aliases, locale="ko"):
    """Translate known public brand aliases while preserving unknown names."""

    if locale != "en":
        return aliases
    translated = [COMPANY_ALIAS_NAMES_EN.get(alias, alias) for alias in aliases]
    return list(dict.fromkeys(translated))

_COMPANY_NEWS_AI_CATEGORY_TERMS = {
    "management": ("경영", "인사", "조직", "리더십", "대표", "임원"),
    "investment": ("투자", "시설", "증설", "확장", "리뉴얼", "개장", "복합리조트"),
    "finance": ("재무", "실적", "매출", "영업이익", "순이익", "배당", "증자", "주가"),
    "hiring": ("채용", "공채", "인재", "구인", "일자리"),
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
        profiles.append(_with_company_slug({
            "name": default["name"],
            "aliases": list(dict.fromkeys(aliases)),
            "dart_corp_code": (
                row.get("dart_corp_code") if row and row.get("dart_corp_code")
                else default.get("dart_corp_code")
            ),
        }))
    known = {profile["name"].casefold() for profile in profiles}
    for row in registered:
        if row["name"].casefold() in known:
            continue
        profiles.append(_with_company_slug({
            "name": row["name"],
            "aliases": list(dict.fromkeys([row["name"], *_parse_aliases(row.get("aliases_json"))])),
            "dart_corp_code": row.get("dart_corp_code"),
        }))
    return profiles


def list_company_options(connection):
    """Return canonical company names and slugs for company-scoped editors."""
    return _company_profiles(connection)


def get_company_profile_by_slug(connection, company_slug):
    return _find_profile_by_slug(_company_profiles(connection), str(company_slug or ""))


def _format_currency(value):
    try:
        number = float(value)
    except (TypeError, ValueError):
        return str(value or "")
    if number >= 0:
        return f"{number:,.0f}"
    return f"{number:,.0f}"


def _normalize_financial_sections(financials):
    if not isinstance(financials, dict):
        return []

    section_alias = {
        "income_statement": "손익계산서",
        "손익계산서": "손익계산서",
        "income": "손익계산서",
        "cash_flow": "현금흐름표",
        "현금흐름표": "현금흐름표",
        "cashflow": "현금흐름표",
        "balance_sheet": "재무상태표",
        "재무상태표": "재무상태표",
        "statement_of_financial_position": "재무상태표",
        "credit": "신용정보",
    }

    sections = []
    for key, source_title in section_alias.items():
        if key not in financials:
            continue
        value = financials[key]
        if isinstance(value, dict):
            rows = []
            for item_key, item_value in value.items():
                display = _format_currency(item_value)
                if display:
                    rows.append({
                        "label": str(item_key).replace("_", " "),
                        "value": item_value,
                        "display": f"{display} 억원",
                    })
            if rows:
                sections.append({"title": source_title, "rows": rows})
        elif isinstance(value, list):
            for item in value:
                if not isinstance(item, dict):
                    continue
                title = str(item.get("period") or item.get("year") or "")
                row_values = [
                    {
                        "label": str(row_key).replace("_", " "),
                        "value": row_value,
                        "display": f"{_format_currency(row_value)} 억원",
                    }
                    for row_key, row_value in item.items()
                    if row_key not in {"period", "as_of", "year"}
                ]
                if row_values:
                    sections.append({
                        "title": f"{source_title} ({title})" if title else source_title,
                        "rows": row_values,
                    })
    return sections


_FINANCIAL_STATEMENT_TITLES = {
    "income_statement": ("손익계산서", "Income statement"),
    "balance_sheet": ("재무상태표", "Statement of financial position"),
    "cash_flow": ("현금흐름표", "Cash flow statement"),
}


def _format_financial_amount(amount):
    """원 단위 저장값을 화면용 억원 문자열로 바꾼다."""

    if amount is None:
        return "-"
    value = int(amount) / 100_000_000
    if value == int(value):
        return f"{value:,.0f}"
    return f"{value:,.1f}"


def _build_company_financial_statements(connection, company_name, period_limit=5):
    statements = []
    reports = queries.list_latest_company_financial_reports(connection, company_name)
    values_by_report = {}
    for source_row in queries.list_company_financial_values_for_reports(
        connection, (report["id"] for report in reports)
    ):
        values_by_report.setdefault(source_row["report_id"], []).append(source_row)
    for report in reports:
        all_rows = values_by_report.get(report["id"], [])
        periods = sorted({row["fiscal_date"] for row in all_rows})[-period_limit:]
        selected_periods = set(periods)
        source_rows = [
            row for row in all_rows if row["fiscal_date"] in selected_periods
        ]
        grouped = {}
        for source_row in source_rows:
            row = grouped.setdefault(
                source_row["display_order"],
                {
                    "account_code": source_row["account_code"],
                    "label": source_row["account_name"],
                    "amounts": {},
                },
            )
            row["amounts"][source_row["fiscal_date"]] = {
                "raw": source_row["amount"],
                "display": _format_financial_amount(source_row["amount"]),
            }
        titles = _FINANCIAL_STATEMENT_TITLES.get(
            report["statement_type"], (report["statement_type"], report["statement_type"])
        )
        statements.append({
            **report,
            "title": titles[0],
            "title_en": titles[1],
            "periods": periods,
            "period_labels": {
                period: period[:7].replace("-", ".") for period in periods
            },
            "rows": list(grouped.values()),
        })
    return statements


def _latest_five_years(rows):
    """Keep the latest rating year and the preceding four calendar years."""
    if not rows:
        return []
    try:
        latest_year = int(str(rows[0].get("evaluated_on") or "")[:4])
    except (TypeError, ValueError):
        return rows
    earliest_year = latest_year - 4
    return [
        row for row in rows
        if str(row.get("evaluated_on") or "")[:4].isdigit()
        and int(str(row["evaluated_on"])[:4]) >= earliest_year
    ]


def build_company_detail_context(connection, company_name):
    profile = get_company_profile_by_slug(connection, company_name)
    if not profile:
        return None
    research = next(
        (
            item
            for item in queries.list_company_research(connection)
            if item["company_name"].casefold() == profile["name"].casefold()
        ),
        None,
    )
    disclosures = queries.list_disclosures_for_company(
        connection, company_name=profile["name"], dart_corp_code=profile["dart_corp_code"], days=365
    )
    disclosure_analyses = queries.list_latest_disclosure_analyses(
        connection, (item["id"] for item in disclosures)
    )
    for item in disclosures:
        analysis = disclosure_analyses.get(item["id"])
        item["analysis"] = analysis or {}
    news = news_reader.articles_for_aliases(profile["aliases"], days=365, limit=60)
    news_items = sorted(
        news,
        key=lambda item: (
            item.get("published_at") or item.get("collected_at") or "0"
        ),
        reverse=True,
    )[:20]
    research_documents = queries.list_research_documents(
        connection, company_name=profile["name"], limit=12
    )
    ir_documents = queries.list_research_documents(
        connection,
        company_name=profile["name"],
        limit=100,
        document_type="ir",
    )
    company_filings = [
        {
            "source_type": "dart",
            "title": item.get("report_nm") or "-",
            "date": item.get("rcept_dt") or "",
            "sort_date": "".join(
                character
                for character in str(item.get("rcept_dt") or "")
                if character.isdigit()
            )[:8],
            "corp_name": item.get("corp_name") or profile["name"],
            "publisher": item.get("flr_nm") or "",
            "dart_link": item.get("dart_link") or "",
            "document_id": None,
        }
        for item in disclosures
    ]
    company_filings.extend(
        {
            "source_type": "ir",
            "title": item.get("title") or item.get("original_filename") or "-",
            "date": item.get("report_date") or str(item.get("created_at") or "")[:10],
            "sort_date": "".join(
                character
                for character in str(
                    item.get("report_date") or item.get("created_at") or ""
                )
                if character.isdigit()
            )[:8],
            "corp_name": profile["name"],
            "publisher": item.get("publisher") or "",
            "dart_link": "",
            "document_id": item.get("id"),
        }
        for item in ir_documents
    )
    company_filings.sort(
        key=lambda item: (item["sort_date"], item["source_type"] == "ir"),
        reverse=True,
    )

    financial_sections = _normalize_financial_sections(research.get("financials", {}) if research else {})
    financial_statements = _build_company_financial_statements(
        connection, profile["name"]
    )
    credit_ratings = queries.list_company_credit_ratings(
        connection, profile["name"]
    )
    latest_credit_rating = credit_ratings[0] if credit_ratings else None
    credit_ratings = _latest_five_years(credit_ratings)
    executive_profiles = queries.list_latest_company_executive_profiles(
        connection, profile["name"]
    )
    credit_data = None
    if research:
        credit_data = research.get("credit")
        if credit_data is None:
            credit_data = research.get("financials", {}).get("credit")
    return {
        "company": profile,
        "research": research,
        "disclosures": disclosures,
        "company_filings": company_filings,
        "news": news_items,
        "research_documents": research_documents,
        "financial_sections": financial_sections,
        "financial_statements": financial_statements,
        "credit_data": credit_data,
        "credit_rating": latest_credit_rating,
        "credit_ratings": credit_ratings,
        "executive_profiles": executive_profiles,
    }


def _matches_keywords(item, keywords):
    text = " ".join(
        str(item.get(key) or "")
        for key in ("title", "issue_title", "category", "latest_summary", "report_nm", "ai_summary")
    ).casefold()
    return any(keyword.casefold() in text for keyword in keywords)


def _classify_company_news(item):
    """Prefer the stored AI issue category, then fall back to article text."""

    ai_category = str(item.get("category") or "").casefold()
    for code, terms in _COMPANY_NEWS_AI_CATEGORY_TERMS.items():
        if any(term.casefold() in ai_category for term in terms):
            return code
    for code in ("management", "investment", "finance", "hiring"):
        signal_code = "leadership" if code == "management" else code
        if _matches_keywords(item, SIGNAL_KEYWORDS[signal_code]):
            return code
    return "other"


def _decorate_company_news(item):
    try:
        importance_score = float(item.get("importance_score") or 0)
    except (TypeError, ValueError):
        importance_score = 0
    importance = str(item.get("importance") or "").strip().casefold()
    impact = str(item.get("impact_direction") or "").strip().casefold()
    impact_aliases = {
        "positive": "positive", "긍정": "positive",
        "negative": "negative", "부정": "negative",
        "mixed": "mixed", "혼재": "mixed", "중립": "neutral",
        "neutral": "neutral",
    }
    item["importance_score"] = importance_score
    item["is_important"] = (
        importance_score >= 60
        or importance in {"high", "critical", "높음", "매우 높음"}
    )
    item["is_analyzed"] = bool(str(item.get("latest_summary") or "").strip())
    item["impact_code"] = impact_aliases.get(impact, "neutral")
    return item


def build_company_news_dashboard(connection, days=90):
    """Return article-only company news without the comparison-page 8-item cap."""

    dashboard = []
    for profile in _company_profiles(connection):
        rows = news_reader.articles_for_aliases(
            profile["aliases"], days=days, limit=300
        )
        seen = set()
        articles = []
        for raw in rows:
            item = dict(raw)
            identity = (
                item.get("article_id")
                or item.get("original_url")
                or item.get("title")
            )
            if identity in seen:
                continue
            seen.add(identity)
            code = _classify_company_news(item)
            item["company_name"] = profile["name"]
            item["category_code"] = code
            item["category_label"] = COMPANY_NEWS_CATEGORY_LABELS[code]
            articles.append(_decorate_company_news(item))
        counts = {
            code: sum(item["category_code"] == code for item in articles)
            for code in COMPANY_NEWS_CATEGORY_LABELS
        }
        dashboard.append({**profile, "articles": articles, "counts": counts})
    return dashboard


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


def _assign_recruitment_jobs(profiles, jobs):
    """Assign each active job to the strongest matching company alias."""

    assigned = {profile["name"]: [] for profile in profiles}
    for job in jobs:
        haystack = " ".join(
            str(job.get(key) or "")
            for key in ("company_name", "title", "raw_text", "ai_summary")
        ).casefold()
        best_name = None
        best_length = 0
        for profile in profiles:
            for alias in profile.get("aliases", []):
                candidate = str(alias or "").strip().casefold()
                if candidate and candidate in haystack and len(candidate) > best_length:
                    best_name = profile["name"]
                    best_length = len(candidate)
        if best_name:
            assigned[best_name].append(job)
    return assigned


def _market_quote_for_company(profile, research, market_quotes):
    stock_code = str((research or {}).get("stock_code") or "").strip().casefold()
    aliases = {
        str(value or "").strip().casefold()
        for value in [profile.get("name"), *profile.get("aliases", [])]
        if str(value or "").strip()
    }
    for quote in market_quotes:
        if stock_code and str(quote.get("symbol") or "").strip().casefold() == stock_code:
            return quote
        if str(quote.get("name") or "").strip().casefold() in aliases:
            return quote
    return None


def build_company_comparison(connection, days=90):
    companies = []
    regulations = queries.list_recent_law_updates(connection, days=days)
    profiles = _company_profiles(connection)
    market_quotes = queries.list_market_quotes(connection)
    recruitment_by_company = _assign_recruitment_jobs(
        profiles, queries.list_recruitment_jobs(connection, limit=1000)
    )
    research_by_name = {
        item["company_name"].casefold(): item
        for item in queries.list_company_research(connection)
    }
    for profile in profiles:
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
        company_jobs = recruitment_by_company.get(profile["name"], [])
        financial_statements = _build_company_financial_statements(
            connection, profile["name"], period_limit=2
        )
        market_quote = _market_quote_for_company(profile, research, market_quotes)
        companies.append(
            {
                **profile,
                "credit_rating": queries.get_latest_company_credit_rating(
                    connection, profile["name"]
                ),
                "research": research,
                "research_documents": research_documents,
                "news": news[:8],
                "disclosures": disclosures[:8],
                "leadership": [item for item in news if _matches_keywords(item, SIGNAL_KEYWORDS["leadership"])][:6],
                "investment": [item for item in news if _matches_keywords(item, SIGNAL_KEYWORDS["investment"])][:6],
                "hiring": company_jobs[:6],
                "market_quote": market_quote,
                "financial_statements": financial_statements,
                "regulations": regulations[:5],
                "strategy_changes": _strategy_change(strategy_history),
                "counts": {
                    "news": len(news),
                    "disclosures": len(disclosures),
                    "leadership": sum(_matches_keywords(item, SIGNAL_KEYWORDS["leadership"]) for item in news),
                    "investment": sum(_matches_keywords(item, SIGNAL_KEYWORDS["investment"]) for item in news),
                    "hiring": len(company_jobs),
                    "finance": len(financial_statements),
                    "research_documents": len(research_documents),
                },
            }
        )
    return companies
