"""Lightweight Korean/English localization for the dashboard.

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
from functools import lru_cache
from html import escape
from pathlib import Path
from typing import Any, Callable, Iterable
from urllib.parse import parse_qsl, urlencode


SUPPORTED_LOCALES = ("ko", "en")
DEFAULT_LOCALE = "ko"
CATALOG_FILE = Path(__file__).resolve().parent / "translations" / "catalog.json"

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


class LocalePrefixMiddleware:
    """Expose the complete Flask application below ``/en`` as well as ``/``."""

    def __init__(self, app: Callable):
        self.app = app

    def __call__(self, environ: dict, start_response: Callable):
        path = environ.get("PATH_INFO", "") or "/"
        locale = DEFAULT_LOCALE
        if path == "/en" or path.startswith("/en/"):
            locale = "en"
            script_name = (environ.get("SCRIPT_NAME", "") or "").rstrip("/")
            environ["SCRIPT_NAME"] = f"{script_name}/en"
            stripped = path[3:]
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

    if locale != "en" or not isinstance(value, str) or not value:
        return value
    catalog = load_catalog()
    match = _SPACE_RE.match(value)
    if not match:
        return value
    leading, core, trailing = match.groups()
    translated = catalog["text"].get(core)
    if translated is None:
        translated = _apply_patterns(core, catalog.get("patterns", {}).items())
    return f"{leading}{translated}{trailing}"


def translate_structure(value: Any, locale: str = DEFAULT_LOCALE) -> Any:
    """Translate message-like JSON structures without changing source datasets."""

    if locale != "en":
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

    if locale != "en":
        return value
    text_map = load_catalog().get("text", {})
    for source in sorted(text_map, key=len, reverse=True):
        if source and source in value:
            value = value.replace(source, str(text_map[source]))
    return value


def translate_html(html: str, locale: str = DEFAULT_LOCALE) -> str:
    """Translate rendered HTML without duplicating any Jinja template."""

    if locale != "en" or not html:
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


def alternate_paths(path: str, query_string: str = "") -> dict[str, str]:
    normalized = path if path.startswith("/") else f"/{path}"
    en_path = "/en/" if normalized == "/" else f"/en{normalized}"

    def localized_query(target_locale: str) -> str:
        if not query_string:
            return ""
        pairs = parse_qsl(query_string, keep_blank_values=True)
        localized_pairs = []
        for key, value in pairs:
            if key == "next" and value.startswith("/") and not value.startswith("//"):
                if target_locale == "ko":
                    value = "/" if value == "/en" else (
                        value[3:] if value.startswith("/en/") else value
                    )
                elif value != "/en" and not value.startswith("/en/"):
                    value = f"/en{value}"
            localized_pairs.append((key, value))
        encoded = urlencode(localized_pairs, doseq=True)
        return f"?{encoded}" if encoded else ""

    return {
        "ko": f"{normalized}{localized_query('ko')}",
        "en": f"{en_path}{localized_query('en')}",
    }
