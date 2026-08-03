import calendar
from datetime import date
import holidays

COUNTRIES = (("KR", "한국", "ko"), ("CN", "중국", "en_US"), ("JP", "일본", "en_US"), ("TW", "대만", "en_US"), ("MN", "몽골", "en_US"))
COUNTRY_CODES = {code for code, _, _ in COUNTRIES} | {"ETC"}

def build_calendar(year, country=""):
    year = min(2028, max(2026, int(year)))
    selected_country = str(country or "").strip().upper()
    if selected_country not in COUNTRY_CODES:
        selected_country = ""
    events = {}
    for code, label, language in COUNTRIES:
        if selected_country and selected_country != code:
            continue
        for day, name in holidays.country_holidays(code, years=year, language=language).items():
            events.setdefault(day.isoformat(), []).append({"code": code, "country": label, "name": name})
    if not selected_country or selected_country == "ETC":
        for month, day, name in ((1, 1, "신정"), (12, 25, "크리스마스")):
            events.setdefault(date(year, month, day).isoformat(), []).append({"code": "ETC", "country": "기타", "name": name})
    cal, months = calendar.Calendar(firstweekday=6), []
    for month in range(1, 13):
        weeks = [[{"day": item.day, "date": item.isoformat(), "in_month": item.month == month, "events": events.get(item.isoformat(), [])} for item in week] for week in cal.monthdatescalendar(year, month)]
        months.append({"month": month, "weeks": weeks})
    return {"year": year, "months": months, "provisional": year >= 2027, "selected_country": selected_country}
