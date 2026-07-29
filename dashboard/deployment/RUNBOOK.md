# PARADISE 대시보드 운영 배포 절차

## 원칙

- 운영 반영 전 SQLite 온라인 백업과 무결성 검사를 반드시 수행합니다.
- 운영 폴더에 미커밋 변경이 있으면 배포·롤백을 중단합니다.
- 소스 적용 후 전체 테스트와 DB 마이그레이션/무결성 검사를 통과해야 Reload 합니다.
- `.env`, API 키, 업로드 파일은 Git에 포함하지 않습니다.

## 표준 배포

```bash
cd /home/kaekun/coding-dashboard/dashboard
chmod +x deployment/*.sh
./deployment/deploy_dashboard.sh origin/feature/dashboard-tips-integration
```

운영 폴더의 DB·업로드·환경설정은 유지하면서 지정한 Git ref의 `dashboard/`
소스만 반영합니다. 스크립트 출력의 `backup`과 `previous_commit`을 배포 기록에 보관합니다. 검증
완료 후 PythonAnywhere Web 탭에서 `dashboard.shingoon.me` 앱을 Reload하고
홈·로그인·유가/환율·연휴 화면을 확인합니다.

## 수동 백업

```bash
./deployment/backup_dashboard.sh
```

백업은 `/home/kaekun/backups/management-dashboard/YYYYMMDD-HHMMSS/`에 생성되며,
DB, Git 커밋, SHA-256 체크섬을 함께 보관합니다.

## 롤백

```bash
./deployment/rollback_dashboard.sh \
  /home/kaekun/backups/management-dashboard/<timestamp>
```

완료 후 PythonAnywhere Web 탭에서 Reload하고 로그인·목록 조회·DB 무결성을
다시 확인합니다. 백업은 최소 30일 보관하고 월 1회 오래된 백업을 별도
보관소로 이동합니다.

## 배포 후 확인

1. `curl -I https://dashboard.shingoon.me/`가 200인지 확인
2. 관리자 로그인 및 권한 없는 계정의 접근 제한 확인
3. `python scheduler/sync_economic_data.py` 실행 후 유가·환율 건수 확인
4. 각 데이터 화면의 `최종 확인`과 `최종 변경`이 구분되는지 확인
5. `logs/*.log`, `errors`, `dashboard_analysis_runs`에서 신규 오류 확인
