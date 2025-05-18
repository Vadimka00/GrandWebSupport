# main.py
from fastapi import FastAPI, Request, Depends, HTTPException, Cookie, Form
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
from models import SessionLocal, Translation, User, Status, Language, SupportRequest, Credentials
from sqlalchemy.dialects.mysql import insert as mysql_insert
from sqlalchemy.orm import selectinload
from utils.telegram import resolve_photo_url
from pydantic import BaseModel
from sqlalchemy import select, update, insert, func
from collections import defaultdict
import uvicorn
import json
import bcrypt
import secrets
import traceback
from starlette.responses import Response
from starlette.status import HTTP_303_SEE_OTHER
from utils.logger import logger

class UpdateRequest(BaseModel):
    key: str
    lang: str
    text: str

# Загрузка описаний ключей
with open("descriptions.json", encoding="utf-8") as f:
    key_descriptions = json.load(f)

with open("flags.json", encoding="utf-8") as f:
    flags = json.load(f)

with open("status_labels.json", encoding="utf-8") as f:
    status_labels = json.load(f)

app = FastAPI()
templates = Jinja2Templates(directory="templates")

app.mount("/static", StaticFiles(directory="static"), name="static")



# Этот middleware позволит перехватывать 500 ошибки
@app.middleware("http")
async def custom_error_handler(request: Request, call_next):
    try:
        return await call_next(request)
    except Exception as e:
        logger.error(
            f"❌ Unhandled error on {request.method} {request.url.path}: {e}\n{traceback.format_exc()}"
        )

        return HTMLResponse(
            content="""
            <!DOCTYPE html>
            <html lang="ru">
            <head>
              <meta charset="UTF-8">
              <title>Ошибка</title>
              <meta name="viewport" content="width=device-width, initial-scale=1.0">
              <style>
                body {
                  font-family: sans-serif;
                  background: #fdf2f2;
                  color: #333;
                  padding: 2rem;
                  text-align: center;
                }
                .error-box {
                  background: #fff;
                  border: 1px solid #e0e0e0;
                  max-width: 400px;
                  margin: 4rem auto;
                  padding: 2rem;
                  border-radius: 8px;
                  box-shadow: 0 4px 12px rgba(0,0,0,0.05);
                }
              </style>
            </head>
            <body>
              <div class="error-box">
                <h2>Что-то пошло не так</h2>
                <p>Пожалуйста, перезагрузите страницу.</p>
              </div>
            </body>
            </html>
            """,
            status_code=500
        )

@app.get("/login", response_class=HTMLResponse)
async def login_form(request: Request):
    logger.debug("[GET /login] Отображение формы входа")
    return templates.TemplateResponse("login.html", {"request": request})

@app.post("/login", response_class=HTMLResponse)
async def login(
    request: Request,
    email: str = Form(...),
    password: str = Form(...),
    response: Response = None
):
    logger.info(f"[POST /login] Попытка входа с email: {email}")
    async with SessionLocal() as session:
        result = await session.execute(
            select(Credentials).where(Credentials.email == email)
        )
        cred = result.scalar_one_or_none()

        if not cred or not bcrypt.checkpw(password.encode(), cred.password_hash.encode()):
            logger.warning(f"[POST /login] Неудачная попытка входа для email: {email}")
            return templates.TemplateResponse(
                "login.html",
                {"request": request, "error": "Неверная пара логин/пароль"}
            )

        logger.info(f"[POST /login] Успешный вход. user_id={cred.user_id}")
        response = RedirectResponse("/", status_code=303)
        response.set_cookie("user_id", str(cred.user_id), httponly=True)
        return response

@app.get("/logout")
def logout(response: Response):
    logger.info("[GET /logout] Выход пользователя. Очистка куки.")
    response = RedirectResponse("/login", status_code=303)
    response.delete_cookie("user_id")
    return response

def get_current_user(user_id: str = Cookie(None)):
    if not user_id:
        logger.debug("[AUTH] Отсутствует user_id в cookie. Перенаправление на /login")
        raise HTTPException(status_code=HTTP_303_SEE_OTHER, headers={"Location": "/login"})
    logger.debug(f"[AUTH] Получен user_id из cookie: {user_id}")
    return int(user_id)

