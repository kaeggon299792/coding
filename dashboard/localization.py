"""Prefix-based localization for the dashboard.

The application keeps one set of routes and templates.  English requests use an
``/en`` URL prefix which is removed by :class:`LocalePrefixMiddleware` before
Flask performs routing.  ``SCRIPT_NAME`` retains the prefix, so ``url_for`` and
form actions automatically stay in the language the visitor selected.

Static UI copy lives in ``translations/catalog.json``.  Korean remains the
fallback language; an incomplete English catalog can therefore never make a
page unusable.
"""

from __future__ import annotations

import json
import re
import sqlite3
import time
from functools import lru_cache
from html import escape, unescape
from pathlib import Path
from typing import Any, Callable, Iterable
from urllib.parse import parse_qsl, urlencode


SUPPORTED_LOCALES = ("ko", "en", "ja", "yue-HK")
LOCALE_PREFIXES = {locale.lower(): locale for locale in SUPPORTED_LOCALES if locale != "ko"}
DEFAULT_LOCALE = "ko"
CATALOG_FILE = Path(__file__).resolve().parent / "translations" / "catalog.json"
_LMS_CACHE = {"expires": 0.0, "db_path": "", "text": {}}

_PROTECTED_HTML_RE = re.compile(
    r"(<(?:pre|code|textarea)\b[^>]*>.*?</(?:pre|code|textarea)\s*>|<[^>]+>)",
    re.IGNORECASE | re.DOTALL,
)
_IGNORED_BLOCK_RE = re.compile(
    r"<(?P<tag>[a-z][\w:-]*)\b[^>]*\bdata-i18n-ignore\b[^>]*>"
    r".*?</(?P=tag)\s*>",
    re.IGNORECASE | re.DOTALL,
)
_ATTRIBUTE_RE = re.compile(
    r'(?P<prefix>\b(?:aria-label|aria-description|placeholder|title|data-confirm)'
    r'\s*=\s*)(?P<quote>["\'])(?P<value>.*?)(?P=quote)',
    re.IGNORECASE | re.DOTALL,
)
_SCRIPT_BLOCK_RE = re.compile(
    r"(<script\b[^>]*>)(.*?)(</script\s*>)",
    re.IGNORECASE | re.DOTALL,
)
_TITLE_RE = re.compile(r"(<title\b[^>]*>)(.*?)(</title\s*>)", re.IGNORECASE | re.DOTALL)
_JS_STRING_RE = re.compile(
    r"(?P<quote>[\"'])(?P<value>(?:\\.|(?!\1).)*?)(?P=quote)",
    re.DOTALL,
)
_SPACE_RE = re.compile(r"^(\s*)(.*?)(\s*)$", re.DOTALL)
_DISCOVERY_BLOCK_RE = re.compile(
    r"<(?:script|style|svg|pre|code|textarea)\b[^>]*>.*?</(?:script|style|svg|pre|code|textarea)\s*>",
    re.IGNORECASE | re.DOTALL,
)
_HANGUL_RE = re.compile(r"[\uac00-\ud7a3]")
_EOK_WON_RE = re.compile(r"^([+-]?[0-9,]+(?:\.[0-9]+)?)억원$")
_MAN_WON_RE = re.compile(r"^([+-]?[0-9,]+(?:\.[0-9]+)?)만원$")
_PEOPLE_RE = re.compile(r"^([+-]?[0-9,]+)명$")


def locale_for_country(country_code: str | None) -> str | None:
    """Return the first-visit locale for a trusted two-letter country code."""
    country = str(country_code or "").strip().upper()
    if not re.fullmatch(r"[A-Z]{2}", country) or country == "XX":
        return None
    if country == "KR":
        return "ko"
    if country == "JP":
        return "ja"
    if country in {"CN", "HK", "MO"}:
        return "yue-HK"
    return "en"


