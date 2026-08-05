# CASINO IN 운영 배포 절차

## 기본 원칙

- 운영 SQLite DB와 소스는 배포 직전에 함께 백업합니다.
- Python 컴파일, 앱 기동, 필수 라우트와 DB 무결성 검사를 통과하면 즉시 Reload합니다.
- 전체 테스트는 배포 후 백그라운드에서 실행합니다.
- 전체 테스트가 실패하면 직전 백업으로 자동 롤백하고 다시 Reload합니다.
- `.env`, API 키, 업로드 파일은 Git에 포함하지 않습니다.

## 빠른 표준 배포

```bash
cd /home/kaekun/coding-dashboard/dashboard
chmod +x deployment/*.sh
./deployment/deploy_dashboard.sh origin/main
```

배포 스크립트는 다음 순서로 처리합니다.

1. SQLite 온라인 백업과 무결성 검사
2. 지정 Git ref의 `dashboard/` 소스만 반영
3. 의존성 설치, Python 컴파일, 앱 기동 및 필수 라우트 검사
4. DB 무결성 재검사
5. 두 PythonAnywhere WSGI 앱 Reload
6. 전체 테스트를 백그라운드 실행
7. 전체 테스트 실패 시 자동 롤백 및 Reload

## 배포 후 전체 테스트 상태

```bash
cat logs/post-deploy-latest.status
tail -n 80 "$(awk '{for(i=1;i<=NF;i++) if($i ~ /^log=/){sub(/^log=/,"",$i); print $i}}' logs/post-deploy-latest.status)"
```

상태는 `RUNNING`, `PASSED`, `ROLLED_BACK` 중 하나입니다.

## 수동 백업 및 롤백

```bash
./deployment/backup_dashboard.sh
./deployment/rollback_dashboard.sh /home/kaekun/backups/management-dashboard/<timestamp>
touch app.py /var/www/casino_shingoon_me_wsgi.py /var/www/www_casinoin_kr_wsgi.py
```

## 배포 직후 확인

운영 `.env`는 Git으로 덮어쓰지 않고 PythonAnywhere에서 다음 비밀이 아닌
도메인 설정만 수동으로 확인합니다. 기존 비밀값과 다른 환경변수는 유지합니다.

```text
DASHBOARD_PUBLIC_URL=https://www.casinoin.kr
TRUSTED_HOSTS=www.casinoin.kr,casinoin.kr,casino.shingoon.me,www.casino.shingoon.me,dashboard.shingoon.me,dashboard-kaekun.pythonanywhere.com
GOOGLE_REDIRECT_URI=https://www.casinoin.kr/auth/google/callback
```

Google Cloud Console에도 위 callback URI와
`https://www.casinoin.kr` JavaScript 원본을 먼저 추가한 뒤 앱을 Reload합니다.

```bash
curl -fsS https://www.casinoin.kr/ > /dev/null
curl -fsS https://www.casinoin.kr/login > /dev/null
curl -fsS https://www.casinoin.kr/market/stocks > /dev/null
```

로그인·관리자 권한, 데이터 화면, 최종 확인/변경 시각, 오류 로그도 변경 범위에 맞춰 확인합니다.
