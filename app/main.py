from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from .api import api
from .db import Base, engine, SessionLocal
from .models import User  # noqa: F401 确保表注册
from . import models  # noqa: F401
from .auth import hash_password
from .scheduler import start_scheduler, stop_scheduler


def init_data():
    Base.metadata.create_all(engine)
    db = SessionLocal()
    try:
        if db.query(User).count() == 0:
            db.add_all([
                User(username="admin", password_hash=hash_password("admin123"),
                     name="管理员", role="admin"),
                User(username="yunying", password_hash=hash_password("tk123456"),
                     name="运营", role="operator"),
                User(username="sales01", password_hash=hash_password("tk123456"),
                     name="销售", role="sales"),
            ])
            db.commit()
    finally:
        db.close()


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_data()
    start_scheduler()
    yield
    stop_scheduler()


app = FastAPI(title="自由光拓客系统", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware, allow_origins=["*"], allow_methods=["*"],
    allow_headers=["*"], allow_credentials=False,
)
app.include_router(api, prefix="/api")


@app.middleware("http")
async def no_cache_html(request, call_next):
    """HTML/JS 不加缓存，防止用户拿到旧版页面导致功能错位。"""
    resp = await call_next(request)
    ct = resp.headers.get("content-type", "")
    if "text/html" in ct or "javascript" in ct or request.url.path in ("/", "/index.html"):
        resp.headers["Cache-Control"] = "no-store, no-cache, must-revalidate"
        resp.headers["Pragma"] = "no-cache"
        resp.headers["Expires"] = "0"
    return resp


@app.get("/api/health")
def health():
    return {"ok": True}


_web = Path(__file__).resolve().parent.parent / "web"
if _web.exists():
    app.mount("/", StaticFiles(directory=_web, html=True), name="web")
