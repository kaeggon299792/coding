@echo off
set SCRIPT_DIR=%~dp0
schtasks /Create /TN "OfficialDocumentFolderScan" /SC HOURLY /MO 1 /TR "python \"%SCRIPT_DIR%main.py\" --scan-folders" /F
echo 작업 스케줄러 등록이 완료되었습니다.

