"""Database-backed localization inventory, scan, QA and bulk interchange."""

from __future__ import annotations

import csv
import hashlib
import html
import io
import json
import re
from datetime import datetime, timedelta
from pathlib import Path

from openpyxl import Workbook, load_workbook

from utils import now_kst


HANGUL_RE = re.compile(r"[가-힣]")
TAG_RE = re.compile(r"<[^>]+>")
HTML_TEXT_RE = re.compile(r">\s*([^<>{%]*[가-힣][^<>{%]*)\s*<")
ATTRIBUTE_RE = re.compile(
    r"(?:placeholder|title|aria-label|aria-description|data-confirm)\s*=\s*['\"]([^'\"]*[가-힣][^'\"]*)['\"]",
    re.IGNORECASE,
)
QUOTED_RE = re.compile(r"(?P<q>['\"])(?P<text>[^'\"\r\n]*[가-힣][^'\"\r\n]*)(?P=q)")
VARIABLE_RE = re.compile(r"\{\{?\s*[\w.]+\s*\}?\}|%\([^)]+\)[a-zA-Z]|%[a-zA-Z]")
MARKDOWN_RE = re.compile(r"(?:\[[^\]]+\]\([^)]+\)|[*_`#]{1,3})")
ALLOWED_STATUS = {"Pending", "Completed", "Ignored"}
ALLOWED_PRIORITY = {"Critical", "High", "Medium", "Low"}
PRIORITY_ORDER = {"Critical": 0, "High": 1, "Medium": 2, "Low": 3}


def _timestamp():
    return now_kst().isoformat(timespec="microseconds")


def _hash(text):
    return hashlib.sha256(text.strip().encode("utf-8")).hexdigest()


def _clean(text):
    return html.unescape(str(text or "")).strip()


def _priority(page, component, string_type):
    haystack = f"{page} {component} {string_type}".lower()
    if any(word in haystack for word in ("menu", "nav", "login", "register", "payment", "booking")):
        return "Critical"
    if any(word in haystack for word in ("company", "news", "research", "ai opinion", "기업", "뉴스", "리서치")):
        return "High"
    if any(word in haystack for word in ("tip", "notice", "faq", "공지", "자료")):
        return "Medium"
    if "admin" in haystack or "관리자" in haystack:
        return "Low"
    return "Medium"


def _key(text, prefix="UI"):
    return f"{prefix}_{_hash(text)[:16].upper()}"


def register_string(connection, source_text, *, page="Unknown", component="Content",
                    string_type="UI", source_kind="runtime", source_path="", locator="",
                    language_key=None):
    """Register or refresh one deduplicated source string and its reference."""
    text = _clean(source_text)
    if not text or not HANGUL_RE.search(text) or len(text) > 20000:
        return None
    now = _timestamp()
    digest = _hash(text)
    row = connection.execute(
        "SELECT id, source_text FROM localization_strings WHERE source_hash=?", (digest,)
    ).fetchone()
    created = row is None
    if created:
        cursor = connection.execute(
            """INSERT INTO localization_strings
                   (language_key, source_text, source_hash, page_name, component,
                    string_type, priority, status, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, 'Pending', ?, ?)""",
            (language_key or _key(text), text, digest, page, component, string_type,
             _priority(page, component, string_type), now, now),
        )
        string_id = cursor.lastrowid
        connection.execute(
            """INSERT INTO localization_events
                   (string_id, event_type, detail, created_at)
               VALUES (?, 'pending_created', ?, ?)""",
            (string_id, source_path[:500], now),
        )
    else:
        string_id = row["id"]
        connection.execute(
            "UPDATE localization_strings SET deleted_at=NULL WHERE id=?", (string_id,)
        )
    if source_path:
        connection.execute(
            """INSERT INTO localization_references
                   (string_id, source_kind, source_path, locator, last_seen_at)
               VALUES (?, ?, ?, ?, ?)
               ON CONFLICT(string_id, source_kind, source_path, locator)
               DO UPDATE SET last_seen_at=excluded.last_seen_at""",
            (string_id, source_kind, source_path[:500], locator[:200], now),
        )
    return string_id


