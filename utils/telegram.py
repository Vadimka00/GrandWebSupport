from config import BOT_TOKEN
import aiohttp

def get_telegram_file_url(file_id: str) -> str:
    return f"https://api.telegram.org/file/bot{BOT_TOKEN}/{file_id}"

async def resolve_photo_url(file_id: str) -> str:
    api_url = f"https://api.telegram.org/bot{BOT_TOKEN}/getFile?file_id={file_id}"
    async with aiohttp.ClientSession() as session:
        async with session.get(api_url) as resp:
            data = await resp.json()
            file_path = data["result"]["file_path"]
            return f"https://api.telegram.org/file/bot{BOT_TOKEN}/{file_path}"