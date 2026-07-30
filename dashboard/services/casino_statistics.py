"""Historical casino industry statistics sourced from the 2026-04 status report."""

from __future__ import annotations


VISITOR_HISTORY = (
    (1994, 3580024, 625865, 17.5, -3.8), (1995, 3753197, 633174, 16.9, 1.2),
    (1996, 3683779, 517672, 14.1, -18.2), (1997, 3908140, 518178, 13.1, 0.1),
    (1998, 4250216, 689254, 16.0, 33.0), (1999, 4659785, 694899, 14.9, 0.8),
    (2000, 5321792, 636005, 12.0, -8.4), (2001, 5147204, 626851, 12.1, -1.4),
    (2002, 5347468, 647722, 12.1, 3.3), (2003, 4752762, 630474, 13.2, -2.6),
    (2004, 5818138, 677145, 11.6, 7.4), (2005, 6022752, 574094, 9.5, -15.2),
    (2006, 6155046, 988718, 16.0, 72.2), (2007, 6448240, 1176338, 18.2, 19.0),
    (2008, 6890841, 1276772, 18.5, 8.5), (2009, 7817533, 1676207, 21.4, 31.2),
    (2010, 8797658, 1945819, 22.1, 16.0), (2011, 9794796, 2100698, 21.4, 8.0),
    (2012, 11140028, 2384214, 21.4, 13.5), (2013, 12175550, 2707315, 22.2, 13.6),
    (2014, 14201516, 2961833, 20.9, 9.4), (2015, 13231651, 2613620, 19.8, -11.8),
    (2016, 17241823, 2362544, 13.7, -9.6), (2017, 13335758, 2216459, 16.6, -6.2),
    (2018, 15346879, 2839017, 18.5, 28.1), (2019, 17502756, 3233761, 18.5, 13.9),
    (2020, 2519118, 1160967, 46.1, -64.1), (2021, 967003, 708571, 73.3, -39.0),
    (2022, 3198017, 1105293, 34.6, 56.0), (2023, 11031665, 2067084, 18.7, 87.0),
    (2024, 16369629, 2944457, 18.0, 42.4), (2025, 18936562, 3494051, 18.5, 18.7),
)

REVENUE_HISTORY = (
    (1994, 3316500, 13.2, 250763, 44.8, 7.6), (1995, 5060200, 52.6, 286342, 14.2, 5.7),
    (1996, 4855400, -4.0, 265560, -7.2, 5.5), (1997, 4710200, -3.0, 243013, -8.5, 5.2),
    (1998, 6865400, 45.8, 203877, -16.1, 2.9), (1999, 6801900, -0.9, 251787, 23.5, 3.7),
    (2000, 6811300, 0.1, 301153, 20.0, 4.4), (2001, 6370700, -6.5, 296355, -0.8, 4.6),
    (2002, 5915000, -7.2, 327075, 10.4, 5.5), (2003, 5339900, -9.7, 334335, 2.2, 6.3),
    (2004, 6049300, 13.3, 378576, 13.2, 6.3), (2005, 5785100, -4.4, 423413, 11.8, 7.3),
    (2006, 5689000, -1.7, 501928, 18.5, 8.8), (2007, 6057600, 6.5, 659634, 31.4, 10.9),
    (2008, 9680500, 59.8, 684263, 3.7, 7.1), (2009, 9737000, 0.6, 720520, 5.3, 7.4),
    (2010, 10225400, 5.0, 869679, 20.5, 8.5), (2011, 12233900, 19.6, 1015982, 16.8, 8.3),
    (2012, 13201100, 7.9, 1110244, 9.3, 8.4), (2013, 14288400, 8.2, 1250093, 12.6, 8.7),
    (2014, 17335900, 21.3, 1307776, 4.6, 7.5), (2015, 14675800, -15.3, 1098778, -16.0, 7.5),
    (2016, 16753900, 14.2, 1099266, 0.04, 6.6), (2017, 13263900, -20.8, 1066442, -3.0, 8.0),
    (2018, 18461800, 39.2, 1477265, 38.5, 8.0), (2019, 20744900, 12.4, 1243280, -15.9, 6.0),
    (2020, 10984000, -47.1, 506559, -59.3, 4.6), (2021, 11335100, 3.2, 353659, -30.2, 3.1),
    (2022, 13021500, 14.9, 552063, 56.1, 4.2), (2023, 16214200, 24.5, 1077858, 95.2, 6.6),
    (2024, 19131300, 18.0, 1362100, 26.4, 7.1), (2025, 21887700, 14.4, 1590760, 16.8, 7.3),
)

