from dashboard_db import queries
from services import assembly_bill_client


class FakeResponse:
    status_code = 200

    def json(self):
        return {
            "ALLBILLV2": [
                {"head": [{"list_total_count": 1}]},
                {"row": [{
                    "BILL_ID": "BILL-1",
                    "BILL_NO": "2200001",
                    "ERACO": "제22대",
                    "BILL_NM": "관광진흥법 일부개정법률안",
                    "PPSR_NM": "홍길동의원 등 10인",
                    "PPSL_DT": "20260729",
                    "PROC_STAGE_CD": "위원회 심사",
                    "LINK_URL": "https://example.test/bill/1",
                }]},
            ]
        }


def test_search_and_normalize_bill(monkeypatch):
    monkeypatch.setattr("config.ASSEMBLY_API_KEY", "test-key")
    monkeypatch.setattr(
        "services.assembly_bill_client.get_with_hard_timeout",
        lambda *args, **kwargs: FakeResponse(),
    )

    result = assembly_bill_client.search_bills("관광진흥법")
    bill = assembly_bill_client.normalize_bill(result["bills"][0], "관광진흥법")

    assert result["ok"] is True
    assert bill["bill_id"] == "BILL-1"
    assert bill["bill_name"] == "관광진흥법 일부개정법률안"
    assert bill["matched_keyword"] == "관광진흥법"


def test_bill_upsert_preserves_single_row(db_connection):
    bill = {
        "bill_id": "BILL-1",
        "bill_no": "2200001",
        "era": "제22대",
        "bill_kind": "법률안",
        "bill_name": "관광진흥법 일부개정법률안",
        "process_stage": "접수",
        "matched_keyword": "관광진흥법",
    }
    assert queries.upsert_legislative_bill(db_connection, bill) is True
    bill["process_stage"] = "위원회 심사"
    assert queries.upsert_legislative_bill(db_connection, bill) is False

    rows = queries.list_legislative_bills(db_connection)
    assert len(rows) == 1
    assert rows[0]["process_stage"] == "위원회 심사"
