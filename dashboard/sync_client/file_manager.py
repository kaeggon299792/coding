from datetime import datetime, timezone
from pathlib import Path, PureWindowsPath


class UnsafeArchivePath(ValueError):
    pass


def drive_path_to_unc(path, root_drive, root_unc):
    candidate = PureWindowsPath(str(path).replace("/", "\\"))
    drive_root = PureWindowsPath(str(root_drive).rstrip("\\"))
    try:
        relative = candidate.relative_to(drive_root)
    except ValueError as error:
        unc_candidate = PureWindowsPath(str(path).replace("/", "\\"))
        unc_root = PureWindowsPath(str(root_unc).rstrip("\\"))
        try:
            unc_candidate.relative_to(unc_root)
        except ValueError:
            raise UnsafeArchivePath("허용된 Y디스크 기준경로 밖의 폴더입니다.") from error
        return str(unc_candidate)
    if ".." in relative.parts:
        raise UnsafeArchivePath("상위 경로 이동은 허용되지 않습니다.")
    return str(PureWindowsPath(str(root_unc).rstrip("\\")) / relative)


def scan_folders(root_drive, root_unc):
    root = Path(root_drive).resolve(strict=True)
    folders = []
    for candidate in root.rglob("*"):
        if not candidate.is_dir() or candidate.is_symlink():
            continue
        resolved = candidate.resolve(strict=True)
        try:
            relative = resolved.relative_to(root)
        except ValueError:
            continue
        parts = relative.parts
        year = next((int(part) for part in parts if len(part) == 4 and part.isdigit()), None)
        files = sum(1 for child in candidate.iterdir() if child.is_file())
        modified = datetime.fromtimestamp(candidate.stat().st_mtime, timezone.utc).isoformat()
        folders.append({
            "folder_name": candidate.name,
            "relative_path": str(PureWindowsPath(*parts)),
            "unc_path": str(PureWindowsPath(root_unc) / PureWindowsPath(*parts)),
            "year": year,
            "folder_category": parts[0] if parts else "",
            "file_count": files,
            "last_modified_at": modified,
        })
    return folders

