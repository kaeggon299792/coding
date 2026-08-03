# 디자인 시스템 — 포트폴리오(shingoon.me) 통합

이 문서는 `dashboard.shingoon.me`가 `www.shingoon.me`(포트폴리오)와 같은 브랜드로 보이도록
적용한 디자인 시스템을 설명한다. **기능/데이터/인증/API/배포 구조는 이 작업으로 전혀
바뀌지 않았다** — 시각적 레이어(`static/css/dashboard.css`, `templates/*.html`)만 변경됨.

## 1. 토큰 출처

**정정 이력**: 최초 버전(PR #6)은 포트폴리오를 **라이트 테마**로 잘못 판단해 적용했다.
`www.shingoon.me`에 `curl`로 직접 접속해 실제 렌더링되는 HTML/CSS(`/custom.css`,
`/css/tips.css`, `/assets/index-*.css`)를 다시 읽은 결과, 실제로는 **다크 테마**(검정에
가까운 배경 + 오프화이트 텍스트 + 흰색 강조)라는 게 확인되어 이후 커밋에서 전체 팔레트를
반전했다. 최초 조사 때 `:root`에서 발견한 `--foreground-rgb: 255,255,255` /
`--background-start-rgb: 0,0,0`을 "Next.js 보일러플레이트 잔재"로 오판해 무시한 것이
근본 원인 — 실제로는 진짜 사용되는 다크모드 토큰이었다. 아래는 정정된 실측값이다.

색상·폰트 토큰은 `kaeggon299792/portfolio`의 실제 배포 응답(HTML/CSS 원문)에서 직접
추출했다(스크린샷 추측이 아님). 확인된 사실:

- 포트폴리오는 Tailwind CSS 기반, **zinc** 뉴트럴 팔레트를 다크 테마로 사용
  (뚜렷한 채도 높은 브랜드 컬러 없이 사실상 모노크롬 — 검정/화이트/그레이 중심,
  단 배경이 어둡고 텍스트가 밝은 방향).
- 실측 다크 팔레트 (`/css/tips.css`의 `--tips-*` 커스텀 프로퍼티 + 루트 페이지
  `:root`의 `--background-start-rgb`/`--foreground-rgb`):
  | 역할 | 실제 값 |
  |---|---|
  | 배경 | `#09090b` (zinc-950, 루트 페이지는 `#000000`에 더 가까움) |
  | 표면(카드 등) | `#18181b` (zinc-900) |
  | 표면(연한 단차) | `#1f1f23` |
  | 보더 | `#27272a` (zinc-800) |
  | 본문 텍스트 | `#f4f4f5` (zinc-100) |
  | 보조 텍스트 | `#a1a1aa` (zinc-400) |
  | 강조색 | `#ffffff` (흰색 — 다크 배경 위 최고 대비) |
- 본문 폰트: `-apple-system, BlinkMacSystemFont, 'Segoe UI', Pretendard, sans-serif`
  (`/css/tips.css` 원문 그대로 — Google Fonts의 Inter는 로드하지 않고 시스템 기본
  산세리프 + 한글 커버용 Pretendard만 사용. "미니멀 에디토리얼" 리파인 단계에서
  외부 폰트 의존을 줄이기 위해 Inter `<link>`를 제거했다).
- 제목(h1~h3) 폰트: 커스텀 웹폰트 `Trap`(ExtraBold, 800) — `static/fonts/Trap-ExtraBold.woff2`를
  포트폴리오 저장소에서 그대로 복사해 재사용(동일 소유자·동일 브랜드 패밀리). 변경 없음.
- Radius: `/css/tips.css` 원문 실측값은 `4px`~`6px`였지만, 사용자가 별도 프로젝트에서
  이미 확정한 "미니멀 에디토리얼" 규칙에 따라 대시보드에서는 이보다 더 절제해서
  카드/버튼/인풋 모두 `2~3px`만 쓴다(알약형 배지만 예외로 `999px`).
- 그림자(box-shadow)는 전혀 쓰지 않는다 — 카드/패널/로그인 카드 구분은 전부 1px 보더로만
  한다(사용자 지정 규칙).

**한계**: 이 세션의 샌드박스 환경에서 Playwright(Chromium)로 `www.shingoon.me`를 직접
렌더링해 스크린샷 비교하는 것은 여전히 실패한다(프록시 특유의 문제로 추정). 다만 `curl`로는
정상 접속되므로, 이번 정정은 실제 서버가 응답하는 HTML/CSS **원문 텍스트**를 직접 읽어
확인한 것이며, 렌더링된 픽셀을 눈으로 대조한 것은 아니다.

## 2. 토큰 정의 위치

`dashboard/static/css/dashboard.css` 최상단 `:root { ... }` 블록. 예:

```css
--brand-bg: #09090b;             /* zinc-950 */
--brand-text-primary: #f4f4f5;   /* 본문 */
--brand-text-secondary: #a1a1aa; /* 보조 */
--brand-text-muted: #71717a;     /* 흐림/메타(날짜·라벨) */
--brand-accent: #ffffff;         /* 다크 배경 위 흰색 단독 강조색 */
--font-display: 'Trap', -apple-system, BlinkMacSystemFont, 'Segoe UI', Pretendard, sans-serif;
--font-body: -apple-system, BlinkMacSystemFont, 'Segoe UI', Pretendard, sans-serif;
```

텍스트는 3단계(본문/보조/흐림)로만 나눈다 — 더 세분화하지 않는다. 상태색(`--brand-success`
`--brand-warning` `--brand-danger`)은 브랜드 강조색이 아니라 실적 델타·긴급도처럼 순수하게
기능적인 상태 표시에만 쓰고, 배지/알림 박스에 색을 채우지 않고 텍스트·점(dot) 색으로만
표현한다(장식적 색 배지 금지 — 사용자 지정 규칙).

## 3. 강조색을 바꾸려면

`--brand-accent`, `--brand-accent-hover` 두 값만 바꾸면 버튼/활성 네비/포커스 링 전체가
따라간다. 현재는 포트폴리오 실측값(다크 배경 위 흰색 강조)을 그대로 썼다.

## 4. 폰트를 바꾸려면

- 본문: `--font-body` 값 수정, 필요하면 `templates/base.html`의 Google Fonts/Pretendard
  `<link>`도 함께 교체.
- 제목: `--font-display` 값 수정. 새 웹폰트 파일을 쓰려면 `dashboard.css` 상단 `@font-face`
  블록의 `src` 경로를 바꾸고 파일을 `static/fonts/`에 추가.

## 5. 네비게이션 항목 추가

1. `app.py`에 라우트 추가(기존 5개 페이지와 동일한 패턴: `@app.route(...)`, `@login_required`)
2. `templates/_topbar.html`의 `<nav class="topbar-nav">` 안에 `<a href="{{ url_for('새_엔드포인트') }}" {% if request.endpoint == '새_엔드포인트' %}class="active"{% endif %}>메뉴명</a>` 추가

## 6. KPI 카드 추가

`templates/dashboard.html`의 `<div class="kpi-row">` 안에 아래 패턴을 복사:

```html
<div class="kpi-card">
  <div class="label">지표명</div>
  <div class="value">{{ kpis.값 }}</div>
  {% if kpis.값_delta is not none %}
    <div class="delta flat">전일 대비 {{ '%+d'|format(kpis.값_delta) }}%</div>
  {% endif %}
</div>
```

`delta` 클래스는 `favorable`(초록)/`unfavorable`(빨강)/`flat`(회색, 값 증감에 대한 유불리
판단이 불명확한 지표 기본값) 중 하나를 쓴다 — 무조건 상승=초록으로 하지 않는다(스펙 원칙).

## 7. 표 추가

`<table class="data-table">` + `<thead><tr><th>...</th></tr></thead>` + `<tbody>` 패턴을
그대로 재사용. 숫자 컬럼은 `<td class="num">`으로 우측 정렬.

## 8. 반응형/접근성 규칙

- 브레이크포인트: 1024px(2컬럼→1컬럼 섹션), 768px(헤더 줄바꿈, 네비 가로 스크롤),
  480px(KPI 카드 1열)
- 포커스: 모든 인터랙티브 요소에 `:focus-visible` 아웃라인 유지(버튼/입력 필드)
- `prefers-reduced-motion: reduce` 존중(전역 트랜지션 무효화)
- 상태 표현은 색상 단독이 아니라 배지 텍스트 + 점(dot) 아이콘 병행

## 8-1. 모션(마이크로 인터랙션)

전부 CSS `transition`/`@keyframes` 만으로 구현했고(JS 없음), `prefers-reduced-motion: reduce`
사용자에게는 전역적으로 전부 꺼진다(`dashboard.css` 최상단의 `@media (prefers-reduced-motion:
reduce) { *, *::before, *::after { transition: none !important; animation: none !important; } }`).

- **카드/리스트 진입 애니메이션**: `.kpi-card`, `.panel`, `.item-list li`가 페이지 로드 시
  아래에서 위로(12px) 페이드인. `.kpi-row .kpi-card:nth-child(n)`과 `.item-list li:nth-child(n)`에
  0~320ms 사이 계단식 지연을 걸어 순차적으로 나타나게 했다(항목당 40ms 간격, 과하지 않게).
- **구분선 스윕**: `.panel h2::after`가 96px짜리 흰색 얇은 막대를 4초 주기로 헤딩 밑줄 위에서
  좌→우로 은은하게 훑고 지나간다(포인트 요소로만, 전체 페이지에 남발하지 않음).
- **행(row) hover**: `.item-list li`, `table.data-table tbody tr` 모두 `rgba(244,244,245,0.03)`
  (흰색 3% 불투명도)만 깔린다 — 거의 안 보일 정도로 절제.
- **화살표 링크 hover**: `.footer-links a`("전체 실적 이력 보기 →" 류)는 hover 시
  `translateX(4px)`로 살짝만 이동.
- **탭/네비 active**: `.topbar-nav a`는 기본이 투명 `border-bottom`이고, hover/active 시
  보더 색만 전환(`border-color` transition) — 배경을 채우지 않는다.
- **버튼/카드 hover**: 확대나 그림자 없이 보더 색만 밝아진다(`.btn:hover`, `.kpi-card:hover`).

**아직 실제 페이지에 연결되지 않은 유틸리티**(요청받았지만 지금 대시보드에 대응하는 실제
기능이 없어 CSS 클래스만 정의해둠 — 새 기능을 만들어 붙이는 건 이번 작업 범위(시각 스타일만)
밖이라 보류):

- `.progress-bar` / `.progress-bar-fill`: 2px 높이 진행률 바. `.progress-bar-fill`의
  `style="width: N%"`을 JS로 갱신하면 `transition: width`로 부드럽게 채워진다. 지금 대시보드에는
  스크롤 진행률이나 로딩 진행률을 추적하는 기능이 없어 아직 어디에도 붙이지 않았다.
- `.btn.is-success`: 클릭 후 "저장됨"/"복사됨" 같은 임시 성공 상태(흰색 텍스트/보더)를
  표현하는 클래스. 지금 대시보드의 버튼(예: 과제 등록)은 전부 일반 폼 제출(POST + 페이지
  전체 리로드)이라 클릭 즉시 페이지가 바뀌므로 "2초 후 원상복귀" 같은 인라인 피드백을 보여줄
  타이밍 자체가 없다. 향후 AJAX로 제출하는 버튼이 생기면 `element.classList.add('is-success')`
  + `setTimeout(...)`으로 텍스트를 되돌리면 된다.

## 9. 로컬 실행

```bash
cd dashboard
python3 -m venv venv && source venv/bin/activate
pip install -r requirements-dev.txt
cp .env.example .env   # 최소 FLASK_SECRET_KEY, DASHBOARD_DB_FILE 채우기
python manage.py create-user admin
python app.py           # http://localhost:5001
```

## 10. 배포 (기존 PythonAnywhere 배포와 동일, 변경 없음)

README.md 7절 그대로. 이 작업은 정적 자산(CSS/폰트/템플릿)만 바뀌었으므로 `git pull` +
웹앱 **Reload**만으로 반영된다 — 가상환경 재설치, Task 재등록, DB 마이그레이션 불필요.

## 11. 롤백

시각 스타일 변경은 항상 별도 브랜치에서 작업하고 PR로 들어온다(`feature/portfolio-design-system` →
PR #6, `fix/portfolio-dark-theme` → PR #7, `feature/editorial-dark-refinement` → 이후 PR).
문제가 있으면 머지 전이면 그냥 브랜치를 버리면 되고, 이미 머지됐다면:

```bash
git revert <이 기능이 들어간 머지 커밋 SHA>
```
백엔드 코드는 건드리지 않았으므로 되돌려도 데이터/DB/인증에는 영향이 없다.

## 12. 남은 과제 (실측 불가로 보류된 것)

- `www.shingoon.me` 실제 렌더링과의 픽셀 단위 시각 대조(샌드박스 네트워크 제약으로
  Chromium 렌더링은 안 됨 — 다만 다크 테마 정정은 `curl`로 받은 HTML/CSS 원문에서
  확인한 실측값이며, 렌더링 결과의 시각적 대조는 아직 안 한 상태)
- 정확한 포트폴리오 파비콘 바이너리 재사용(이 세션 도구가 해당 이미지 바이너리를
  저장하지 못함 — 현재는 임시 SVG 파비콘 사용 중. `home/kaekun/portfolio/static/favicon.png`를
  `dashboard/static/`로 직접 복사하고 `templates/base.html`의 `<link rel="icon">`을
  `favicon.png`로 바꾸면 됨)
