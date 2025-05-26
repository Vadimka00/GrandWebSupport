from fastapi import APIRouter, Request, HTTPException
from fastapi.templating import Jinja2Templates
from fastapi.responses import RedirectResponse
from sqlalchemy.future import select
from sqlalchemy.orm import selectinload
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy import func, delete
from starlette.status import HTTP_500_INTERNAL_SERVER_ERROR

from models import SessionLocal, Language, SupportGroup, User, Translation, ModeratorGroupLink, SupportGroupLanguage
from utils.utils import get_group_photo_url

router = APIRouter()
templates = Jinja2Templates(directory="templates")

@router.get("/settings")
async def settings_page(request: Request):
    try:
        async with SessionLocal() as session:
            result_languages = await session.execute(select(Language))
            result_groups = await session.execute(
                select(SupportGroup)
                .options(
                    selectinload(SupportGroup.languages),
                    selectinload(SupportGroup.moderators)
                )
            )
            result_users = await session.execute(
                select(User).where(User.role == "moderator")
            )

            # Языки без переводов (неактивируемые)
            result_unavailable = await session.execute(
                select(Language.code)
                .outerjoin(Translation, Translation.lang == Language.code)
                .group_by(Language.code)
                .having(func.count(Translation.id) == 0)
            )
            unavailable_codes = {row[0] for row in result_unavailable}

            # Финальные данные
            languages = result_languages.scalars().all()
            groups = result_groups.scalars().all()
            moderators = result_users.scalars().all()

            return templates.TemplateResponse("settings.html", {
                "request": request,
                "languages": languages,
                "groups": groups,
                "moderators": moderators,
                "unavailable_codes": unavailable_codes,
                "get_photo_url": lambda path: get_group_photo_url(path)
            })

    except SQLAlchemyError as e:
        print(f"[DB ERROR] {e}")
        raise HTTPException(
            status_code=HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Ошибка при подключении к базе данных."
        )

    except Exception as e:
        print(f"[UNEXPECTED ERROR] {e}")
        raise HTTPException(
            status_code=HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Неизвестная ошибка при загрузке настроек."
        )
    
@router.post("/settings/toggle-language/{code}")
async def toggle_language(code: str):
    try:
        async with SessionLocal() as session:
            lang = await session.get(Language, code)
            if not lang:
                raise HTTPException(status_code=404, detail="Язык не найден")
            lang.available = not lang.available
            await session.commit()
            return RedirectResponse(url="/settings", status_code=303)
    except SQLAlchemyError as e:
        print(f"[DB ERROR toggle_language] {e}")
        raise HTTPException(status_code=500, detail="Ошибка базы данных")

@router.post("/settings/assign-language/{group_id}")
async def assign_language(group_id: int, request: Request):
    try:
        form = await request.form()
        language_code = form.get("language_code")

        async with SessionLocal() as session:
            lang = await session.get(Language, language_code)
            if not lang or not lang.available:
                raise HTTPException(status_code=400, detail="Недопустимый язык")

            exists = await session.execute(
                select(SupportGroupLanguage).where(
                    SupportGroupLanguage.group_id == group_id,
                    SupportGroupLanguage.language_code == language_code
                )
            )
            if exists.scalar():
                return RedirectResponse(url="/settings", status_code=303)

            session.add(SupportGroupLanguage(group_id=group_id, language_code=language_code))
            await session.commit()
            return RedirectResponse(url="/settings", status_code=303)
    except SQLAlchemyError as e:
        print(f"[DB ERROR assign_language] {e}")
        raise HTTPException(status_code=500, detail="Ошибка базы данных")

@router.post("/settings/unassign-language/{group_id}/{language_code}")
async def unassign_language(group_id: int, language_code: str):
    try:
        async with SessionLocal() as session:
            await session.execute(
                delete(SupportGroupLanguage).where(
                    SupportGroupLanguage.group_id == group_id,
                    SupportGroupLanguage.language_code == language_code
                )
            )
            await session.commit()
            return RedirectResponse(url="/settings", status_code=303)
    except SQLAlchemyError as e:
        print(f"[DB ERROR unassign_language] {e}")
        raise HTTPException(status_code=500, detail="Ошибка базы данных")

@router.post("/settings/assign-moderator/{group_id}")
async def assign_moderator(group_id: int, request: Request):
    try:
        form = await request.form()
        moderator_id = int(form.get("moderator_id"))

        async with SessionLocal() as session:
            user = await session.get(User, moderator_id)
            if not user or user.role != "moderator":
                raise HTTPException(status_code=400, detail="Недопустимый модератор")

            result = await session.execute(
                select(ModeratorGroupLink).where(
                    ModeratorGroupLink.group_id == group_id,
                    ModeratorGroupLink.moderator_id == moderator_id
                )
            )
            if result.scalar():
                return RedirectResponse(url="/settings", status_code=303)

            session.add(ModeratorGroupLink(group_id=group_id, moderator_id=moderator_id))
            await session.commit()
            return RedirectResponse(url="/settings", status_code=303)
    except SQLAlchemyError as e:
        print(f"[DB ERROR assign_moderator] {e}")
        raise HTTPException(status_code=500, detail="Ошибка базы данных")

@router.post("/settings/unassign-moderator/{group_id}/{moderator_id}")
async def unassign_moderator(group_id: int, moderator_id: int):
    try:
        async with SessionLocal() as session:
            await session.execute(
                delete(ModeratorGroupLink).where(
                    ModeratorGroupLink.group_id == group_id,
                    ModeratorGroupLink.moderator_id == moderator_id
                )
            )
            await session.commit()
            return RedirectResponse(url="/settings", status_code=303)
    except SQLAlchemyError as e:
        print(f"[DB ERROR unassign_moderator] {e}")
        raise HTTPException(status_code=500, detail="Ошибка базы данных")