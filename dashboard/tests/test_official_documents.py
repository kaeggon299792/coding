from datetime import date, timedelta
import os
import zipfile

import pytest
from werkzeug.datastructures import MultiDict

from services.official_document_manager import (
    OfficialDocumentError,
    build_archive_folder_name,
    normalize_date,
    review_reasons,
    sanitize_windows_component,
    create_document,
)
from services.official_excel_export import HEADERS, create_workbook
from sync_client.file_manager import UnsafeArchivePath, drive_path_to_unc


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("20260728", "2026-07-28"),
        ("2026.07.28", "2026-07-28"),
        ("2026-07-28", "2026-07-28"),
        ("2026/07/28", "2026-07-28"),
    ],
)
def test_normalize_date_formats(raw, expected):
    assert normalize_date(raw, required=True) == expected


def test_normalize_date_rejects_invalid_date():
    with pytest.raises(OfficialDocumentError):
        normalize_date("2026-02-30", required=True)


def test_archive_folder_name_is_windows_safe_and_limited():
    name = build_archive_folder_name(
        "2026-07-28",
        "03. 수사협조요청",
        '서울/경찰청:"본청"',
        "고객  게임내역\n및 외환거래 기록 요청?" * 10,
    )
    assert len(name) <= 120
    assert not any(char in name for char in '\\/:*?"<>|\r\n\t ')
    assert name.startswith("2026.07.28_03.수사협조요청_서울_경찰청_본청_")


def test_review_reasons_combines_all_applicable_reasons():
    document = {
        "receipt_date": (date.today() - timedelta(days=8)).isoformat(),
        "processing_result": "처리 필요",
        "storage_status": "FAILED",
        "location": None,
        "file_count": 0,
        "video_exported": "예",
        "export_pledge": "미접수",
    }
    assert review_reasons(document) == [
        "접수 후 7일 경과",
        "Y디스크 저장 실패",
        "반출확약서 확인 필요",
    ]


def test_reference_values_are_seeded(db_connection):
    categories = db_connection.execute(
        "SELECT code FROM official_doc_reference_values WHERE kind='category' ORDER BY sort_order"
    ).fetchall()
    folders = db_connection.execute(
        "SELECT code FROM official_doc_reference_values WHERE kind='folder_category' ORDER BY sort_order"
    ).fetchall()
    assert [row["code"] for row in categories] == ["01-1", "01-2", "02", "03", "04", "OTHER"]
    assert [row["code"] for row in folders] == [
        "071", "072", "073", "074", "075", "076", "077", "078", "079"
    ]


def _existing_folder_form():
    return MultiDict({
        "category_code": "03",
        "folder_category_code": "072",
        "manager": "홍길동",
        "receipt_date": "20260728",
        "organization": "서울세관",
        "request_content": "게임기록\n요청",
        "folder_handling_type": "LINK_EXISTING",
        "requested_folder_path": r"Y:\공문자료\072. 수사기관\2026\기존폴더",
        "folder_display_name": "기존폴더",
    })


def test_existing_folder_can_be_registered_without_pdf(db_connection):
    document_id, errors = create_document(
        db_connection, _existing_folder_form(), [], {"id": None, "username": "tester"}
    )
    assert errors is None
    row = db_connection.execute(
        "SELECT folder_handling_type, folder_link_status, temp_file_status, storage_status "
        "FROM official_documents WHERE id=?", (document_id,)
    ).fetchone()
    assert dict(row) == {
        "folder_handling_type": "LINK_EXISTING",
        "folder_link_status": "LINK_PENDING",
        "temp_file_status": "LINK_PENDING",
        "storage_status": "UPLOADED",
    }


def test_excel_export_structure_and_safety(db_connection):
    categories = [
        dict(row) for row in db_connection.execute(
            "SELECT * FROM official_doc_reference_values WHERE kind='category' ORDER BY sort_order"
        )
    ]
    folders = [
        dict(row) for row in db_connection.execute(
            "SELECT * FROM official_doc_reference_values WHERE kind='folder_category' ORDER BY sort_order"
        )
    ]
    document = {
        "receipt_number": "2021-12", "manager": "홍길동", "receipt_date": "2021-01-27",
        "organization": "서울세관", "case_name": "사건", "request_content": "첫째 줄\n둘째 줄",
        "special_note": None, "requester": "김담당", "contact": "02-501-1659",
        "email": "myjung17@korea.kr", "dispatch_number": "2021-16", "reply_date": "2021-02-10",
        "location": r"\\fileserver\공문자료\072. 수사기관\2021\기존폴더",
        "normalized_unc_path": r"\\fileserver\공문자료\072. 수사기관\2021\기존폴더",
        "folder_display_name": "기존폴더", "folder_link_status": "LINK_VERIFIED",
        "video_exported": "예", "export_pledge": "확인완료",
    }
    path = create_workbook(
        [document], categories, folders,
        {"username": "admin", "created_at": "2026-07-28T16:00:00", "export_type": "selected"},
        include_personal_data=True,
    )
    try:
        with zipfile.ZipFile(path) as archive:
            names = set(archive.namelist())
            workbook_xml = archive.read("xl/workbook.xml").decode("utf-8")
            shared = archive.read("xl/sharedStrings.xml").decode("utf-8")
            sheet = archive.read("xl/worksheets/sheet1.xml").decode("utf-8")
            assert "DB" in workbook_xml and "Metadata" in workbook_xml
            assert all(header in shared for header in HEADERS)
            assert "20210127" in shared and "20210210" in shared
            assert "2021-12" in shared and "2021-16" in shared and "02-501-1659" in shared
            assert "첫째 줄" in shared and "둘째 줄" in shared
            assert "<tablePart" in sheet
            assert "xl/vbaProject.bin" not in names
            assert not any(name.startswith("xl/externalLinks/") for name in names)
            assert "#REF!" not in shared
            assert "xl/worksheets/_rels/sheet1.xml.rels" in names
    finally:
        os.unlink(path)


def test_drive_path_is_safely_converted_to_unc():
    assert drive_path_to_unc(
        r"Y:\공문자료\072. 수사기관\2026\기존폴더",
        r"Y:\공문자료",
        r"\\fileserver\공용디스크\공문자료",
    ) == r"\\fileserver\공용디스크\공문자료\072. 수사기관\2026\기존폴더"
    with pytest.raises(UnsafeArchivePath):
        drive_path_to_unc(
            r"Y:\공문자료2\외부폴더",
            r"Y:\공문자료",
            r"\\fileserver\공용디스크\공문자료",
        )