FUND_YEARS = tuple(range(2016, 2026))
FUND_ROWS = (
    ("파라다이스 워커힐", (33927, 26612, 29081, 28583, 16865, 13876, 15334, 34908, 32322, 33683), "육지"),
    ("세븐럭 강남코엑스", (22915, 19349, 18974, 18261, 8109, 2648, 13518, 18674, 17481, 20021), "육지"),
    ("세븐럭 서울드래곤시티", (21466, 20181, 19751, 21606, 7239, 4258, 9645, 14628, 14908, 14527), "육지"),
    ("세븐럭 부산롯데", (8081, 7999, 7896, 7824, 1634, 446, 1734, 4812, 5359, 6365), "육지"),
    ("파라다이스 부산", (9616, 6699, 6410, 7093, 1928, 1161, 2393, 4160, 5750, 5267), "육지"),
    ("파라다이스시티", (9048, 17046, 24401, 37152, 12153, 8146, 15299, 32373, 41729, 48001), "육지"),
    ("인스파이어", (None, None, None, None, None, None, None, None, 16792, 28061), "육지"),
    ("알펜시아", (None, 0.4, 2, 2, 0.3, None, None, None, None, None), "육지"),
    ("인터불고대구", (1133, 1173, 1094, 1532, 1139, 1316, 1670, 1662, 1589, 1474), "육지"),
    ("육지지역 외국인전용 계", (106186, 99059, 107609, 120521, 49067, 31851, 59593, 111217, 135930, 157399), "소계"),
    ("제주완리", (229, 2736, 3268, 2679, 435, 9.9, None, 19, 324, None), "제주"),
    ("드림타워", (1884, 959, 177, 193, 27, 2414, 5981, 18430, 31492, 51525), "제주"),
    ("파라다이스 제주", (4983, 2729, 1920, 3503, 451, 55, 112, 941, 1109, 1850), "제주"),
    ("블루원", (90, 367, 393, 372, 55, None, None, 7.2, 9, 3), "제주"),
    ("레스에이", (2621, 3514, 37941, 5705, 3695, 1097, 644, 1786, 6390, 4879), "제주"),
    ("제주오리엔탈", (1517, 1442, 822, 1140, 20, None, None, 67, 8, 6), "제주"),
    ("세븐스타", (1999, 580, 1044, 343, 118, None, 8.5, 2049, 3819, 3555), "제주"),
    ("골드마운틴", (562, 1133, 1581, 1250, 0.4, None, None, 2.0, 3, 253), "제주"),
    ("제주지역 외국인전용 계", (13885, 13460, 47146, 15185, 4801, 3576, 6745, 23301, 43154, 62071), "소계"),
    ("외국인전용 합계", (120071, 112519, 154755, 135706, 53868, 35427, 66338, 134518, 179084, 219470), "합계"),
    ("강원랜드", (162221, 151770, 139468, 147615, 43815, 76960, 121806, 131482, 135874, 142626), "내국인"),
    ("총계", (282292, 264289, 294223, 283321, 97683, 112387, 188144, 266000, 314958, 362096), "총계"),
)


def _polyline(values, width=920, height=260, pad=24, maximum=None):
    maximum = maximum or max(value for value in values if value is not None)
    usable_width = width - pad * 2
    usable_height = height - pad * 2
    count = max(len(values) - 1, 1)
    return " ".join(
        f"{pad + index * usable_width / count:.1f},{height - pad - (value or 0) / maximum * usable_height:.1f}"
        for index, value in enumerate(values)
    )


