import sys
import types
from pathlib import Path

from scheduler.config_binding import bind_dashboard_config


def test_bind_dashboard_config_installs_real_dashboard_config(monkeypatch):
    fake_legacy_config = types.ModuleType("config")
    fake_legacy_config.LEGACY_MARKER = "legacy"
    monkeypatch.setitem(sys.modules, "config", fake_legacy_config)

    # Simulates a legacy module that already bound its own `config` reference
    # (e.g. casino_news_watch's news_watch.py) before the rebind happens.
    already_bound_by_legacy_module = sys.modules["config"]

    dashboard_root = Path(__file__).resolve().parent.parent
    result = bind_dashboard_config(dashboard_root)

    assert sys.modules["config"] is result
    assert result is not fake_legacy_config
    assert hasattr(result, "TELEGRAM_ALERT_DRY_RUN")
    assert hasattr(result, "TELEGRAM_MEMBER_BOT_TOKEN")
    assert hasattr(result, "TELEGRAM_BOT_TOKEN")
    assert hasattr(result, "DASHBOARD_DB_FILE")

    # A module that imported `config` before the rebind keeps its own
    # reference untouched -- the legacy pipeline is unaffected.
    assert already_bound_by_legacy_module is fake_legacy_config
    assert not hasattr(already_bound_by_legacy_module, "TELEGRAM_ALERT_DRY_RUN")


def test_bind_dashboard_config_lets_dashboard_modules_resolve_correctly(monkeypatch):
    """Reproduces the managed-worker import order and confirms the three
    Telegram-facing modules the news alert policy depends on end up bound to
    the dashboard's own config, not whatever was cached under "config"
    beforehand."""
    fake_legacy_config = types.ModuleType("config")
    fake_legacy_config.TELEGRAM_BOT_TOKEN = "legacy-token"
    fake_legacy_config.TELEGRAM_CHAT_ID = "legacy-chat"
    monkeypatch.setitem(sys.modules, "config", fake_legacy_config)

    for name in ("extensions", "services.member_telegram", "services.telegram_alert"):
        monkeypatch.delitem(sys.modules, name, raising=False)

    dashboard_root = Path(__file__).resolve().parent.parent
    bind_dashboard_config(dashboard_root)

    import extensions
    import services.member_telegram as member_telegram
    import services.telegram_alert as telegram_alert

    assert extensions.config is not fake_legacy_config
    assert member_telegram.config is not fake_legacy_config
    assert telegram_alert.config is not fake_legacy_config
    assert hasattr(extensions.config, "DASHBOARD_DB_FILE")
    assert hasattr(member_telegram.config, "TELEGRAM_MEMBER_BOT_TOKEN")
    assert hasattr(telegram_alert.config, "TELEGRAM_ALERT_DRY_RUN")


def test_managed_wrapper_binds_config_before_importing_news_alert_policy():
    """Guards the fix's ordering: the rebind must run before the dashboard's
    news_alert_policy import, or later dashboard imports would still pick up
    whatever config the legacy pipeline cached first."""
    source = Path(__file__).resolve().parent.parent.joinpath(
        "scheduler", "casino_news_watch_managed.py"
    ).read_text()

    bind_index = source.index("bind_dashboard_config(PROJECT_ROOT)")
    policy_import_index = source.index("from services.news_alert_policy import apply_news_alert_policy")

    assert bind_index < policy_import_index
