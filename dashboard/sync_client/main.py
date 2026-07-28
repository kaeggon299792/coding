import argparse

import api_client
import config
from file_manager import scan_folders


def main():
    parser = argparse.ArgumentParser(description="공문자료 Y디스크 동기화 클라이언트")
    parser.add_argument("--scan-folders", action="store_true")
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--document-id")
    parser.add_argument("--verify-all", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    if args.scan_folders:
        folders = scan_folders(config.ROOT_DRIVE, config.ROOT_UNC)
        if args.dry_run:
            print(f"전송 예정 폴더: {len(folders)}개")
            return
        result = api_client.upload_folder_index(folders)
        print(f"폴더 인덱스 동기화 완료: {result['folder_count']}개")
        return
    parser.error("현재 구현된 실행 옵션을 선택하세요: --scan-folders")


if __name__ == "__main__":
    main()

