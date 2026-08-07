"""Admin-facing inventory and execution evidence for external scheduled tasks."""

from __future__ import annotations

from pathlib import Path

import config
from dashboard_db import queries
from services import automation_settings, news_reader


VERIFIED_AT = "2026-08-06"


TASKS = (
    {
        "key": "law_sync",
        "title": "법령·정부자료 통합 갱신",
        "location": "PythonAnywhere",
        "kind": "Scheduled",
        "schedule": "매일 21:00 KST",
        "platform_schedule": "12:00 UTC",
        "command": "scheduler/sync_law_updates.py",
        "run_type": "law_sync",
        "log_name": "law_sync",
        "source": "국가법령정보센터, 국회 의안정보, 정부 공지, 경제·시장 공개자료",
        "process": "등록된 법령의 원문과 이전 해시를 비교하고, 변경된 경우에만 AI 요약을 실행합니다.",
        "destination": "법률·규제 화면과 dashboard.db, 중요 변경 텔레그램 알림",
        "failure": "해당 실행만 실패하며 기존 저장 데이터는 유지됩니다.",
    },
    {
        "key": "daily_insight",
        "title": "일일 경영 시사점·해외뉴스·영문 번역",
        "location": "PythonAnywhere",
        "kind": "Scheduled",
        "schedule": "매일 21:05 KST",
        "platform_schedule": "12:05 UTC",
        "command": "scheduler/daily_insight_batch.py",
        "run_type": "daily_insight",
        "log_name": "daily_insight_batch",
        "source": "오늘의 중요 뉴스, 공문, 데이터랩 실적, 최근 리서치, 해외뉴스 RSS",
        "process": "하루 한 번 자료를 묶어 경영 시사점을 만들고 해외뉴스와 공개 콘텐츠 번역도 갱신합니다.",
        "destination": "경영 시사점·해외뉴스·영문 화면과 dashboard.db",
        "failure": "영역별 오류를 따로 기록하며 기존 결과는 삭제하지 않습니다.",
    },
    {
        "key": "dart_sync",
        "title": "관심기업 DART 공시 수집",
        "location": "PythonAnywhere",
        "kind": "Scheduled",
        "schedule": "매시간 30분 KST",
        "platform_schedule": "Hourly · 30 mins past",
        "command": "scheduler/sync_dart_disclosures.py",
        "run_type": "dart_sync",
        "log_name": "dart_sync",
        "source": "OpenDART의 파라다이스·GKL·강원랜드·롯데관광개발 공시",
        "process": "최근 공시를 중복 없이 가져오고 신규 공시를 AI로 요약·분류합니다.",
        "destination": "기업별 공시 화면과 dashboard.db, 중요 공시 텔레그램 알림",
        "failure": "실패한 기업만 기록하고 다음 시간에 다시 확인합니다.",
    },
    {
        "key": "tourism_stats_sync",
        "title": "방한 외래관광객 통계",
        "location": "PythonAnywhere",
        "kind": "Scheduled",
        "schedule": "매일 15:27 KST",
        "platform_schedule": "06:27 UTC",
        "command": "scheduler/sync_tourism_stats.py",
        "run_type": "tourism_stats_sync",
        "log_name": "tourism_stats_sync",
        "source": "한국관광 데이터의 월별 국가·지역별 방한객 통계",
        "process": "최신 발표 월을 찾고 올해·전년 자료 중 새 항목과 최근 2개월을 갱신합니다.",
        "destination": "시장 정보의 관광객 통계와 dashboard.db",
        "failure": "실패 월을 기록하고 이미 저장된 월은 유지합니다.",
    },
    {
        "key": "salary_sync",
        "title": "카지노 4사 연봉·기업평점",
        "location": "PythonAnywhere",
        "kind": "Scheduled",
        "schedule": "매일 06:10 KST",
        "platform_schedule": "전일 21:10 UTC",
        "command": "scheduler/sync_salary_data.py",
        "run_type": "salary_sync",
        "log_name": "salary_sync",
        "source": "잡코리아·OpenBizData·잡플래닛의 공개 기업정보 원문",
        "process": "카지노 4사의 평균연봉과 비교 가능한 공개 평점을 읽어 스냅샷으로 저장합니다.",
        "destination": "기업정보의 연봉·평점 화면과 dashboard.db",
        "failure": "가져온 기업만 갱신하고 실패 기업의 기존 값은 유지합니다.",
    },
    {
        "key": "recruitment_sync",
        "title": "카지노 4사 채용공고",
        "location": "PythonAnywhere",
        "kind": "Scheduled",
        "schedule": "6시간 간격 (03:20·09:20·15:20·21:20 KST)",
        "platform_schedule": "6시간 간격 (00:20·06:20·12:20·18:20 UTC)",
        "command": "scheduler/sync_recruitment_jobs.py",
        "run_type": "recruitment_sync",
        "log_name": "recruitment_sync",
        "source": "인스파이어·파라다이스 공식 채용 사이트와 기존 공개 채용 검색",
        "process": "신규 공고를 중복 없이 저장하고 새 공고만 제한적으로 AI 분석합니다.",
        "destination": "기업정보의 채용정보 화면과 dashboard.db",
        "failure": "수집 가능한 공고만 반영하고 기존 공고는 유지합니다.",
    },
    {
        "key": "localization_translation",
        "title": "일본어·광둥어 자동 번역",
        "location": "PythonAnywhere",
        "kind": "Scheduled",
        "schedule": "매일 23:30 KST",
        "platform_schedule": "14:30 UTC",
        "command": "scheduler/translate_localization.py",
        "log_name": "localization_translation",
        "signal": "translation",
        "source": "Localization에 새로 발견된 한국어 원문과 언어별 용어집",
        "process": "미완료 항목만 묶어 OpenAI로 번역하고 숫자·URL·HTML·placeholder를 검사합니다.",
        "destination": "기존 localization_translations 테이블의 일본어·광둥어 번역",
        "failure": "검증 실패 문장은 저장하지 않고 다음 날 다시 처리하며 일일 비용 한도에서 중단됩니다.",
    },
    {
        "key": "email_monitor",
        "title": "업무 이메일 모니터",
        "location": "PythonAnywhere",
        "kind": "Always-on",
        "schedule": "상시 실행 · 장애 시 자동 재시작",
        "platform_schedule": "PythonAnywhere Always-on",
        "command": "/home/kaekun/email_monitor/run_forever.py",
        "signal": "email_db",
        "source": "설정된 업무 이메일 계정의 신규 메일",
        "process": "신규 메일을 주기적으로 확인하고 기존 email_monitor 프로그램 규칙으로 처리합니다.",
        "destination": "email_monitor.db 및 연결된 알림",
        "failure": "프로세스가 종료되면 PythonAnywhere가 다시 시작합니다.",
    },
    {
        "key": "casino_news_watch",
        "title": "카지노 뉴스 모니터",
        "location": "PythonAnywhere",
        "kind": "Always-on",
        "schedule": "상시 실행 · 장애 시 자동 재시작",
        "platform_schedule": "PythonAnywhere Always-on",
        "command": "/home/kaekun/casino_news_watch/always_on_runner.py",
        "signal": "news",
        "source": "casino_news_watch에 설정된 국내외 뉴스·검색 출처",
        "process": "기사를 주기적으로 수집하고 중복 제거·분류·중요도 분석을 수행합니다.",
        "destination": "news_history.db; CASINO IN은 읽기 전용으로 표시",
        "failure": "프로세스가 종료되면 PythonAnywhere가 다시 시작하며 대시보드는 기존 뉴스를 유지합니다.",
    },
    {
        "key": "telegram_ingest",
        "title": "데이터랩 텔레그램 실적 수신",
        "location": "PythonAnywhere",
        "kind": "Always-on",
        "schedule": "상시 실행 · 기본 60초 간격",
        "platform_schedule": "PythonAnywhere Always-on",
        "command": "scheduler/poll_telegram_performance.py",
        "log_name": "telegram_ingest",
        "signal": "performance",
        "source": "로컬 데이터랩 작업이 텔레그램 봇으로 보낸 실적 메시지",
        "process": "getUpdates로 새 메시지만 받아 실적 항목과 숫자를 파싱합니다.",
        "destination": "경영 실적 화면과 dashboard.db",
        "failure": "한 번의 오류로 종료하지 않고 다음 폴링 주기에 다시 시도합니다.",
    },
    {
        "key": "local_board_watch",
        "title": "Brity 게시판 알림",
        "location": "로컬 PC",
        "kind": "Windows Task Scheduler · 17개",
        "schedule": "매일 06:00~22:00, 매시 정각",
        "platform_schedule": "Brity 게시판 카카오 알림_06시 ~ _22시",
        "command": r"C:\Automation\BrityBoardWatch\board_watch.py",
        "source": "Brity Works에 지정된 여러 게시판의 글 목록·본문·첨부파일",
        "process": "저장된 로그인 세션으로 신규·수정 글을 비교하고 중복 알림을 막습니다.",
        "destination": "카카오 알림, 필요한 첨부파일은 텔레그램, 로컬 state.json·로그",
        "failure": "PC가 꺼져 있거나 세션이 만료되면 실행되지 않으며 서버가 직접 재시작할 수 없습니다.",
    },
    {
        "key": "local_datalab",
        "title": "Brity 데이터랩 실적 캡처",
        "location": "로컬 PC",
        "kind": "Windows Task Scheduler · 10개",
        "schedule": "매일 08:30, 09:00, 09:15, 09:30, 09:45, 10:00, 10:15, 10:30, 10:45, 11:00",
        "platform_schedule": "Brity 데이터랩 카카오 알림_8시30분 ~ _11시",
        "command": r"C:\Automation\BrityBoardWatch\datalab_capture.py",
        "signal": "performance",
        "source": "Brity SSO를 거쳐 접속한 사내 데이터랩 주요지표 화면",
        "process": "화면을 캡처하고 그룹·카지노·호텔 실적 숫자를 읽어 이전 이미지와 비교합니다.",
        "destination": "카카오·텔레그램 알림과 CASINO IN 경영실적 수신 경로",
        "failure": "PC 전원·사내망·로그인 세션에 의존하며, 실패 시 서버에는 새 실적이 도착하지 않습니다.",
    },
)


