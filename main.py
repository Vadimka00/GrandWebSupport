# main.py
from fastapi import FastAPI, Request, Depends, HTTPException, Cookie, Form
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
from models import SessionLocal, Translation, User, Status, MessageHistory, SupportRequest, Credentials
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
from starlette.responses import Response

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

@app.post("/login", response_class=HTMLResponse)
async def login(
    request: Request,
    email: str = Form(...),
    password: str = Form(...),
    response: Response = None
):
    async with SessionLocal() as session:
        # Правильный способ получить по email
        result = await session.execute(
            select(Credentials).where(Credentials.email == email)
        )
        cred = result.scalar_one_or_none()

        if not cred or not bcrypt.checkpw(password.encode(), cred.password_hash.encode()):
            return templates.TemplateResponse(
                "login.html",
                {"request": request, "error": "Неверная пара логин/пароль"}
            )

        # Успешный вход — ставим куку и редиректим
        response = RedirectResponse("/", status_code=303)
        response.set_cookie("user_id", str(cred.user_id), httponly=True)
        return response

@app.post("/login", response_class=HTMLResponse)
async def login(
    request: Request,
    email: str = Form(...),
    password: str = Form(...),
    response: Response = None
):
    async with SessionLocal() as session:
        cred = await session.get(Credentials, {"email": email})
        if not cred or not bcrypt.checkpw(password.encode(), cred.password_hash.encode()):
            return templates.TemplateResponse("login.html", {"request": request, "error": "Неверная пара логин/пароль"})
        # успешный вход → ставим простую куку
        response = RedirectResponse("/", status_code=303)
        response.set_cookie("user_id", str(cred.user_id), httponly=True)
        return response

@app.get("/logout")
def logout(response: Response):
    response = RedirectResponse("/login", status_code=303)
    response.delete_cookie("user_id")
    return response

def get_current_user(user_id: str = Cookie(None)):
    if not user_id:
        raise HTTPException(status_code=401, detail="Not authenticated")
    return int(user_id)

@app.get("/", dependencies=[Depends(get_current_user)], response_class=HTMLResponse)
async def index(request: Request):
    async with SessionLocal() as session:
        # 1) Пользователи по языкам
        u = await session.execute(
            select(User.language_code, func.count()).group_by(User.language_code)
        )
        user_stats = dict(u.all())
        total_users = sum(user_stats.values())

        # 2) Модераторы по языкам
        m = await session.execute(
            select(User.language_code, func.count())
            .where(User.role == "moderator")
            .group_by(User.language_code)
        )
        mod_stats = dict(m.all())
        total_mods = sum(mod_stats.values())

        # 3) Заявки по языкам и статусам
        r = await session.execute(
            select(SupportRequest.language, SupportRequest.status, func.count())
            .group_by(SupportRequest.language, SupportRequest.status)
        )
        raw = r.all()

    # собираем структуру { lang: { total, pending, in_progress, closed } }
    req_stats = {}
    for lang, st, cnt in raw:
        rec = req_stats.setdefault(lang, {
            "total": 0, "pending": 0, "in_progress": 0, "closed": 0
        })
        rec[st] += cnt
        rec["total"] += cnt
    total_reqs = sum(v["total"] for v in req_stats.values())

    languages = sorted({*user_stats, *mod_stats, *req_stats})
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

@app.get("/translations", dependencies=[Depends(get_current_user)], response_class=HTMLResponse)
async def show_translations(request: Request):
    async with SessionLocal() as session:
        result = await session.execute(
            select(Translation).where(Translation.lang.in_(["ru", "en"]))
        )
        rows = result.scalars().all()

    # Сгруппировать по ключу
    translations = defaultdict(dict)
    langs_set = set()

    for row in rows:
        translations[row.key][row.lang] = row.text
        langs_set.add(row.lang)

    langs = sorted(langs_set)

    return templates.TemplateResponse("translations.html", {
        "request": request,
        "translations": translations,
        "langs": langs,
        "key_descriptions": key_descriptions,
        "flags": flags
    })

@app.post("/update")
async def update_translation(data: UpdateRequest):
    async with SessionLocal() as session:
        await session.execute(
            update(Translation)
            .where(Translation.key == data.key, Translation.lang == data.lang)
            .values(text=data.text)
        )
        await session.commit()
    return JSONResponse(content={"status": "ok"})

@app.get("/users", dependencies=[Depends(get_current_user)], response_class=HTMLResponse)
async def users_view(request: Request, q: str = "", page: int = 1, per_page: int = 20):
    offset = (page - 1) * per_page

    async with SessionLocal() as session:
        # Общее количество (учитывая фильтр, если есть)
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

    total_pages = (total + per_page - 1) // per_page

    return templates.TemplateResponse("users.html", {
        "request": request,
        "total": total,
        "lang_counts": lang_counts,
        "users": users.scalars().all(),
        "query": q,
        "page": page,
        "total_pages": total_pages,
        "flags": flags
    })

@app.post("/users/set-role")
async def set_user_role(user_id: int = Form(...), role: str = Form(...)):
    async with SessionLocal() as session:
        user = await session.get(User, user_id)
        if not user:
            return RedirectResponse("/users", status_code=303)

        # обновляем роль в users
        await session.execute(
            update(User).where(User.id == user_id).values(role=role)
        )

        # если назначили admin — генерим email/пароль и сохраняем/обновляем credentials
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

        # пишем в статус все роли
        status_stmt = insert(Status).values(
            id=user.id,
            language_code=user.language_code,
            role=role,
            text=text
        )
        await session.execute(status_stmt)

        await session.commit()

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

    async with SessionLocal() as session:
        # Базовый запрос с фильтрами
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

        # Общее число заявок после фильтра
        total_q = select(func.count()).select_from(q.subquery())
        total = await session.scalar(total_q)

        # Достаём нужную страницу
        result = await session.execute(
            q.offset(offset).limit(per_page)
        )
        requests_list = result.scalars().all()

        # Статистика (без пагинации)
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

    # Собираем lang_stats
    lang_stats = {}
    for l, st, cnt in raw_stats:
        rec = lang_stats.setdefault(l, {"total": 0, "pending": 0, "in_progress": 0, "closed": 0})
        rec[st] += cnt
        rec["total"] += cnt

    total_pages = (total + per_page - 1) // per_page

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
            return HTMLResponse("Request not found", status_code=404)

    # Загружаем фото для сообщений (если есть)
    messages = []
    for m in sorted(support_request.messages, key=lambda m: m.timestamp):
        photo_url = None
        if m.photo_file_id:
            try:
                photo_url = await resolve_photo_url(m.photo_file_id)
            except Exception as e:
                print(f"Ошибка загрузки фото: {e}")

        messages.append({
            "text": m.text,
            "caption": m.caption,
            "photo_url": photo_url,
            "timestamp": m.timestamp,
            "sender_id": m.sender_id,
            "is_user": m.sender_id == support_request.user.id,
            "is_moderator": m.sender_id == (support_request.assigned_moderator_id or 0)
        })

    return templates.TemplateResponse("chat.html", {
        "request": request,
        "support": support_request,
        "messages": messages
    })


if __name__ == "__main__":
    uvicorn.run("main:app", reload=True)