@app.get("/", dependencies=[Depends(get_current_user)], response_class=HTMLResponse)
async def index(request: Request):
    logger.info("[GET /] Загрузка главной страницы")

    try:
        async with SessionLocal() as session:
            logger.debug("[/index] Получение статистики пользователей")
            u = await session.execute(
                select(User.language_code, func.count()).group_by(User.language_code)
            )
            user_stats = dict(u.all())
            total_users = sum(user_stats.values())

            logger.debug("[/index] Получение статистики модераторов")
            m = await session.execute(
                select(User.language_code, func.count())
                .where(User.role == "moderator")
                .group_by(User.language_code)
            )
            mod_stats = dict(m.all())
            total_mods = sum(mod_stats.values())

            logger.debug("[/index] Получение статистики заявок")
            r = await session.execute(
                select(SupportRequest.language, SupportRequest.status, func.count())
                .group_by(SupportRequest.language, SupportRequest.status)
            )
            raw = r.all()

        req_stats = {}
        for lang, st, cnt in raw:
            rec = req_stats.setdefault(lang, {
                "total": 0, "pending": 0, "in_progress": 0, "closed": 0
            })
            rec[st] += cnt
            rec["total"] += cnt
        total_reqs = sum(v["total"] for v in req_stats.values())

        logger.info(f"[/index] Статистика собрана: users={total_users}, mods={total_mods}, requests={total_reqs}")

        def safe_lang(lang):
            return lang if lang is not None else 'None'

        user_stats = {safe_lang(k): v for k, v in user_stats.items()}
        mod_stats = {safe_lang(k): v for k, v in mod_stats.items()}
        req_stats = {safe_lang(k): v for k, v in req_stats.items()}

        languages = sorted(set(user_stats) | set(mod_stats) | set(req_stats))
        statuses = ["pending", "in_progress", "closed"]

        return templates.TemplateResponse("index.html", {
            "request": request,
            "user_stats": user_stats,
            "mod_stats": mod_stats,
            "req_stats": req_stats,
            "languages": languages,
            "statuses": statuses,
            "flags": flags,
            "status_labels": status_labels,
            "total_users": total_users,
            "total_mods": total_mods,
            "total_reqs": total_reqs,
        })

    except Exception as e:
        logger.exception(f"[GET /] Ошибка при загрузке главной страницы: {e}")
        raise

@app.get("/translations", dependencies=[Depends(get_current_user)], response_class=HTMLResponse)
async def show_translations(request: Request):
    logger.info("[GET /translations] Загрузка страницы переводов")

    try:
        async with SessionLocal() as session:
            logger.debug("[/translations] Получение переводов для 'ru' и 'en'")
            result = await session.execute(
                select(Translation).where(Translation.lang.in_(["ru", "en"]))
            )
            rows = result.scalars().all()
            logger.info(f"[/translations] Загружено переводов: {len(rows)}")

        translations = defaultdict(dict)
        langs_set = set()

        for row in rows:
            translations[row.key][row.lang] = row.text
            langs_set.add(row.lang)

        langs = sorted(langs_set)
        logger.debug(f"[/translations] Найденные языки: {langs}")

        return templates.TemplateResponse("translations.html", {
            "request": request,
            "translations": translations,
            "langs": langs,
            "key_descriptions": key_descriptions,
            "flags": flags
        })

    except Exception as e:
        logger.exception(f"[GET /translations] Ошибка при загрузке переводов: {e}")
        raise

@app.post("/update")
async def update_translation(data: UpdateRequest):
    logger.info(f"[POST /update] Запрос на обновление перевода: key='{data.key}', lang='{data.lang}'")

    try:
        async with SessionLocal() as session:
            logger.debug(f"[/update] Выполнение запроса UPDATE для key='{data.key}', lang='{data.lang}'")

            result = await session.execute(
                update(Translation)
                .where(Translation.key == data.key, Translation.lang == data.lang)
                .values(text=data.text)
            )
            await session.commit()

            # Проверим, были ли затронуты строки (для отладки)
            updated = result.rowcount
            if updated == 0:
                logger.warning(f"[/update] ⚠️ Перевод не найден или не обновлён: key='{data.key}', lang='{data.lang}'")
            else:
                logger.info(f"[/update] ✅ Перевод обновлён: key='{data.key}', lang='{data.lang}', rows affected={updated}")

        return JSONResponse(content={"status": "ok"})

    except Exception as e:
        logger.exception(f"[POST /update] ❌ Ошибка при обновлении перевода: key='{data.key}', lang='{data.lang}': {e}")
        raise

