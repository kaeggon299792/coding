# 경영기획 인텔리전스 대시보드

카지노 뉴스 모니터링(`casino_news_watch`), 이메일 모니터링(`email_monitor`), 회사 인트라넷
"데이터랩" 실적 알림(텔레그램), DART 공시, 법령 변경 정보를 한 화면에서 확인하는 내부
경영기획용 웹 대시보드입니다.

이 프로젝트는 **기존 뉴스/이메일 모니터링 시스템을 전혀 수정하지 않습니다.** 두 시스템의
DB는 읽기 전용으로만 연결하고, 텔레그램은 같은 봇을 재사용하되 발송이 아닌 수신
(`getUpdates`)만 사용합니다.

## 1. 전체 시스템 구조

```
┌─────────────────────┐   ┌──────────────────────┐   ┌─────────────────────────────┐
│ casino_news_watch     │   │ email_monitor          │   │ 회사 PC (사내망 전용)          │
│ (PythonAnywhere,      │   │ (PythonAnywhere,       │   │ datalab_capture.py 등        │
│  Hourly Task)         │   │  Hourly/Always-on)     │   │ (Windows 작업 스케줄러)        │
│ → news_history.db     │   │ → email_monitor.db     │   │ → 같은 텔레그램 봇으로 발송     │
└──────────┬───────────┘   └──────────┬────────────┘   └──────────────┬───────────────┘
           │ 읽기 전용                  │ 읽기 전용                       │ getUpdates(수신)
           ▼                          ▼                                ▼
┌────────────────────────────────────────────────────────────────────────────────────┐
│                         경영기획 인텔리전스 대시보드 (본 프로젝트)                          │
│  Flask 웹앱 + dashboard.db(신규) + DART OpenAPI + 국가법령정보센터 Open API             │
└────────────────────────────────────────────────────────────────────────────────────┘
```

## 2. 디렉터리 구조

```
dashboard/
  app.py                 Flask 엔트리포인트(웹앱)
  config.py               환경변수 로딩
  extensions.py            DB 커넥션 헬퍼(읽기전용 2개 + 대시보드 자체 DB)
  auth/                    로그인/세션/CSRF
  dashboard_db/            대시보드 자체 DB 스키마·쿼리
  services/                뉴스/이메일 리더, 텔레그램 수집·파서, DART/법률 클라이언트, AI
  scheduler/               PythonAnywhere Task로 등록할 배치 진입점들
  templates/, static/      화면
  tests/                   pytest(외부 API 미호출)
  manage.py                계정/관심기업/모니터링법령 관리 CLI
```

## 3. 로컬 실행

```bash
cd dashboard
python3 -m venv venv && source venv/bin/activate
pip install -r requirements-dev.txt

cp .env.example .env
# .env를 열어 최소한 FLASK_SECRET_KEY, DASHBOARD_DB_FILE, NEWS_DB_FILE,
# TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID를 채운다.
# python -c "import secrets; print(secrets.token_hex(32))" 로 FLASK_SECRET_KEY 생성

python manage.py create-user admin   # 최초 관리자 계정 생성(대화형으로 비밀번호 입력)
python app.py                         # http://localhost:5001
```

테스트:

```bash
pytest tests/ -v
```

## 4. 환경변수 목록

`.env.example` 참고. 실제 값은 `.env`에만 넣고 절대 git에 커밋하지 않습니다(`.gitignore`에
이미 포함되어 있습니다). 주요 변수:

| 변수 | 설명 |
|---|---|
| `FLASK_SECRET_KEY` | 세션 서명 키 |
| `DASHBOARD_DB_FILE` | 대시보드 자체 SQLite 파일 경로 |
| `NEWS_DB_FILE` | `casino_news_watch/news_history.db`의 **절대경로** (읽기 전용) |
| `TELEGRAM_BOT_TOKEN` / `TELEGRAM_CHAT_ID` | 기존 세 프로그램과 동일한 봇/챗 |
| `TELEGRAM_ALERT_DRY_RUN` | 대시보드가 새로 보내는 "중요 공시/법령변경 긴급알림" 스위치. 처음엔 반드시 `true` |
| `OPENAI_API_KEY` / `OPENAI_INSIGHT_MODEL` | 경영진 시사점/공시분석/법률분석 공통 |
| `DART_API_KEY` | https://opendart.fss.or.kr 에서 무료 발급 |
| `LAW_API_OC` / `LAW_API_KEY` | https://open.law.go.kr 에서 무료 발급 |

## 5. DB 마이그레이션

`extensions.dashboard_db()`(또는 `dashboard_db/schema.py`의 `connect()`)를 호출할 때마다
`migrate()`가 자동 실행되어 `CREATE TABLE IF NOT EXISTS` + `ALTER TABLE ADD COLUMN`(멱등)으로
스키마를 최신 상태로 맞춥니다. 별도의 수동 마이그레이션 스크립트가 필요 없습니다.