class LocalePrefixMiddleware:
    """Expose the complete Flask application below every supported locale prefix."""

    def __init__(self, app: Callable):
        self.app = app

    def __call__(self, environ: dict, start_response: Callable):
        path = environ.get("PATH_INFO", "") or "/"
        locale = DEFAULT_LOCALE
        first_segment = path.lstrip("/").split("/", 1)[0].lower()
        if first_segment in LOCALE_PREFIXES:
            locale = LOCALE_PREFIXES[first_segment]
            prefix = f"/{first_segment}"
            script_name = (environ.get("SCRIPT_NAME", "") or "").rstrip("/")
            environ["SCRIPT_NAME"] = f"{script_name}{prefix}"
            stripped = path[len(prefix):]
            environ["PATH_INFO"] = stripped or "/"
        environ["DASHBOARD_LOCALE"] = locale
        return self.app(environ, start_response)


@lru_cache(maxsize=1)
def load_catalog() -> dict[str, Any]:
    if not CATALOG_FILE.is_file():
        return {"meta": {"ko": {}, "en": {}}, "text": {}, "patterns": {}}
    with CATALOG_FILE.open("r", encoding="utf-8") as handle:
        data = json.load(handle)
    data.setdefault("meta", {}).setdefault("ko", {})
    data.setdefault("meta", {}).setdefault("en", {})
    data.setdefault("text", {})
    data.setdefault("patterns", {})
    return data


def locale_from_environ(environ: dict) -> str:
    locale = environ.get("DASHBOARD_LOCALE", DEFAULT_LOCALE)
    return locale if locale in SUPPORTED_LOCALES else DEFAULT_LOCALE


def meta_for(locale: str) -> dict[str, str]:
    catalog = load_catalog()
    default_meta = catalog["meta"].get(DEFAULT_LOCALE, {})
    selected = catalog["meta"].get(locale, {})
    return {**default_meta, **selected}


def _apply_patterns(text: str, patterns: Iterable[tuple[str, str]]) -> str:
    for source, replacement in patterns:
        try:
            # Catalog replacements use JavaScript-style capture references
            # (``$1``, ``$2``) because the same file is consumed in the browser.
            # Expand them explicitly for Python's regex engine.
            text = re.sub(
                source,
                lambda match: re.sub(
                    r"\$(\d+)",
                    lambda group: (
                        (match.group(int(group.group(1))) or "")
                        if int(group.group(1)) <= (match.lastindex or 0)
                        else ""
                    ),
                    replacement,
                ),
                text,
            )
        except re.error:
            # A malformed optional pattern must not take down the dashboard.
            continue
    return text


def translate_text(value: Any, locale: str = DEFAULT_LOCALE) -> Any:
    """Translate one UI value while preserving whitespace and non-strings."""

    if locale == DEFAULT_LOCALE or not isinstance(value, str) or not value:
        return value
    catalog = load_catalog()
    match = _SPACE_RE.match(value)
    if not match:
        return value
    leading, core, trailing = match.groups()
    translated = _lms_text_map(locale).get(core)
    if translated is None and locale == "en":
        translated = catalog["text"].get(core)
    if translated is None and locale == "en":
        translated = _translate_numeric_unit(core)
    if translated is None and locale == "en":
        translated = _apply_patterns(core, catalog.get("patterns", {}).items())
    if translated is None:
        translated = core
    return f"{leading}{translated}{trailing}"


def translate_source_label(value: Any, locale: str = DEFAULT_LOCALE) -> Any:
    """Localize recurring Korean tokens in compound source-series labels.

    Source-series names can combine provider-supplied English names with a
    Korean frequency suffix. Keep the stored source untouched and translate
    only those well-defined display tokens.
    """
    translated = translate_text(value, locale)
    if locale == DEFAULT_LOCALE or not isinstance(translated, str):
        return translated
    month_names = (
        "", "January", "February", "March", "April", "May", "June",
        "July", "August", "September", "October", "November", "December",
    )

    def replace_as_of(match: re.Match) -> str:
        year, month = match.group(1), int(match.group(2))
        if locale == "en":
            return f"As of {month_names[month]} {year}"
        if locale == "ja":
            return f"{year}年{month}月時点"
        return f"截至{year}年{month}月"

    translated = re.sub(
        r"(\d{4})년\s*(\d{1,2})월\s*기준", replace_as_of, translated
    )
    replacements = {
        "en": {
            "분기누계": "Quarter-to-date", "연누계": "Year-to-date",
            "분기별": "Quarterly", "연간": "Annual", "월별": "Monthly",
            "전체 입장객": "Total visitors", "입장객": "Visitors",
            "데이터 표": "data table",
        },
        "ja": {
            "분기누계": "四半期累計", "연누계": "年初来累計",
            "분기별": "四半期別", "연간": "年間", "월별": "月別",
            "전체 입장객": "総入場者数", "입장객": "入場者数",
            "데이터 표": "データ表",
        },
        "yue-HK": {
            "분기누계": "季度累計", "연누계": "年初至今累計",
            "분기별": "按季度", "연간": "全年", "월별": "按月",
            "전체 입장객": "總入場人次", "입장객": "入場人次",
            "데이터 표": "資料表",
        },
    }
    for source, target in replacements.get(locale, {}).items():
        translated = translated.replace(source, target)
    return translated