EXECUTION_META = {
    "law_sync": {
        "mode": "묶음 실행",
        "steps": [
            "법령 원문 변경 확인",
            "국회 관련 의안 수집",
            "정부 입법예고 수집",
            "미분석 의안 AI 분석",
            "국내외 시장 시세 갱신",
            "유가·환율 갱신",
        ],
    },
    "daily_insight": {
        "mode": "묶음 실행",
        "steps": [
            "오늘의 경영 시사점 생성",
            "마카오·일본 해외뉴스 수집 및 분석",
            "공개 콘텐츠 영어 번역 갱신",
        ],
    },
    "dart_sync": {"mode": "단독 실행", "steps": ["관심기업 DART 공시 수집·분석"]},
    "tourism_stats_sync": {"mode": "단독 실행", "steps": ["방한 외래관광객 통계 갱신"]},
    "salary_sync": {"mode": "단독 실행", "steps": ["카지노 4사 연봉·평점 갱신"]},
    "recruitment_sync": {"mode": "단독 실행", "steps": ["카지노 4사 채용공고 수집·분석"]},
    "localization_translation": {"mode": "단독 실행", "steps": ["일본어 번역", "광둥어 번역"]},
    "email_monitor": {"mode": "상시 실행", "steps": ["신규 이메일 반복 확인"]},
    "casino_news_watch": {"mode": "상시 실행", "steps": ["카지노 뉴스 반복 수집·분석"]},
    "telegram_ingest": {"mode": "상시 실행", "steps": ["텔레그램 실적 메시지 반복 수신·파싱"]},
    "local_board_watch": {
        "mode": "동일 스크립트 다중 예약",
        "steps": ["06시부터 22시까지 17개 예약이 같은 board_watch.py를 실행"],
    },
    "local_datalab": {
        "mode": "동일 스크립트 다중 예약",
        "steps": ["08:30부터 11:00까지 10개 예약이 같은 datalab_capture.py를 실행"],
    },
}


