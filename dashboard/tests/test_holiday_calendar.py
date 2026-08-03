from services import holiday_calendar

def test_holiday_calendar_contains_all_country_groups():
    result = holiday_calendar.build_calendar(2026)
    assert len(result["months"]) == 12
    codes = {event["code"] for month in result["months"] for week in month["weeks"] for day in week for event in day["events"]}
    assert {"KR", "CN", "JP", "TW", "MN", "ETC"}.issubset(codes)


def test_holiday_calendar_filters_one_country():
    result = holiday_calendar.build_calendar(2026, "JP")
    codes = {event["code"] for month in result["months"] for week in month["weeks"] for day in week for event in day["events"]}
    assert codes == {"JP"}
    assert result["selected_country"] == "JP"


def test_holiday_calendar_rejects_unknown_country():
    result = holiday_calendar.build_calendar(2026, "UNKNOWN")
    assert result["selected_country"] == ""