def _scan_file(path, root):
    try:
        source = path.read_text(encoding="utf-8")
    except (OSError, UnicodeError):
        return []
    relative = path.relative_to(root).as_posix()
    page = path.stem.replace("_", " ").title()
    matches = []
    patterns = (HTML_TEXT_RE, ATTRIBUTE_RE) if path.suffix == ".html" else (QUOTED_RE,)
    for pattern in patterns:
        for match in pattern.finditer(source):
            text = _clean(match.group(1) if pattern is not QUOTED_RE else match.group("text"))
            text = re.sub(r"\s+", " ", text)
            if not text or len(text) > 2000 or not HANGUL_RE.search(text):
                continue
            line = source.count("\n", 0, match.start()) + 1
            component = "Template" if path.suffix == ".html" else "Server Message"
            string_type = "UI" if path.suffix == ".html" else "Message"
            matches.append((text, page, component, string_type, relative, f"line:{line}"))
    return matches


def scan_project(connection, project_root):
    """Inventory static source plus supported dynamic content; never modifies source files."""
    root = Path(project_root).resolve()
    scanned = registered = 0
    scan_started = _timestamp()
    for folder, suffixes in (
        ("templates", {".html"}), ("static/js", {".js"}),
        ("auth", {".py"}), ("services", {".py"}),
    ):
        base = root / folder
        if not base.exists():
            continue
        for path in base.rglob("*"):
            if not path.is_file() or path.suffix not in suffixes:
                continue
            scanned += 1
            for text, page, component, kind, relative, locator in _scan_file(path, root):
                if register_string(connection, text, page=page, component=component,
                                   string_type=kind, source_kind="file",
                                   source_path=relative, locator=locator):
                    registered += 1
    for filename in ("app.py", "official_docs.py", "tips.py", "localization.py"):
        path = root / filename
        if not path.is_file():
            continue
        scanned += 1
        for text, page, component, kind, relative, locator in _scan_file(path, root):
            if register_string(connection, text, page=page, component=component,
                               string_type=kind, source_kind="file",
                               source_path=relative, locator=locator):
                registered += 1

    catalog_path = root / "translations" / "catalog.json"
    if catalog_path.is_file():
        catalog = json.loads(catalog_path.read_text(encoding="utf-8"))
        for source_text, translated in catalog.get("text", {}).items():
            string_id = register_string(
                connection, source_text, page="Global", component="Catalog",
                string_type="UI", source_kind="catalog",
                source_path="translations/catalog.json", language_key=_key(source_text, "CATALOG"),
            )
            if string_id and translated:
                save_translation(connection, string_id, "en", translated, actor_id=None)

    # Dynamic sources are registered without translating or changing their data.
    dynamic = (
        ("company", "monitored_companies", ("name",), "기업정보", "Company", ""),
        ("company_profile", "company_research_profiles",
         ("company_name", "business_summary", "strategy_summary"), "기업정보", "Company", ""),
        ("notice", "community_posts", ("title", "content"), "공지", "Notice", "board_type='notice'"),
        ("board", "community_posts", ("title", "content"), "자유 게시판", "Content", "board_type='community'"),
        ("research", "research_documents",
         ("title", "ai_summary", "industry_impact", "investment_stance"), "리서치", "Research", ""),
        ("tip", "tips_articles", ("title", "summary", "body"), "자료실", "Tips", "is_deleted=0"),
    )
    tables = {row[0] for row in connection.execute(
        "SELECT name FROM sqlite_master WHERE type='table'"
    ).fetchall()}
    for kind, table, fields, page, string_type, where in dynamic:
        if table not in tables:
            continue
        columns = {row[1] for row in connection.execute(f"PRAGMA table_info({table})")}
        fields = tuple(field for field in fields if field in columns)
        if not fields:
            continue
        sql = f"SELECT id, {', '.join(fields)} FROM {table}"
        if where:
            sql += f" WHERE {where}"
        for row in connection.execute(sql).fetchall():
            for field in fields:
                if register_string(connection, row[field], page=page, component="Dynamic Content",
                                   string_type=string_type, source_kind="database",
                                   source_path=f"{table}:{row['id']}", locator=field):
                    registered += 1

    # A full scan owns file/catalog references. References not seen in this run
    # represent removed or modified source strings and are retired non-destructively.
    connection.execute(
        "DELETE FROM localization_references WHERE source_kind IN ('file','catalog') AND last_seen_at<?",
        (scan_started,),
    )
    stale = connection.execute(
        """SELECT s.id FROM localization_strings s
           WHERE s.deleted_at IS NULL AND NOT EXISTS
             (SELECT 1 FROM localization_references r WHERE r.string_id=s.id)"""
    ).fetchall()
    for row in stale:
        connection.execute(
            "UPDATE localization_strings SET deleted_at=?, updated_at=? WHERE id=?",
            (scan_started, scan_started, row["id"]),
        )
        connection.execute(
            "INSERT INTO localization_events (string_id,event_type,created_at) VALUES (?,'deleted',?)",
            (row["id"], scan_started),
        )
    connection.commit()
    return {"files_scanned": scanned, "strings_seen": registered}