@app.get("/users", dependencies=[Depends(get_current_user)], response_class=HTMLResponse)
async def users_view(request: Request, q: str = "", page: int = 1, per_page: int = 20):

    offset = (page - 1) * per_page
    client_ip = request.client.host
    current_user = request.scope.get("user")  # если get_current_user добавляет юзера в scope

    logger.info(f"🔍 /users requested by {current_user} from {client_ip} | query='{q}' | page={page}, per_page={per_page}")

    async with SessionLocal() as session:
        count_query = select(func.count()).select_from(User)
        user_query = select(User)

        if q:
            like = f"%{q.lower()}%"
            filter_expr = func.lower(User.username).like(like) | func.lower(User.full_name).like(like)
            count_query = count_query.where(filter_expr)
            user_query = user_query.where(filter_expr)

        total = await session.scalar(count_query)

        langs = await session.execute(
            select(User.language_code, func.count()).group_by(User.language_code)
        )
        lang_counts = dict(langs.all())

        users = await session.execute(
            user_query.order_by(User.id.desc()).offset(offset).limit(per_page)
        )
        langs_available = await session.execute(
            select(Language).where(Language.available == True)
        )
        available_languages = langs_available.scalars().all()

    total_pages = (total + per_page - 1) // per_page

    logger.info(f"✅ /users responded with {total} users")

    return templates.TemplateResponse("users.html", {
        "request": request,
        "total": total,
        "lang_counts": lang_counts,
        "users": users.scalars().all(),
        "query": q,
        "page": page,
        "total_pages": total_pages,
        "available_languages": available_languages,
        "flags": flags
    })

@app.post("/users/set-language")
async def set_user_language(request: Request, user_id: int = Form(...), lang: str = Form(...)):
    try:
        async with SessionLocal() as session:
            user = await session.get(User, user_id)
            if not user:
                logger.warning(f"⚠️ Attempt to change language for non-existent user_id={user_id} from {request.client.host}")
                return RedirectResponse("/users", status_code=303)

            logger.info(f"🌐 Changing language for user_id={user_id} (@{user.username}) to '{lang}'")

            await session.execute(
                update(User).where(User.id == user_id).values(language_code=lang)
            )

            await session.commit()
            logger.info(f"✅ Language '{lang}' set for user_id={user_id}")

    except Exception as e:
        logger.error(f"❌ Error in set_user_language for user_id={user_id}: {e}\n{traceback.format_exc()}")

    return RedirectResponse("/users", status_code=303)

@app.post("/users/set-role")
async def set_user_role(request: Request, user_id: int = Form(...), role: str = Form(...)):
    try:
        async with SessionLocal() as session:
            user = await session.get(User, user_id)
            if not user:
                logger.warning(f"⚠️ Attempt to set role '{role}' for non-existent user_id={user_id} from {request.client.host}")
                return RedirectResponse("/users", status_code=303)

            logger.info(f"🔄 Changing role for user_id={user_id} (@{user.username}) to '{role}'")

            await session.execute(
                update(User).where(User.id == user_id).values(role=role)
            )

            text = None
            if role == "admin":
                username = user.username.lstrip("@")
                email = f"{username}@admin.grandtime.com"
                raw_pw = username + secrets.token_hex(3)
                pw_hash = bcrypt.hashpw(raw_pw.encode(), bcrypt.gensalt()).decode()

                credentials_stmt = mysql_insert(Credentials).values(
                    user_id=user.id,
                    email=email,
                    password_hash=pw_hash
                ).on_duplicate_key_update(
                    password_hash=pw_hash
                )
                await session.execute(credentials_stmt)
                text = f"Email: {email}\nPassword: {raw_pw}"
                logger.info(f"✅ Admin credentials created for user_id={user_id} | email={email}")

            status_stmt = insert(Status).values(
                id=user.id,
                language_code=user.language_code,
                role=role,
                text=text
            )
            await session.execute(status_stmt)

            await session.commit()
            logger.info(f"✅ Role '{role}' assigned to user_id={user_id} successfully")

    except Exception as e:
        logger.error(f"❌ Error in set_user_role for user_id={user_id}: {e}\n{traceback.format_exc()}")

    return RedirectResponse("/users", status_code=303)