`news_history.db`는 **절대 이 프로젝트가 마이그레이션하지 않습니다** —
읽기 전용 URI(`file:...?mode=ro`)로만 연결되어 물리적으로 쓰기가 불가능합니다.

## 6. 초기 설정 (관심기업 / 모니터링 법령)

```bash
# DART 관심기업 등록 (corp_code는 opendart.fss.or.kr에서 회사명으로 검색해 확인)
python manage.py add-company 파라다이스 <DART고유번호>
python manage.py add-company GKL <DART고유번호>
python manage.py add-company 강원랜드 <DART고유번호>
python manage.py add-company 롯데관광개발 <DART고유번호>
python manage.py list-companies

# 모니터링 법령 기본 목록 일괄 등록(관광진흥법 등, config.py의 DEFAULT_MONITORED_LAWS 참고)
python manage.py seed-default-laws
```

## 7. PythonAnywhere 배포

1. Bash 콘솔에서 이 저장소를 clone(또는 git pull)합니다.
2. 가상환경 생성 및 설치:
   ```bash
   mkvirtualenv mgmt-dashboard --python=python3.11
   pip install -r dashboard/requirements.txt
   ```
3. `dashboard/.env`를 서버에 직접 생성하고 값을 채웁니다(레포에 커밋하지 마세요).
4. **Web** 탭에서 새 웹앱을 추가하고 WSGI 파일에서 `dashboard/app.py`의 `app` 객체를 가리키도록
   설정합니다(기존 portfolio 웹앱과는 별도의 웹앱/서브도메인으로 분리).
5. `python manage.py create-user <아이디>`로 최초 관리자 계정을 만듭니다.
6. 먼저 `TELEGRAM_ALERT_DRY_RUN=true`, DART/법률 키 없이 웹앱만 켜서 뉴스 읽기 전용
   연동이 정상인지 확인합니다.

## 8. 스케줄 작업 등록

| 스크립트 | 등록 방식 | 주기 |
|---|---|---|
| `scheduler/poll_telegram_performance.py` | **Always-on Task** | 상시(내부적으로 60초 간격 폴링) |
| `scheduler/sync_dart_disclosures.py` | Scheduled Task | 평일 업무시간 1시간 간격 |
| `scheduler/sync_law_updates.py` | Scheduled Task | 1일 1회 |
| `scheduler/daily_insight_batch.py` | Scheduled Task | 1일 1회(뉴스 수집 이후) |

등록 명령 예시(PythonAnywhere Tasks 탭):
```bash
/home/사용자명/.virtualenvs/mgmt-dashboard/bin/python3.11 /home/사용자명/coding/dashboard/scheduler/poll_telegram_performance.py
```

## 9. 뉴스 / 공문 / 텔레그램 실적 수집 흐름

- **뉴스**: `casino_news_watch`가 이미 수집·분석해 `news_history.db`의 `articles`/`issues`
  테이블에 저장한 결과를 그대로 읽습니다(`services/news_reader.py`). 대시보드가 직접
  뉴스를 수집하거나 재분석하지 않습니다.
- **공문**: 대시보드 자체 공문·자료관리 DB에서 처리상태와 7일 초과 미처리 건을 읽습니다.
- **실적**: 회사 인트라넷 "데이터랩"은 사내망에서만 접근 가능해 서버에서 원본 데이터에 접근할
  수 없습니다. 대신 로컬 PC의 `datalab_capture.py`가 같은 텔레그램 봇으로 보내는 메시지
  (사진 caption 또는 텍스트)를 `getUpdates`로 수집해 정규식으로 파싱합니다
  (`services/telegram_ingest.py`, `services/performance_parser.py`). **`getUpdates`는 폴링을
  시작한 시점 이후의 메시지만 가져올 수 있어 과거 실적 이력은 소급되지 않습니다.**
  캡션에 없는 지점별 세부 수치(인천/부산/제주 등)는 파싱 대상이 아니며, 향후 스크린샷
  이미지 OCR로 확장할 수 있는 여지만 남겨두었습니다.

## 10. AI 분석 흐름

- 뉴스 자체의 수집·분석 결과는 기존 뉴스 프로그램에서 읽고 대시보드가 재분석하지 않습니다.
- 대시보드가 새로 추가하는 AI 분석 3종(`services/ai_insights.py`)은 모두 하루 실행 주기가
  정해진 배치 스크립트에서만 호출되고, 페이지를 열 때마다 재실행되지 않습니다.
  - 중요 공시 발생 시: 공시 메타데이터 기반 요약(`sync_dart_disclosures.py`)
  - 모니터링 법령 원문 변경 감지 시에만: 법률 변경 요약(`sync_law_updates.py`)
  - 1일 1회: 오늘의 중요 뉴스+이메일+실적을 종합한 경영진 시사점(`daily_insight_batch.py`)
