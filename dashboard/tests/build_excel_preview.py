"""시각 검증용 공문 대장 샘플 생성기."""

from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from dashboard_db import schema
from services.official_excel_export import create_workbook


output = Path(__file__).resolve().parent / "_artifacts"
output.mkdir(exist_ok=True)
connection = schema.connect(":memory:")
categories = [
    dict(row) for row in connection.execute(
        "SELECT * FROM official_doc_reference_values WHERE kind='category' ORDER BY sort_order"
    )
]
folders = [
    dict(row) for row in connection.execute(
        "SELECT * FROM official_doc_reference_values WHERE kind='folder_category' ORDER BY sort_order"
    )
]
documents = [{
    "receipt_number": "2026-12",
    "manager": "홍길동",
    "receipt_date": "2026-07-28",
    "organization": "서울세관",
    "case_name": "한국인 고객 게임기록",
    "request_content": "김고객 게임내역 및 외환거래 기록 요청\n2026년 7월 자료 일체",
    "special_note": "회신기한 확인 필요",
    "requester": "김담당",
    "contact": "02-501-1659",
    "email": "myjung17@korea.kr",
    "dispatch_number": "2026-16",
    "reply_date": "2026-08-03",
    "location": r"\\fileserver\공용디스크\공문자료\072. 수사기관\2026\2026.07.28_서울세관_게임기록",
    "normalized_unc_path": r"\\fileserver\공용디스크\공문자료\072. 수사기관\2026\2026.07.28_서울세관_게임기록",
    "folder_display_name": "2026.07.28_서울세관_게임기록",
    "folder_link_status": "LINK_VERIFIED",
    "video_exported": "예",
    "export_pledge": "확인완료",
}]
temporary = create_workbook(
    documents, categories, folders,
    {"username": "admin", "created_at": "2026-07-28 16:30", "export_type": "검증 샘플"},
    include_personal_data=True,
)
target = output / "official_documents_excel_preview.xlsx"
Path(temporary).replace(target)
print(target)
