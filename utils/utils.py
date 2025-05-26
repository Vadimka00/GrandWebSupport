import os

TELEGRAM_BOT_TOKEN = os.getenv("BOT_TOKEN")

def get_group_photo_url(photo_path: str) -> str:
    return f"https://api.telegram.org/file/bot{TELEGRAM_BOT_TOKEN}/{photo_path}"