def _translate_numeric_unit(text: str) -> str | None:
    """Translate frequently changing Korean financial/count units."""

    match = _EOK_WON_RE.match(text)
    if match:
        value = float(match.group(1).replace(",", "")) / 10
        return f"KRW {value:,.1f}B"
    match = _MAN_WON_RE.match(text)
    if match:
        value = float(match.group(1).replace(",", "")) / 100
        return f"KRW {value:,.2f}M"
    match = _PEOPLE_RE.match(text)
    if match:
        return f"{match.group(1)} people"
    return None


def _lms_text_map(locale: str) -> dict[str, str]:
    """Return completed manual LMS translations with a short process cache."""
    if locale == DEFAULT_LOCALE:
        return {}
    now = time.monotonic()
    translations: dict[str, dict[str, str]] = {}
    try:
        import config
        db_path = str(config.DASHBOARD_DB_FILE)
        if db_path == _LMS_CACHE["db_path"] and now < _LMS_CACHE["expires"]:
            return _LMS_CACHE["text"].get(locale, {})
        connection = sqlite3.connect(db_path)
        try:
            rows = connection.execute(
                """SELECT s.source_text, t.language_code, t.translated_text
                   FROM localization_strings s JOIN localization_translations t
                     ON t.string_id=s.id
                   WHERE s.deleted_at IS NULL AND t.status='Completed'
                     AND t.translated_text IS NOT NULL"""
            ).fetchall()
            for source, language_code, target in rows:
                translations.setdefault(language_code, {})[source] = target
        finally:
            connection.close()
    except (ImportError, OSError, sqlite3.Error):
        translations = {}
    _LMS_CACHE["text"] = translations
    _LMS_CACHE["db_path"] = str(getattr(config, "DASHBOARD_DB_FILE", ""))
    _LMS_CACHE["expires"] = now + 60.0
    return translations.get(locale, {})


def translate_structure(value: Any, locale: str = DEFAULT_LOCALE) -> Any:
    """Translate message-like JSON structures without changing source datasets."""

    if locale == DEFAULT_LOCALE:
        return value
    if isinstance(value, list):
        return [translate_structure(item, locale) for item in value]
    if isinstance(value, dict):
        translated = dict(value)
        for key in ("message", "error", "notice", "detail"):
            if key in translated and isinstance(translated[key], str):
                translated[key] = translate_text(translated[key], locale)
        return translated
    return translate_text(value, locale)


def _translate_tag_attributes(tag: str, locale: str) -> str:
    def replace_attribute(match: re.Match) -> str:
        value = translate_text(match.group("value"), locale)
        return (
            f"{match.group('prefix')}{match.group('quote')}"
            f"{escape(value, quote=True)}{match.group('quote')}"
        )

    return _ATTRIBUTE_RE.sub(replace_attribute, tag)


def _translate_js_strings(script: str, locale: str) -> str:
    def replace_string(match: re.Match) -> str:
        original = match.group("value")
        translated = translate_text(original, locale)
        if translated == original:
            return match.group(0)
        quote = match.group("quote")
        safe = translated.replace("\\", "\\\\").replace(quote, f"\\{quote}")
        safe = safe.replace("\r", "\\r").replace("\n", "\\n")
        return f"{quote}{safe}{quote}"

    return _JS_STRING_RE.sub(replace_string, script)


def _translate_inline_phrases(value: str, locale: str) -> str:
    """Translate known phrases inside compound strings such as document titles."""

    if locale == DEFAULT_LOCALE:
        return value
    text_map = _lms_text_map(locale)
    if locale == "en":
        text_map = {**load_catalog().get("text", {}), **text_map}
    for source in sorted(text_map, key=len, reverse=True):
        if source and source in value:
            value = value.replace(source, str(text_map[source]))
    return value