def _chart_points(values, years, width=920, height=260, pad=24, maximum=None):
    maximum = maximum or max(value for value in values if value is not None)
    usable_width = width - pad * 2
    usable_height = height - pad * 2
    count = max(len(values) - 1, 1)
    return [
        {
            "year": year,
            "value": value,
            "x": round(pad + index * usable_width / count, 1),
            "y": round(height - pad - (value or 0) / maximum * usable_height, 1),
        }
        for index, (year, value) in enumerate(zip(years, values))
        if value is not None
    ]


def _year_ticks(years, width=920, pad=24):
    interval = 5 if len(years) >= 20 else 2
    count = max(len(years) - 1, 1)
    usable_width = width - pad * 2
    return [
        {
            "year": year,
            "x": round(pad + index * usable_width / count, 1),
        }
        for index, year in enumerate(years)
        if year % interval == 0 or year == years[-1]
    ]


def build_visitors() -> dict:
    rows = [
        {"year": year, "foreign_visitors": foreign, "casino_visitors": casino,
         "share": share, "growth": growth}
        for year, foreign, casino, share, growth in VISITOR_HISTORY
    ]
    maximum = max(row["foreign_visitors"] for row in rows)
    years = [row["year"] for row in rows]
    foreign_values = [row["foreign_visitors"] for row in rows]
    casino_values = [row["casino_visitors"] for row in rows]
    share_values = [row["share"] for row in rows]
    return {
        "rows": rows,
        "latest": rows[-1],
        "foreign_points": _polyline(foreign_values, maximum=maximum),
        "casino_points": _polyline(casino_values, maximum=maximum),
        "share_points": _polyline(share_values, height=150),
        "foreign_chart_points": _chart_points(foreign_values, years, maximum=maximum),
        "casino_chart_points": _chart_points(casino_values, years, maximum=maximum),
        "share_chart_points": _chart_points(share_values, years, height=150),
        "year_ticks": _year_ticks(years),
        "share_year_ticks": _year_ticks(years),
    }


def build_revenue() -> dict:
    rows = [
        {"year": year, "tourism_income": tourism, "tourism_growth": tourism_growth,
         "casino_income": casino, "casino_growth": casino_growth, "share": share}
        for year, tourism, tourism_growth, casino, casino_growth, share in REVENUE_HISTORY
    ]
    maximum = max(row["tourism_income"] for row in rows)
    years = [row["year"] for row in rows]
    tourism_values = [row["tourism_income"] for row in rows]
    casino_values = [row["casino_income"] for row in rows]
    share_values = [row["share"] for row in rows]
    return {
        "rows": rows,
        "latest": rows[-1],
        "tourism_points": _polyline(tourism_values, maximum=maximum),
        "casino_points": _polyline(casino_values, maximum=maximum),
        "share_points": _polyline(share_values, height=150),
        "tourism_chart_points": _chart_points(tourism_values, years, maximum=maximum),
        "casino_chart_points": _chart_points(casino_values, years, maximum=maximum),
        "share_chart_points": _chart_points(share_values, years, height=150),
        "year_ticks": _year_ticks(years),
        "share_year_ticks": _year_ticks(years),
    }


def build_fund() -> dict:
    rows = [
        {"name": name, "values": values, "category": category}
        for name, values, category in FUND_ROWS
    ]
    lookup = {row["name"]: row["values"] for row in rows}
    maximum = max(lookup["총계"])
    years = list(FUND_YEARS)
    return {
        "years": FUND_YEARS,
        "rows": rows,
        "latest": {
            "foreign_only": lookup["외국인전용 합계"][-1],
            "kangwon": lookup["강원랜드"][-1],
            "total": lookup["총계"][-1],
        },
        "foreign_points": _polyline(lookup["외국인전용 합계"], maximum=maximum),
        "kangwon_points": _polyline(lookup["강원랜드"], maximum=maximum),
        "total_points": _polyline(lookup["총계"], maximum=maximum),
        "foreign_chart_points": _chart_points(
            lookup["외국인전용 합계"], years, maximum=maximum
        ),
        "kangwon_chart_points": _chart_points(
            lookup["강원랜드"], years, maximum=maximum
        ),
        "total_chart_points": _chart_points(
            lookup["총계"], years, maximum=maximum
        ),
        "year_ticks": _year_ticks(years),
    }
