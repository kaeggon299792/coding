from services import holiday_calendar

def test_holiday_calendar_contains_all_country_groups():
    result = holiday_calendar.build_calendar(2026)
    assert len(result["months"]) == 12
    codes = {event["code"] for month in result["months"] for week in month["weeks"] for day in week for event in day["events"]}
    assert {"KR", "CN", "JP", "TW", "MN", "ETC"}.issubset(codes)