def scan_if_due(connection, project_root, interval_minutes=60):
    """Run at most once per interval when an administrator renders the site."""
    row = connection.execute(
        "SELECT setting_value FROM site_settings WHERE setting_key='localization_last_scan_at'"
    ).fetchone()
    if row:
        try:
            last_scan = datetime.fromisoformat(row["setting_value"])
            if now_kst() - last_scan < timedelta(minutes=interval_minutes):
                return None
        except (TypeError, ValueError):
            pass
    result = scan_project(connection, project_root)
    now = _timestamp()
    connection.execute(
        """INSERT INTO site_settings (setting_key, setting_value, updated_by, updated_at)
           VALUES ('localization_last_scan_at', ?, NULL, ?)
           ON CONFLICT(setting_key) DO UPDATE SET
             setting_value=excluded.setting_value, updated_at=excluded.updated_at""",
        (now, now),
    )
    connection.commit()
    return result


def save_translation(connection, string_id, language_code, translated_text, actor_id=None,
                     *, status="Completed", record_event=True):
    if status not in ALLOWED_STATUS:
        raise ValueError("invalid status")
    language = connection.execute(
        "SELECT 1 FROM localization_languages WHERE language_code=? AND is_active=1",
        (language_code,),
    ).fetchone()
    if not language or language_code == "ko":
        raise ValueError("invalid language")
    text = str(translated_text or "").strip()
    if status == "Completed" and not text:
        raise ValueError("completed translation cannot be empty")
    now = _timestamp()
    connection.execute(
        """INSERT INTO localization_translations
               (string_id, language_code, translated_text, status, translated_by,
                created_at, updated_at, last_translated_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)
           ON CONFLICT(string_id, language_code) DO UPDATE SET
               translated_text=excluded.translated_text, status=excluded.status,
               translated_by=excluded.translated_by, updated_at=excluded.updated_at,
               last_translated_at=excluded.last_translated_at""",
        (string_id, language_code, text or None, status, actor_id, now, now,
         now if status == "Completed" else None),
    )
    connection.execute(
        "UPDATE localization_strings SET updated_at=? WHERE id=?", (now, string_id)
    )
    if record_event:
        connection.execute(
            """INSERT INTO localization_events
                   (string_id, event_type, language_code, actor_id, created_at)
               VALUES (?, ?, ?, ?, ?)""",
            (string_id, "translation_completed" if status == "Completed" else "status_changed",
             language_code, actor_id, now),
        )


