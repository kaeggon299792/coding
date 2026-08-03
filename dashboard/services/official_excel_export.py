"""공문 대장을 안전한 새 XLSX 파일로 생성한다."""

import os
import tempfile
from datetime import datetime
from pathlib import PureWindowsPath

import xlsxwriter


HEADERS = [
    "접수번호", "담당", "접수일", "기관명(회사명)", "사건", "요청내용", "특이사항",
    "의뢰자", "연락처", "이메일", "발송번호", "회신일", "위치", "영상반출여부", "반출확약서",
]
WIDTHS = [15.25, 13.25, 13.38, 19.63, 27.13, 70, 48.25, 15.38, 17.88, 19.25, 19.25, 17.5, 35, 16.38, 16]
TEXT_COLUMNS = {0, 2, 8, 10, 11}
WRAP_COLUMNS = {5, 6}
CENTER_COLUMNS = {0, 1, 2, 7, 8, 10, 11, 13, 14}
MAX_EXCEL_DATA_ROWS = 1_048_575
EXPORT_VERSION = "2.0"


def _date_text(value):
    return str(value or "").replace("-", "") if value else ""


def _safe(value):
    return "" if value is None else str(value)


def _mask_contact(value):
    text = _safe(value)
    if not text:
        return ""
    digits = [index for index, char in enumerate(text) if char.isdigit()]
    for index in digits[3:-2]:
        text = text[:index] + "*" + text[index + 1:]
    return text


def _mask_email(value):
    text = _safe(value)
    if "@" not in text:
        return ""
    local, domain = text.split("@", 1)
    return (local[:2] + "***@" + domain) if local else "***@" + domain


def _as_drive_path(path, drive_letter):
    text = _safe(path).strip().replace("/", "\\")
    if not text:
        return ""
    if len(text) >= 3 and text[1:3] == ":\\":
        relative = text[3:]
    elif text.startswith("\\\\"):
        # UNC: \\server\share\relative -> X:\relative
        parts = [part for part in text[2:].split("\\") if part]
        if len(parts) < 3:
            return ""
        relative = "\\".join(parts[2:])
    else:
        return ""
    return f"{drive_letter}:\\{relative}"


def _location_parts(document, drive_letter):
    verified = document.get("folder_link_status") in (None, "", "LINK_VERIFIED")
    source_path = _safe(
        document.get("normalized_unc_path")
        or document.get("requested_folder_path")
        or document.get("location")
    )
    drive_path = _as_drive_path(source_path, drive_letter) if verified else ""
    is_linkable = bool(drive_path)
    display = _safe(document.get("folder_display_name"))
    if is_linkable:
        display = drive_path
    elif not display:
        try:
            display = PureWindowsPath(source_path).name if source_path else ""
        except ValueError:
            display = source_path
    return display, drive_path if is_linkable else ""


