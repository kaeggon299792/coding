import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).with_name(".env"))

SERVER_URL = os.getenv("ARCHIVE_SERVER_URL", "").rstrip("/")
API_TOKEN = os.getenv("SYNC_API_TOKEN", "")
CLIENT_NAME = os.getenv("SYNC_CLIENT_NAME", "ADMIN-PC")
ROOT_DRIVE = os.getenv("ARCHIVE_ROOT_DRIVE", "")
ROOT_UNC = os.getenv("ARCHIVE_ROOT_UNC", "")
LOCAL_TEMP_DIR = Path(os.getenv("LOCAL_TEMP_DIR", r"C:\ArchiveSync\temp"))

