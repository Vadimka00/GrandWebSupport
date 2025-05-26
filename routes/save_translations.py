# routes/save_translations.py

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from sqlalchemy import insert
from starlette.responses import JSONResponse
from models import SessionLocal, Translation

router = APIRouter()

class BulkSaveRequest(BaseModel):
    lang: str
    translations: dict[str, str]

@router.post("/translations/save")
async def save_translations_handler(data: BulkSaveRequest):
    try:
        async with SessionLocal() as session:
            for key, text in data.translations.items():
                if not text.strip():
                    continue
                stmt = insert(Translation).values(
                    key=key,
                    lang=data.lang,
                    text=text
                ).prefix_with("IGNORE")
                await session.execute(stmt)
            await session.commit()
            return JSONResponse({"status": "ok", "saved": len(data.translations)})
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))