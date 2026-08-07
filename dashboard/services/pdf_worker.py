"""Resource-limited PDF validation/extraction subprocess."""

import json
import sys
from io import BytesIO
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from pypdf import PdfReader  # noqa: E402
from services import pdf_security  # noqa: E402


def _set_limits(memory_mb, cpu_seconds):
    try:
        import resource
    except ImportError:
        return
    memory_bytes = max(64, int(memory_mb)) * 1024 * 1024
    cpu = max(2, int(cpu_seconds))
    resource.setrlimit(resource.RLIMIT_AS, (memory_bytes, memory_bytes))
    resource.setrlimit(resource.RLIMIT_CPU, (cpu, cpu))
    resource.setrlimit(resource.RLIMIT_FSIZE, (2 * 1024 * 1024, 2 * 1024 * 1024))


def main():
    try:
        max_bytes, max_pages, max_chars = map(int, sys.argv[1:4])
        _set_limits(sys.argv[4], sys.argv[5])
        raw = sys.stdin.buffer.read(max_bytes + 1)
        if len(raw) > max_bytes:
            raise ValueError("too_large")
        page_count = pdf_security.validate_pdf_content(raw, max_pages=max_pages)
        reader = PdfReader(BytesIO(raw), strict=False)
        chunks, current_chars = [], 0
        for page in reader.pages[:max_pages]:
            text = (page.extract_text() or "").strip()
            if not text:
                continue
            remaining = max_chars - current_chars
            if remaining <= 0:
                break
            chunk = text[:remaining]
            chunks.append(chunk)
            current_chars += len(chunk)
        print(json.dumps({"ok": True, "page_count": page_count,
                          "text": "\n\n".join(chunks).strip()}))
        return 0
    except pdf_security.PdfSecurityError as error:
        print(json.dumps({"ok": False, "kind": "invalid", "message": str(error)}))
        return 2
    except (MemoryError, OSError, ValueError, TypeError):
        print(json.dumps({"ok": False, "kind": "processing"}))
        return 3


if __name__ == "__main__":
    raise SystemExit(main())
