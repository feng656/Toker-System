from contextlib import asynccontextmanager
from pathlib import Path
import logging
from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm.exc import StaleDataError
from . import config
from .api import api
from .db import engine


@asynccontextmanager
async def lifespan(app):
    config.validate()
    # 严禁 create_all 吞掉迁移问题；空库由独立 migration 命令初始化。
    with engine.connect() as conn:
        revision = conn.execute(text('SELECT version_num FROM alembic_version')).scalar()
        if revision != '0004_login_catalog':
            raise RuntimeError('数据库迁移未完成，请先执行 alembic upgrade head')
    if config.SCHEDULER_ENABLED:
        from .scheduler import start_scheduler
        start_scheduler()
    yield
    if config.SCHEDULER_ENABLED:
        from .scheduler import stop_scheduler
        stop_scheduler()


app = FastAPI(title='自由光拓客系统后端', version='2.0.0', lifespan=lifespan,
              description='多平台内容与授权工作空间。发布、互动保留人工确认，未配置外部服务时明确失败。')
app.add_middleware(CORSMiddleware, allow_origins=config.CORS_ORIGINS,
                   allow_methods=['GET', 'POST', 'PUT', 'DELETE'], allow_headers=['Authorization', 'Content-Type', 'Idempotency-Key'])
app.include_router(api, prefix='/api/v1')
from .phase2_api import api as phase2_api
app.include_router(phase2_api, prefix='/api/v1')
app.include_router(phase2_api, prefix='/api', include_in_schema=False)
from .media_api import api as media_api
from .automation_api import api as automation_api
for extra in (media_api, automation_api):
    app.include_router(extra, prefix='/api/v1')
    app.include_router(extra, prefix='/api', include_in_schema=False)
# 原页面仍调用/api：短期只作兼容别名，不复制业务逻辑、不污染OpenAPI。
app.include_router(api, prefix='/api', include_in_schema=False)


@app.exception_handler(HTTPException)
async def http_error(request, exc):
    return JSONResponse({'detail': exc.detail, 'code': {401: 'UNAUTHENTICATED', 403: 'FORBIDDEN',
        404: 'NOT_FOUND', 409: 'CONFLICT', 422: 'VALIDATION_ERROR', 503: 'DEPENDENCY_UNAVAILABLE'}.get(exc.status_code, 'REQUEST_ERROR')},
        status_code=exc.status_code, headers=exc.headers)


@app.exception_handler(IntegrityError)
async def integrity_error(request, exc):
    return JSONResponse({'detail': '数据约束冲突，请检查重复记录或关联数据', 'code': 'CONSTRAINT_CONFLICT'}, status_code=409)


@app.exception_handler(StaleDataError)
async def stale_error(request, exc):
    return JSONResponse({'detail': '记录已被其他请求修改，请刷新后重试', 'code': 'STALE_VERSION'}, status_code=409)


@app.exception_handler(RequestValidationError)
async def request_validation_error(request, exc):
    # Pydantic错误默认含input，登录/服务配置校验不得回显密码、邀请码或密钥。
    errors = [{k:v for k,v in error.items() if k in ('loc', 'msg', 'type')} for error in exc.errors()]
    return JSONResponse({'detail': errors, 'code': 'VALIDATION_ERROR'}, status_code=422)


from .llm import AIUnavailable
@app.exception_handler(AIUnavailable)
async def ai_error(request, exc):
    return JSONResponse({'detail': 'AI服务失败或响应无效，请检查配置并重试', 'code': 'DEPENDENCY_UNAVAILABLE'}, status_code=503)


@app.exception_handler(ValueError)
async def value_error(request, exc):
    return JSONResponse({'detail': str(exc), 'code': 'VALIDATION_ERROR'}, status_code=422)


@app.get('/api/v1/health', tags=['健康'])
@app.get('/api/health', include_in_schema=False)
def health():
    try:
        with engine.connect() as conn:
            conn.execute(text('SELECT 1'))
        return {'ok': True, 'database': 'ok', 'demo': config.DEMO_MODE,
                'ai_configured': bool(config.LLM_PROVIDERS), 'storage_configured': bool(config.MINIO_ENDPOINT)}
    except Exception:
        raise HTTPException(503, '数据库不可用')


@app.middleware('http')
async def response_headers(request: Request, call_next):
    response = await call_next(request)
    if request.url.path.startswith('/api') or 'text/html' in response.headers.get('content-type', ''):
        response.headers['Cache-Control'] = 'no-store'
    if request.url.path.startswith('/api/') and not request.url.path.startswith('/api/v1/'):
        response.headers['Deprecation'] = 'true'
        response.headers['Link'] = '</api/v1>; rel="successor-version"'
    response.headers['X-Content-Type-Options'] = 'nosniff'
    return response


web = Path(__file__).resolve().parent.parent / 'web'
if web.exists():
    app.mount('/', StaticFiles(directory=web, html=True), name='web')