def dashboard_summary(connection, language_code="en"):
    counts = {row["status"]: row["count"] for row in connection.execute(
        """SELECT CASE WHEN s.status='Ignored' THEN 'Ignored'
                       ELSE COALESCE(t.status, 'Pending') END AS status, COUNT(*) AS count
           FROM localization_strings s
           LEFT JOIN localization_translations t
             ON t.string_id=s.id AND t.language_code=?
           WHERE s.deleted_at IS NULL GROUP BY CASE WHEN s.status='Ignored' THEN 'Ignored'
                       ELSE COALESCE(t.status, 'Pending') END""",
        (language_code,),
    ).fetchall()}
    total = sum(counts.values())
    completed = counts.get("Completed", 0)
    coverage = round(completed * 100 / total, 2) if total else 100.0
    health = "Excellent" if coverage >= 98 else "Good" if coverage >= 90 else "Needs Review"
    since = (now_kst() - timedelta(hours=24)).isoformat(timespec="seconds")
    recent_counts = {row["event_type"]: row["count"] for row in connection.execute(
        "SELECT event_type, COUNT(*) AS count FROM localization_events WHERE created_at>=? GROUP BY event_type",
        (since,),
    ).fetchall()}
    events = connection.execute(
        """SELECT e.*, s.language_key, s.source_text FROM localization_events e
           LEFT JOIN localization_strings s ON s.id=e.string_id
           WHERE e.created_at>=? ORDER BY e.created_at DESC LIMIT 30""", (since,)
    ).fetchall()
    return {"counts": counts, "total": total, "completed": completed,
            "pending": counts.get("Pending", 0), "ignored": counts.get("Ignored", 0),
            "coverage": coverage, "health": health,
            "recent_counts": recent_counts, "events": [dict(row) for row in events]}


def list_strings(connection, *, language_code="en", query="", status="", priority="",
                 sort="newest", page=1, per_page=50):
    clauses = ["s.deleted_at IS NULL"]
    params = [language_code]
    if query:
        clauses.append("(s.source_text LIKE ? OR s.language_key LIKE ? OR s.page_name LIKE ? OR s.string_type LIKE ?)")
        needle = f"%{query[:200]}%"
        params.extend([needle] * 4)
    if status in ALLOWED_STATUS:
        clauses.append("(CASE WHEN s.status='Ignored' THEN 'Ignored' ELSE COALESCE(t.status, 'Pending') END)=?")
        params.append(status)
    if priority in ALLOWED_PRIORITY:
        clauses.append("s.priority=?")
        params.append(priority)
    order = {
        "oldest": "s.created_at ASC", "page": "s.page_name, s.language_key",
        "type": "s.string_type, s.language_key",
        "priority": "CASE s.priority WHEN 'Critical' THEN 0 WHEN 'High' THEN 1 WHEN 'Medium' THEN 2 ELSE 3 END, s.updated_at DESC",
    }.get(sort, "s.updated_at DESC")
    where = " AND ".join(clauses)
    total = connection.execute(
        f"""SELECT COUNT(*) FROM localization_strings s
            LEFT JOIN localization_translations t ON t.string_id=s.id AND t.language_code=?
            WHERE {where}""", params,
    ).fetchone()[0]
    offset = (max(1, page) - 1) * per_page
    rows = connection.execute(
        f"""SELECT s.*, t.translated_text,
                   CASE WHEN s.status='Ignored' THEN 'Ignored' ELSE COALESCE(t.status, 'Pending') END AS effective_status,
                   t.last_translated_at,
                   (SELECT COUNT(*) FROM localization_references r WHERE r.string_id=s.id) AS reference_count
            FROM localization_strings s
            LEFT JOIN localization_translations t ON t.string_id=s.id AND t.language_code=?
            WHERE {where} ORDER BY {order} LIMIT ? OFFSET ?""",
        (*params, per_page, offset),
    ).fetchall()
    return [dict(row) for row in rows], total


def references(connection, string_id):
    return [dict(row) for row in connection.execute(
        "SELECT * FROM localization_references WHERE string_id=? ORDER BY source_kind, source_path",
        (string_id,),
    ).fetchall()]


