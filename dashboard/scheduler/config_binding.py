"""Bind the dashboard's own config module inside a shared process.

`casino_news_watch_managed.py` puts the legacy `casino_news_watch` project
first on `sys.path` so it can import that project's own modules unmodified.
Those modules do a bare `import config`, which Python caches under the
module name "config" in `sys.modules`. When the dashboard code loaded
afterward (extensions, member_telegram, telegram_alert) does its own bare
`import config`, it reuses that same cached entry instead of resolving
dashboard/config.py, since both projects happen to name their settings
module "config".

`bind_dashboard_config()` loads dashboard/config.py by its exact file path
(bypassing `sys.path` search order entirely) and installs it as
`sys.modules["config"]` so any `import config` that happens *after* this
call resolves unambiguously to the dashboard's config. Modules that already
ran `import config` before this call (the legacy pipeline) keep their own
already-bound reference and are unaffected.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


def bind_dashboard_config(dashboard_root: Path | str | None = None):
    dashboard_root = Path(dashboard_root or Path(__file__).resolve().parent.parent)
    spec = importlib.util.spec_from_file_location("config", dashboard_root / "config.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules["config"] = module
    spec.loader.exec_module(module)
    return module