- 모든 AI 호출은 대시보드 자체의 `api_usage` 테이블에 호출량/비용을 기록하고,
  `MAX_GPT_CALLS_PER_DAY`/`DAILY_OPENAI_BUDGET_USD` 한도를 넘으면 자동으로 중단합니다.
- 프롬프트 버전은 `dashboard_analysis_runs.prompt_version`에 기록되어 나중에 어떤 프롬프트로
  생성된 결과인지 추적할 수 있습니다.

## 11. 오류 발생 시 확인 방법

- `dashboard/logs/*.log`: 스케줄 스크립트별 날짜별 로그(비밀값은 자동 마스킹됨).
- `dashboard.db`의 `errors` 테이블: 단계(stage)별 오류 이력.
  ```bash
  sqlite3 dashboard.db "SELECT occurred_at, stage, error_type, error_message FROM errors ORDER BY occurred_at DESC LIMIT 20;"
  ```
- `dashboard_analysis_runs` 테이블: 각 배치 작업의 성공/실패/부분실패 이력과 오류 메시지.
- 뉴스 DB 연결 실패, DART/법률 API 키 미설정 등은 대시보드 전체를 중단시키지 않고
  해당 영역만 "비교 데이터 없음"/빈 목록으로 표시됩니다.

## 12. 백업 및 복원

`dashboard.db`는 SQLite 파일 하나이므로 정지 없이 `sqlite3 dashboard.db ".backup backup.db"`로
백업할 수 있습니다. `news_history.db`/`email_monitor.db`는 이 프로젝트가 전혀 건드리지
않으므로 기존 두 프로그램의 백업 절차를 그대로 따르면 됩니다.

## 13. 이번 패스에서 구현하지 않은 것 (다음 단계)

- 경쟁사별 탭 UI, 이슈 클러스터링 고도화
- 지난주 대비 상세 비교 통계, 신규/지속/확대/완화 이슈 자동 분류
- 통합 검색, 통합 타임라인, 실적 차트/그래프
- DART 공시 원문(XBRL/PDF) 전체 파싱 기반 심층 분석(현재는 메타데이터 기반 요약만)
- 법령의 발의/심사 등 입법 진행 단계 추적(국가법령정보센터 Open API는 공포된 법령만
  제공 — 국회 의안정보시스템 등 별도 API 필요)
- Brity Works 게시판(`board_watch.py`) 연동
- 데이터랩 스크린샷 OCR을 통한 지점별 세부 실적 확장

## 14. 알려진 별도 조치 필요 사항

이번 분석 과정에서 `email_server/app.py`(포트폴리오 문의메일 발송, 이 프로젝트와 무관)에
**네이버 이메일 비밀번호가 코드에 평문으로 하드코딩**되어 있는 것을 발견했습니다. 반드시
해당 비밀번호를 재발급하고 코드를 환경변수 방식으로 수정해주세요(이 저장소 범위 밖의
별도 프로젝트입니다).
# Localization Management System

관리자는 `/admin/localization`에서 프로젝트의 한국어 원문, 언어별 번역,
상태(`Pending`/`Completed`/`Ignored`), 우선순위와 사용 위치를 관리한다. 번역은
외부 API를 호출하지 않으며 코드블록을 원하는 AI에 복사한 뒤 결과를 붙여넣거나
CSV/XLSX로 일괄 반영한다. 새 언어는 관리 화면에서 `language_code`를 추가한다.

정적 UI와 동적 콘텐츠 자동 인벤토리는 다음 명령을 매시간 실행하도록
PythonAnywhere Scheduled Task에 등록한다. 작업은 번역 API를 호출하지 않는다.

```bash
/home/kaekun/.virtualenvs/mgmt-dashboard/bin/python \
  /home/kaekun/coding-dashboard/dashboard/scheduler/sync_localization.py
```

일본어·광둥어 미번역 항목은 매일 23:30(KST)에 다음 Scheduled Task로 증분 번역한다.
기존 완료 번역은 다시 호출하지 않으며, 숫자·날짜·URL·HTML·placeholder 검증을 통과한
결과만 저장한다. 호출 횟수와 비용은 공통 `MAX_GPT_CALLS_PER_DAY` 및
`DAILY_OPENAI_BUDGET_USD` 한도를 적용한다.

```bash
/home/kaekun/.virtualenvs/mgmt-dashboard/bin/python \
  /home/kaekun/coding-dashboard/dashboard/scheduler/translate_localization.py
```

관리 화면의 `Translation Scan`도 같은 비파괴 스캔을 즉시 실행한다. 스캔에서
사라진 참조는 원문을 삭제하지 않고 `deleted_at`으로 보관한다.