def create_workbook(documents, categories, folders, metadata, include_personal_data):
    if len(documents) > MAX_EXCEL_DATA_ROWS:
        raise ValueError("Excel 최대 행 수를 초과했습니다. 검색조건을 좁혀주세요.")
    handle = tempfile.NamedTemporaryFile(prefix="official_export_", suffix=".xlsx", delete=False)
    path = handle.name
    handle.close()
    try:
        workbook = xlsxwriter.Workbook(path, {"strings_to_urls": False})
        workbook.set_properties({
            "title": "외부자료제공 및 공문접수 대장",
            "author": metadata.get("username", ""),
            "comments": "웹 시스템에서 안전한 XLSX 형식으로 생성",
        })
        sheet = workbook.add_worksheet("DB")
        sheet.hide_gridlines(2)
        sheet.freeze_panes(1, 0)
        sheet.set_landscape()
        sheet.fit_to_pages(1, 0)
        sheet.set_margins(0.25, 0.25, 0.5, 0.5)
        for index, width in enumerate(WIDTHS):
            sheet.set_column(index, index, width)

        base = {"font_name": "맑은 고딕", "font_size": 10, "valign": "vcenter", "border": 1, "border_color": "#D8DEE9"}
        left = workbook.add_format({**base, "align": "left"})
        center = workbook.add_format({**base, "align": "center"})
        text_center = workbook.add_format({**base, "align": "center", "num_format": "@"})
        wrap = workbook.add_format({**base, "align": "left", "text_wrap": True})
        link = workbook.add_format({**base, "align": "left", "font_color": "#2F6B9A", "underline": 1})
        mail = workbook.add_format({**base, "align": "left", "font_color": "#2F6B9A", "underline": 1})
        header = workbook.add_format({
            "font_name": "맑은 고딕", "font_size": 10, "bold": True, "font_color": "#FFFFFF",
            "bg_color": "#26354A", "align": "center", "valign": "vcenter",
            "border": 1, "border_color": "#AAB4C3",
        })
        sheet.set_row(0, 28)
        for column, value in enumerate(HEADERS):
            sheet.write(0, column, value, header)

        drive_letter = str(metadata.get("drive_letter") or "Y").upper()
        if len(drive_letter) != 1 or drive_letter < "A" or drive_letter > "Z":
            raise ValueError("드라이브 문자는 A부터 Z 중 하나여야 합니다.")
        for row_index, document in enumerate(documents, 1):
            contact = _safe(document.get("contact")) if include_personal_data else _mask_contact(document.get("contact"))
            email = _safe(document.get("email")) if include_personal_data else _mask_email(document.get("email"))
            location_display, location_link = _location_parts(document, drive_letter)
            values = [
                _safe(document.get("receipt_number")), _safe(document.get("manager")),
                _date_text(document.get("receipt_date")), _safe(document.get("organization")),
                _safe(document.get("case_name")), _safe(document.get("request_content")),
                _safe(document.get("special_note")), _safe(document.get("requester")), contact,
                email, _safe(document.get("dispatch_number")), _date_text(document.get("reply_date")),
                location_display, _safe(document.get("video_exported")), _safe(document.get("export_pledge")),
            ]
            line_count = max(values[5].count("\n") + 1, values[6].count("\n") + 1)
            sheet.set_row(row_index, min(72, max(20, line_count * 15)))
            for column, value in enumerate(values):
                cell_format = wrap if column in WRAP_COLUMNS else (
                    text_center if column in TEXT_COLUMNS else center if column in CENTER_COLUMNS else left
                )
                if column == 9 and include_personal_data and value and "@" in value:
                    sheet.write_url(row_index, column, f"mailto:{value}", mail, value)
                elif column == 12 and location_link:
                    sheet.write_url(row_index, column, "external:" + location_link, link, value)
                else:
                    sheet.write_string(row_index, column, value, cell_format)

        last_row = max(1, len(documents))
        table_options = {
            "name": "OfficialDocumentLedger",
            "style": "Table Style Medium 2",
            "autofilter": True,
            "total_row": False,
            "columns": [{"header": value} for value in HEADERS],
        }
        sheet.add_table(0, 0, last_row, 14, table_options)
        sheet.print_area(0, 0, last_row, 14)

        meta = workbook.add_worksheet("Metadata")
        meta.hide_gridlines(2)
        meta.set_column("A:A", 24)
        meta.set_column("B:B", 60)
        meta_header = workbook.add_format({"font_name": "맑은 고딕", "bold": True, "font_color": "#FFFFFF", "bg_color": "#26354A", "border": 1})
        meta_value = workbook.add_format({"font_name": "맑은 고딕", "border": 1, "border_color": "#D8DEE9", "text_wrap": True})
        info_rows = [
            ("항목", "내용"),
            ("다운로드 생성일시", metadata.get("created_at", "")),
            ("다운로드 실행 사용자", metadata.get("username", "")),
            ("다운로드 유형", metadata.get("export_type", "")),
            ("적용된 검색조건", metadata.get("filters", "")),
            ("적용된 접수연도", metadata.get("year", "")),
            ("위치 링크 드라이브", drive_letter),
            ("총 데이터 건수", len(documents)),
            ("내보내기 버전", EXPORT_VERSION),
        ]
        for row, (label, value) in enumerate(info_rows):
            meta.write(row, 0, label, meta_header if row == 0 else meta_value)
            meta.write(row, 1, value, meta_header if row == 0 else meta_value)
        start = len(info_rows) + 2
        meta.write(start, 0, "분류", meta_header)
        meta.write(start, 1, "폴더구분", meta_header)
        max_rows = max(len(categories), len(folders))
        for offset in range(max_rows):
            meta.write(start + offset + 1, 0, categories[offset]["label"] if offset < len(categories) else "", meta_value)
            meta.write(start + offset + 1, 1, folders[offset]["label"] if offset < len(folders) else "", meta_value)
        workbook.close()
        return path
    except Exception:
        try:
            os.unlink(path)
        except OSError:
            pass
        raise
