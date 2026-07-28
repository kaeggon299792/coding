# 관리자 PC 폴더 인덱스 동기화

1. `python -m pip install -r requirements.txt`
2. `.env.example`을 `.env`로 복사하고 서버 URL, API 토큰, Y: 및 UNC 루트를 입력합니다.
3. `python main.py --scan-folders --dry-run`으로 건수를 확인합니다.
4. `python main.py --scan-folders`로 폴더명, 상대경로, UNC 경로, 연도, 파일수만 서버에 전송합니다.
5. `install_scheduler.bat`를 관리자 PC에서 실행하면 매시간 폴더 인덱스를 갱신합니다.

폴더 안의 파일 내용은 전송하지 않습니다. 설정된 루트 밖으로 해석되는 경로와 심볼릭 링크는 제외합니다.