def translate_html(html: str, locale: str = DEFAULT_LOCALE) -> str:
    """Translate rendered HTML without duplicating any Jinja template."""

    if locale == DEFAULT_LOCALE or not html:
        return html

    html = _TITLE_RE.sub(
        lambda match: (
            f"{match.group(1)}{_translate_inline_phrases(match.group(2), locale)}"
            f"{match.group(3)}"
        ),
        html,
    )

    ignored_blocks: list[str] = []

    def protect_ignored(match: re.Match) -> str:
        ignored_blocks.append(match.group(0))
        return f"___DASHBOARD_IGNORED_{len(ignored_blocks) - 1}___"

    html = _IGNORED_BLOCK_RE.sub(protect_ignored, html)

    scripts: list[str] = []

    def protect_script(match: re.Match) -> str:
        body = match.group(2)
        if "application/json" not in match.group(1).lower():
            body = _translate_js_strings(body, locale)
        scripts.append(
            f"{match.group(1)}{body}{match.group(3)}"
        )
        return f"___DASHBOARD_SCRIPT_{len(scripts) - 1}___"

    html = _SCRIPT_BLOCK_RE.sub(protect_script, html)
    parts = _PROTECTED_HTML_RE.split(html)
    output: list[str] = []
    for part in parts:
        if not part:
            continue
        if part.startswith("<"):
            output.append(_translate_tag_attributes(part, locale))
        else:
            output.append(translate_text(part, locale))
    translated_html = "".join(output)
    for index, script in enumerate(scripts):
        translated_html = translated_html.replace(
            f"___DASHBOARD_SCRIPT_{index}___", script
        )
    for index, block in enumerate(ignored_blocks):
        translated_html = translated_html.replace(
            f"___DASHBOARD_IGNORED_{index}___", block
        )
    return translated_html


def extract_translatable_html_strings(html: str) -> list[str]:
    """Return deduplicated Korean strings that are actually visible in HTML.

    Executable/protected blocks are deliberately excluded.  This is used only
    for public-page LMS discovery; it never changes the rendered response.
    """

    if not html:
        return []
    visible = _IGNORED_BLOCK_RE.sub("", html)
    visible = _DISCOVERY_BLOCK_RE.sub("", visible)
    candidates = [match.group("value") for match in _ATTRIBUTE_RE.finditer(visible)]
    candidates.extend(re.split(r"<[^>]+>", visible))
    found: list[str] = []
    seen: set[str] = set()
    for candidate in candidates:
        text = re.sub(r"\s+", " ", unescape(candidate)).strip()
        if not text or len(text) > 2000 or not _HANGUL_RE.search(text) or text in seen:
            continue
        seen.add(text)
        found.append(text)
    return found


def alternate_paths(path: str, query_string: str = "") -> dict[str, str]:
    normalized = path if path.startswith("/") else f"/{path}"

    def localized_query(target_locale: str) -> str:
        if not query_string:
            return ""
        pairs = parse_qsl(query_string, keep_blank_values=True)
        localized_pairs = []
        for key, value in pairs:
            if key == "next" and value.startswith("/") and not value.startswith("//"):
                for prefix in LOCALE_PREFIXES:
                    marker = f"/{prefix}"
                    if value == marker:
                        value = "/"
                        break
                    if value.startswith(f"{marker}/"):
                        value = value[len(marker):]
                        break
                if target_locale != "ko":
                    prefix = f"/{target_locale.lower()}"
                    value = prefix if value == "/" else f"{prefix}{value}"
            localized_pairs.append((key, value))
        encoded = urlencode(localized_pairs, doseq=True)
        return f"?{encoded}" if encoded else ""

    paths = {"ko": f"{normalized}{localized_query('ko')}"}
    for locale in SUPPORTED_LOCALES:
        if locale == "ko":
            continue
        prefix = f"/{locale.lower()}"
        localized = f"{prefix}/" if normalized == "/" else f"{prefix}{normalized}"
        paths[locale] = f"{localized}{localized_query(locale)}"
    return paths