def _file_mtime(path):
    try:
        return Path(path).stat().st_mtime
    except OSError:
        return None


def _log_evidence(log_name):
    if not log_name:
        return None
    path = Path(config.LOG_DIR) / f"{log_name}.log"
    timestamp = _file_mtime(path)
    if timestamp is None:
        return None
    from datetime import datetime

    return datetime.fromtimestamp(timestamp, tz=config.KST).isoformat(timespec="seconds")


def _signal(connection, signal):
    if signal == "translation":
        row = connection.execute(
            """SELECT called_at FROM api_usage
               WHERE request_type LIKE 'localization_translation_%'
               ORDER BY called_at DESC LIMIT 1"""
        ).fetchone()
        return row["called_at"] if row else None
    if signal == "performance":
        row = connection.execute(
            "SELECT MAX(received_at) AS value FROM performance_reports"
        ).fetchone()
        return row["value"] if row else None
    if signal == "news":
        return news_reader.last_updated_at()
    if signal == "email_db":
        timestamp = _file_mtime("/home/kaekun/email_monitor/email_monitor.db")
        if timestamp is None:
            return None
        from datetime import datetime

        return datetime.fromtimestamp(timestamp, tz=config.KST).isoformat(timespec="seconds")
    return None


def dashboard(connection):
    managed_settings = automation_settings.get_all(connection)
    items = []
    for definition in TASKS:
        item = dict(definition)
        if definition["location"] == "로컬 PC":
            item["platform"] = "Windows 작업 스케줄러 (현재 로컬 PC)"
        else:
            item["platform"] = "PythonAnywhere Always-on · CASINOINBOT"
            item["managed_by"] = "CASINOINBOT"
            item["kind"] = "CASINOINBOT"
        item.update(EXECUTION_META[definition["key"]])
        item["connection_note"] = {
            "local_datalab": (
                "플랫폼 연결: 로컬 PC가 실적을 텔레그램·대시보드로 전송하고, "
                "PythonAnywhere의 '데이터랩 텔레그램 실적 수신'이 받아 저장합니다."
            ),
            "telegram_ingest": (
                "플랫폼 연결: 이 작업 자체는 PythonAnywhere에서 실행되지만, "
                "원본 실적은 로컬 PC의 데이터랩 캡처 작업이 만듭니다."
            ),
        }.get(definition["key"])
        latest = (
            queries.get_latest_completed_run(connection, definition["run_type"])
            if definition.get("run_type")
            else None
        )
        item["last_status"] = latest["status"] if latest else None
        item["last_run_at"] = latest["finished_at"] if latest else None
        item["last_error"] = (latest.get("error_message") or "")[:240] if latest else ""
        item["last_signal_at"] = _signal(connection, definition.get("signal"))
        item["last_log_at"] = _log_evidence(definition.get("log_name"))
        item["verified_at"] = VERIFIED_AT
        item["settings"] = managed_settings.get(definition["key"])
        items.append(item)
    return {
        "items": items,
        "pythonanywhere": [item for item in items if item["location"] == "PythonAnywhere"],
        "local": [item for item in items if item["location"] == "로컬 PC"],
        "counts": {
            "pythonanywhere_scheduled": 0,
            "pythonanywhere_always_on": 1,
            "windows_registered": 27,
        },
        "verified_at": VERIFIED_AT,
    }
