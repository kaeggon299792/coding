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
- 본문 폰트: `Inter, Pretendard, -apple-system, BlinkMacSystemFont, system-ui, sans-serif`
  (최초 조사에서도 맞았음 — 변경 없음)
- 제목(h1~h3) 폰트: 커스텀 웹폰트 `Trap`(ExtraBold, 800) — `static/fonts/Trap-ExtraBold.woff2`를
  포트폴리오 저장소에서 그대로 복사해 재사용(동일 소유자·동일 브랜드 패밀리). 변경 없음.
- Radius: `/css/tips.css` 원문에서 직접 읽은 실측값은 대부분 `4px`~`6px`(카드/큰 요소는 6px,
  버튼/인풋 등은 4px), 알약형 배지는 `999px`. 최초 버전의 "shadcn 기본값 0.5rem" 가정은
  틀렸던 것으로 확인되어 폐기하고 고정 px 값으로 교체했다.

**한계**: 이 세션의 샌드박스 환경에서 Playwright(Chromium)로 `www.shingoon.me`를 직접
렌더링해 스크린샷 비교하는 것은 여전히 실패한다(프록시 특유의 문제로 추정). 다만 `curl`로는
정상 접속되므로, 이번 정정은 실제 서버가 응답하는 HTML/CSS **원문 텍스트**를 직접 읽어
확인한 것이며, 렌더링된 픽셀을 눈으로 대조한 것은 아니다.

## 2. 토큰 정의 위치

`dashboard/static/css/dashboard.css` 최상단 `:root { ... }` 블록. 예:

```css
--brand-bg: #09090b;           /* zinc-950 */
--brand-text-primary: #f4f4f5; /* zinc-100 */
--brand-accent: #ffffff;       /* 다크 배경 위 흰색이 강조색 */
--font-display: 'Trap', 'Inter', 'Pretendard', sans-serif;
--font-body: 'Inter', 'Pretendard', -apple-system, BlinkMacSystemFont, system-ui, sans-serif;
```

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

이 브랜치(`feature/portfolio-design-system`)는 `main`에 아직 병합되지 않은 별도 브랜치다.
문제가 있으면 그냥 병합하지 않고 버리면 되고, 이미 병합한 뒤 되돌려야 한다면:

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