def qa_report(connection, language_code="en"):
    rows = connection.execute(
        """SELECT s.id, s.language_key, s.source_text, s.page_name, s.string_type,
                  t.translated_text, t.status
           FROM localization_strings s LEFT JOIN localization_translations t
             ON t.string_id=s.id AND t.language_code=? WHERE s.deleted_at IS NULL""",
        (language_code,),
    ).fetchall()
    findings = []
    for row in rows:
        source = row["source_text"] or ""
        target = row["translated_text"] or ""
        issues = []
        if not target:
            issues.append("영어 누락/빈 문자열")
        else:
            if HANGUL_RE.search(target): issues.append("한국어가 그대로 포함됨")
            if sorted(VARIABLE_RE.findall(source)) != sorted(VARIABLE_RE.findall(target)):
                issues.append("변수 누락 또는 변경")
            if len(TAG_RE.findall(source)) != len(TAG_RE.findall(target)):
                issues.append("HTML 태그 구조 변경")
            if len(MARKDOWN_RE.findall(source)) != len(MARKDOWN_RE.findall(target)):
                issues.append("Markdown 구조 변경")
            if source.count("\n") != target.count("\n"): issues.append("줄바꿈 손실")
            source_special = {c for c in source if c in "↗©®™•·→←↑↓"}
            if not source_special.issubset(set(target)): issues.append("특수문자 손실")
        for issue in issues:
            findings.append({**dict(row), "issue": issue})
    return findings


def export_rows(connection, language_code="en"):
    return [dict(row) for row in connection.execute(
        """SELECT s.id, s.language_key, s.page_name, s.component, s.string_type,
                  s.priority, s.source_text AS korean, COALESCE(t.translated_text, '') AS translation,
                  CASE WHEN s.status='Ignored' THEN 'Ignored' ELSE COALESCE(t.status, 'Pending') END AS status
           FROM localization_strings s LEFT JOIN localization_translations t
             ON t.string_id=s.id AND t.language_code=?
           WHERE s.deleted_at IS NULL ORDER BY s.id""", (language_code,)
    ).fetchall()]


def export_file(connection, language_code="en", file_type="csv"):
    rows = export_rows(connection, language_code)
    headers = ["id", "language_key", "page_name", "component", "string_type", "priority", "korean", "translation", "status"]
    def safe_cell(value):
        value = "" if value is None else str(value)
        return f"'{value}" if value.startswith(("=", "+", "-", "@")) else value

    safe_rows = [{name: safe_cell(row[name]) for name in headers} for row in rows]
    if file_type == "xlsx":
        stream = io.BytesIO()
        workbook = Workbook()
        sheet = workbook.active
        sheet.title = "Localization"
        sheet.append(headers)
        for row in safe_rows: sheet.append([row[name] for name in headers])
        workbook.save(stream)
        return stream.getvalue(), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    stream = io.StringIO(newline="")
    writer = csv.DictWriter(stream, fieldnames=headers)
    writer.writeheader(); writer.writerows(safe_rows)
    return ("\ufeff" + stream.getvalue()).encode("utf-8"), "text/csv; charset=utf-8"


def import_file(connection, file_storage, language_code, actor_id=None):
    filename = (file_storage.filename or "").lower()
    raw = file_storage.read(10 * 1024 * 1024 + 1)
    if len(raw) > 10 * 1024 * 1024:
        raise ValueError("파일은 10MB 이하여야 합니다.")
    if filename.endswith(".csv"):
        reader = csv.DictReader(io.StringIO(raw.decode("utf-8-sig")))
        rows = list(reader)
    elif filename.endswith(".xlsx"):
        workbook = load_workbook(io.BytesIO(raw), read_only=True, data_only=True)
        sheet = workbook.active
        values = sheet.iter_rows(values_only=True)
        headers = [str(value or "").strip() for value in next(values)]
        rows = [dict(zip(headers, values_row)) for values_row in values]
    else:
        raise ValueError("CSV 또는 XLSX 파일만 가져올 수 있습니다.")
    updated = errors = 0
    for row in rows:
        try:
            string_id = int(row.get("id") or 0)
            translation = str(row.get("translation") or "").strip()
            status = str(row.get("status") or ("Completed" if translation else "Pending")).strip()
            if not connection.execute("SELECT 1 FROM localization_strings WHERE id=?", (string_id,)).fetchone():
                raise ValueError("unknown id")
            save_translation(connection, string_id, language_code, translation,
                             actor_id=actor_id, status=status)
            updated += 1
        except (TypeError, ValueError):
            errors += 1
    connection.commit()
    return {"updated": updated, "errors": errors}