@app.get("/requests", dependencies=[Depends(get_current_user)], response_class=HTMLResponse)
async def requests_view(
    request: Request,
    lang: str = "all",
    status: str = "all",
    page: int = 1,
    per_page: int = 20,
):

    offset = (page - 1) * per_page

    client_ip = request.client.host
    current_user = request.scope.get("user")  # если get_current_user это добавляет

    logger.info(
        f"📥 /requests requested by {current_user} from {client_ip} | lang={lang} | status={status} | page={page}, per_page={per_page}"
    )

    async with SessionLocal() as session:
        q = select(SupportRequest) \
            .options(
                selectinload(SupportRequest.user),
                selectinload(SupportRequest.moderator)
            ) \
            .order_by(SupportRequest.created_at.desc())

        if lang != "all":
            q = q.where(SupportRequest.language == lang)
        if status != "all":
            q = q.where(SupportRequest.status == status)

        total_q = select(func.count()).select_from(q.subquery())
        total = await session.scalar(total_q)

        result = await session.execute(
            q.offset(offset).limit(per_page)
        )
        requests_list = result.scalars().all()

        stat_result = await session.execute(
            select(
                SupportRequest.language,
                SupportRequest.status,
                func.count()
            ).group_by(
                SupportRequest.language,
                SupportRequest.status
            )
        )
        raw_stats = stat_result.all()

    lang_stats = {}
    for l, st, cnt in raw_stats:
        rec = lang_stats.setdefault(l, {"total": 0, "pending": 0, "in_progress": 0, "closed": 0})
        rec[st] += cnt
        rec["total"] += cnt

    total_pages = (total + per_page - 1) // per_page

    logger.info(
        f"✅ /requests returned {len(requests_list)} of {total} requests"
    )

    return templates.TemplateResponse("requests.html", {
        "request": request,
        "requests_list": requests_list,
        "lang_stats": lang_stats,
        "total_requests": total,
        "languages": sorted(lang_stats.keys()),
        "statuses": ["pending", "in_progress", "closed"],
        "current_lang": lang,
        "current_status": status,
        "flags": flags,
        "status_labels": status_labels,
        "page": page,
        "total_pages": total_pages,
        "per_page": per_page,
    })

@app.get("/chat/{request_id}", dependencies=[Depends(get_current_user)], response_class=HTMLResponse)
async def chat_view(request: Request, request_id: int):
    client_ip = request.client.host
    current_user = request.scope.get("user")  # если добавляешь юзера в scope

    logger.info(f"💬 /chat/{request_id} requested by {current_user} from {client_ip}")

    async with SessionLocal() as session:
        result = await session.execute(
            select(SupportRequest)
            .options(
                selectinload(SupportRequest.user),
                selectinload(SupportRequest.moderator),
                selectinload(SupportRequest.messages)
            )
            .where(SupportRequest.id == request_id)
        )
        support_request = result.scalar_one_or_none()

        if not support_request:
            logger.warning(f"⚠️ Support request {request_id} not found")
            return HTMLResponse("Request not found", status_code=404)

    messages = []
    for m in sorted(support_request.messages, key=lambda m: m.timestamp):
        photo_url = None
        if m.photo_file_id:
            try:
                photo_url = await resolve_photo_url(m.photo_file_id)
            except Exception as e:
                logger.error(f"❌ Error loading photo for message {m.id} in request {request_id}: {e}")
                logger.debug(traceback.format_exc())

        messages.append({
            "text": m.text,
            "caption": m.caption,
            "photo_url": photo_url,
            "timestamp": m.timestamp,
            "sender_id": m.sender_id,
            "is_user": m.sender_id == support_request.user.id,
            "is_moderator": m.sender_id == (support_request.assigned_moderator_id or 0)
        })

    logger.info(f"✅ Loaded chat for request {request_id} with {len(messages)} messages")

    return templates.TemplateResponse("chat.html", {
        "request": request,
        "support": support_request,
        "messages": messages
    })

if __name__ == "__main__":
    uvicorn.run("main:app", reload=True)