# PythonAnywhere Project

프레임워크 없는 순수 Python 프로젝트입니다. PythonAnywhere 유료 플랜의
**Always-on task** 또는 **Scheduled task**로 실행하는 것을 전제로 구성했습니다.

## 프로젝트 구조

```
pythonanywhere_project/
├── main.py           # 엔트리 포인트
├── config.py         # .env에서 환경 변수를 읽어오는 설정 모듈
├── requirements.txt  # 의존성 목록
├── .env.example       # 환경 변수 템플릿 (실제 값은 없음)
├── .gitignore         # .env 등 커밋하면 안 되는 파일 제외
└── README.md
```

## 로컬 개발 설정

```bash
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt

cp .env.example .env
# .env 파일을 열어서 실제 DB/API 값 입력

python main.py
```

## PythonAnywhere 배포

1. **코드 가져오기** (Bash 콘솔에서)
   ```bash
   git clone <repo-url>
   cd coding/pythonanywhere_project
   ```

2. **가상환경 생성 및 패키지 설치**
   ```bash
   mkvirtualenv --python=/usr/bin/python3.10 pa-project-venv
   pip install -r requirements.txt
   ```

3. **환경 변수 설정**
   서버에는 `.env` 파일을 직접 올리지 않고, 콘솔에서 생성합니다.
   ```bash
   cp .env.example .env
   nano .env   # 실제 DB 비밀번호, API 키 입력
   ```
   `.env`는 `.gitignore`에 포함되어 있어 절대 git에 커밋되지 않습니다.

4. **MySQL 사용 시**
   PythonAnywhere Databases 탭에서 MySQL 인스턴스를 생성한 뒤,
   `.env`의 `DB_HOST`, `DB_USER`, `DB_PASSWORD`, `DB_NAME` 값을
   발급받은 정보로 채웁니다.

5. **실행 방식 선택**
   - **Scheduled Tasks** 탭: 주기적으로 실행할 명령 등록
     ```
     workon pa-project-venv && python /home/yourusername/coding/pythonanywhere_project/main.py
     ```
   - **Always-on Tasks** 탭 (유료 플랜): 계속 실행되어야 하는 워커/봇의 경우
     `main.py`가 무한 루프로 동작하도록 작성 후 등록합니다.

## 환경 변수 (.env)

| 변수 | 설명 |
|---|---|
| `DB_HOST` | MySQL 호스트 (예: `yourusername.mysql.pythonanywhere-services.com`) |
| `DB_USER` | MySQL 사용자명 |
| `DB_PASSWORD` | MySQL 비밀번호 |
| `DB_NAME` | 데이터베이스 이름 |
| `API_KEY` | 외부 API 인증 키 |
| `SECRET_KEY` | 앱 내부 암호화/서명용 시크릿 |

실제 값은 `.env`에만 두고, 코드에는 절대 하드코딩하지 않습니다.
`config.py`가 `python-dotenv`를 통해 이 값들을 로드합니다.
