"""Register the member assistant webhook without exposing its token in output."""

import sys

import requests

import config
from services import member_telegram


def main():
    if not member_telegram.configured():
        print("TELEGRAM_MEMBER_BOT_TOKEN is not configured.")
        return 2
    webhook_url = f"{config.DASHBOARD_PUBLIC_URL.rstrip('/')}/members/telegram/webhook"
    try:
        response = requests.post(
            f"https://api.telegram.org/bot{config.TELEGRAM_MEMBER_BOT_TOKEN}/setWebhook",
            json={"url": webhook_url, "secret_token": member_telegram.webhook_secret()},
            timeout=15,
        )
        ok = response.ok and bool(response.json().get("ok"))
    except (requests.RequestException, ValueError):
        ok = False
    print("Member Telegram webhook configured." if ok else "Member Telegram webhook setup failed.")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
