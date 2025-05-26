from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from starlette.responses import JSONResponse
from services.gpt_translate import translate_with_gpt
from models import SessionLocal, Translation, Language
from sqlalchemy import select, insert
from collections import defaultdict
import traceback
import logging

logger = logging.getLogger("gpt_translate")

router = APIRouter()

class TranslateRequest(BaseModel):
    lang: str

@router.post("/translate_with_gpt")
async def gpt_translation_handler(data: TranslateRequest):
    try:
        async with SessionLocal() as session:
            # Получаем язык из базы
            lang_result = await session.execute(select(Language).where(Language.code == data.lang))
            lang = lang_result.scalar_one_or_none()
            if not lang:
                raise HTTPException(status_code=404, detail="Язык не найден")

            # Получаем все переводы на русском
            result = await session.execute(select(Translation).where(Translation.lang == "ru"))
            ru_rows = result.scalars().all()
            ru_dict = {row.key: row.text for row in ru_rows}

            # Запрашиваем перевод
            translated_dict = await translate_with_gpt(
                ru_translations=ru_dict,
                target_lang=lang.code,
                lang_name=lang.name_ru,
                emoji=lang.emoji or ""
            )

            # Сохраняем переводы в базу
            for key, text in translated_dict.items():
                if not text.strip():
                    continue
                stmt = insert(Translation).values(
                    key=key,
                    lang=lang.code,
                    text=text
                ).prefix_with("IGNORE")
                await session.execute(stmt)

            await session.commit()
            return JSONResponse({"status": "ok", "added": len(translated_dict)})

    except Exception as e:
        logger.exception(f"[GPT TRANSLATE] ❌ Ошибка перевода: {e}")
        raise HTTPException(status_code=500, detail=str(e))
