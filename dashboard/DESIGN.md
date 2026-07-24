# 디자인 시스템 — 포트폴리오(shingoon.me) 통합

이 문서는 `dashboard.shingoon.me`가 `www.shingoon.me`(포트폴리오)와 같은 브랜드로 보이도록
적용한 디자인 시스템을 설명한다. **기능/데이터/인증/API/배포 구조는 이 작업으로 전혀
바뀌지 않았다** — 시각적 레이어(`static/css/dashboard.css`, `templates/*.html`)만 변경됨.

## 1. 토큰 출처

색상·폰트 토큰은 claude.ai Projects("Portfolio-Archive")가 아니라 **`kaeggon299792/portfolio`
GitHub 저장소에 실제 배포된 컴파일 산출물**(`static/index.html`, `static/assets/index-*.css`)을
직접 읽어서 추출했다(스크린샷 추측이 아님). 확인된 사실:

- 포트폴리오는 Vite로 빌드된 SPA + Tailwind CSS(Tailwind의 **zinc** 뉴트럴 팔레트 사용,
  뚜렷한 채도 높은 브랜드 컬러 없이 사실상 모노크롬 — 블랙/화이트/그레이 중심).
- 본문 폰트: `Inter, Pretendard, -apple-system, BlinkMacSystemFont, system-ui, sans-serif`
- 제목(h1~h3) 폰트: 커스텀 웹폰트 `Trap`(ExtraBold, 800) — `static/fonts/Trap-ExtraBold.woff2`를
  포트폴리오 저장소에서 그대로 복사해 재사용(동일 소유자·동일 브랜드 패밀리).
- Radius: shadcn류 `--radius`(기본 0.5rem) + `calc(var(--radius) - 2px / 4px)` 중첩 패턴 확인.
  정확한 base 값(0.5rem)은 컴파일된 CSS에서 직접 읽지 못해 shadcn 기본값을 그대로 채택한
  가정값이다 — 실제 포트폴리오와 다르면 `--radius` 하나만 바꾸면 전체가 따라간다.
- 다크모드: 발견된 `:root` 커스텀 프로퍼티(`--foreground-rgb` 등)는 Next.js 보일러플레이트
  잔재로 실사용 근거가 없어 적용하지 않음(대시보드도 라이트 전용 유지).

**한계**: 이 세션의 샌드박스 환경에서 Playwright로 `www.shingoon.me`를 직접 렌더링해
스크린샷 비교하는 것은 프록시 문제로 실패했다(`curl`로는 정상 접속됨 — Chromium-프록시
조합 특유의 문제로 추정). 따라서 실제 렌더링 결과의 픽셀 단위 대조는 하지 못했고, 컴파일된
소스 코드에서 추출한 값만 사용했다.

## 2. 토큰 정의 위치

`dashboard/static/css/dashboard.css` 최상단 `:root { ... }` 블록. 예:

```css
--brand-bg: #fafafa;        /* zinc-50 */
--brand-text-primary: #09090b; /* zinc-950 */
--brand-accent: #09090b;    /* 모노크롬 — 블랙이 곧 강조색 */
--font-display: 'Trap', 'Inter', 'Pretendard', sans-serif;
--font-body: 'Inter', 'Pretendard', -apple-system, BlinkMacSystemFont, system-ui, sans-serif;
```

## 3. 강조색을 바꾸려면

`--brand-accent`, `--brand-accent-hover` 두 값만 바꾸면 버튼/활성 네비/포커스 링 전체가
따라간다. 현재는 포트폴리오 실측값(모노크롬 zinc-950)을 그대로 썼다.

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

- `www.shingoon.me` 실제 렌더링과의 픽셀 단위 시각 대조(샌드박스 네트워크 제약)
- 정확한 포트폴리오 파비콘 바이너리 재사용(이 세션 도구가 해당 이미지 바이너리를
  저장하지 못함 — 현재는 임시 SVG 파비콘 사용 중. `home/kaekun/portfolio/static/favicon.png`를
  `dashboard/static/`로 직접 복사하고 `templates/base.html`의 `<link rel="icon">`을
  `favicon.png`로 바꾸면 됨)
- `--radius` 기준값(0.5rem)은 shadcn 기본값 가정 — 실측 필요시 브라우저 개발자도구로
  포트폴리오 버튼의 `border-radius` computed 값을 확인해 교체
