import os
import json
from openai import AsyncOpenAI
from dotenv import load_dotenv

load_dotenv()

openai_api_key = os.getenv("OPENAI_API_KEY")
if not openai_api_key:
    raise RuntimeError("❌ Переменная OPENAI_API_KEY не найдена в окружении")

client = AsyncOpenAI(api_key=openai_api_key)

# Загрузка флагов
flags = {}
with open("flags.json", encoding="utf-8") as f:
    flags = json.load(f)

def patch_flag(text: str) -> str:
    """Заменяет флаг в тексте на {flag} (только если явно в конце строки или после пробела)"""
    for code, flag in flags.items():
        if f" {flag}" in text:
            return text.replace(f" {flag}", " {flag}")
        if text.endswith(flag):
            return text.replace(flag, "{flag}")
    return text

async def translate_with_gpt(ru_translations: dict[str, str], target_lang: str, lang_name: str, emoji: str) -> dict[str, str]:
    """
    Отправляет словарь переводов на русском и возвращает переводы на выбранный язык
    """
    prompt_lines = []
    for key, text in ru_translations.items():
        safe_text = patch_flag(text)
        prompt_lines.append(f"{key}: {safe_text}")

    formatted = "\n".join(prompt_lines)

    system_msg = (
        f"Ты профессиональный переводчик интерфейсов.\n"
        f"Переводи строки справа от двоеточия на {lang_name} {emoji}.\n"
        f"Сохраняй переносы строк (\\n и \\n\\n), эмодзи {{flag}}, а также плейсхолдеры вроде {{text}} и {{moderator}}.\n"
        f"Формат ответа: key: translated text"
    )

    response = await client.chat.completions.create(
        model="gpt-4o",
        messages=[
            {"role": "system", "content": system_msg},
            {"role": "user", "content": formatted}
        ],
        temperature=0.2
    )

    raw = response.choices[0].message.content.strip()
    result = {}

    for line in raw.splitlines():
        if ":" in line:
            k, v = line.split(":", 1)
            # Подставляем флаг обратно
            final_text = v.strip().replace("{flag}", f"{flags.get(target_lang, target_lang.upper())}")
            result[k.strip()] = final_text

    return result