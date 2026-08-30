from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.middleware.base import BaseHTTPMiddleware

from app.config import settings
from app.db import init_db, SessionLocal
from app.ingest.auto_sync import start_auto_sync, stop_auto_sync
from app.ingest.wechat_cli.errors import ReaderError
from app.license import LICENSE_BLOCKED, LicenseError, status_from_runtime
from app.models import SyncJob
from app.product import PRODUCT_NAME
from app.routers.api import router
from app.settings_persist import apply_persisted_settings

_LICENSE_ALLOW = {"/api/health", "/api/license", "/api/wechat/status", "/api/restart"}


class LicenseGate(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        path = request.url.path
        if request.method == "OPTIONS" or not path.startswith("/api") or path in _LICENSE_ALLOW:
            return await call_next(request)
        status = status_from_runtime()
        if status.ok:
            return await call_next(request)
        return JSONResponse(
            status_code=403,
            content={"code": LICENSE_BLOCKED, "message": status.message, "detail": status.mode},
        )


def _load_persisted_settings() -> None:
    db = SessionLocal()
    try:
        apply_persisted_settings(db)
    finally:
        db.close()


def _fail_stale_jobs() -> None:
    db = SessionLocal()
    try:
        rows = db.query(SyncJob).filter(SyncJob.status.in_(["queued", "running"])).all()
        for job in rows:
            job.status = "failed"
            job.error_message = "服务已重启，请重新同步"
        if rows:
            db.commit()
    finally:
        db.close()


@asynccontextmanager
async def lifespan(_app: FastAPI):
    start_auto_sync()
    yield
    stop_auto_sync()


def create_app() -> FastAPI:
    init_db()
    _load_persisted_settings()
    _fail_stale_jobs()
    app = FastAPI(title=PRODUCT_NAME, docs_url=None, redoc_url=None, lifespan=lifespan)
    app.add_middleware(LicenseGate)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://127.0.0.1:5173", "http://localhost:5173"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.exception_handler(LicenseError)
    async def license_error_handler(_request, exc: LicenseError):
        return JSONResponse(
            status_code=403,
            content={"code": exc.code, "message": exc.message, "detail": ""},
        )

    @app.exception_handler(ReaderError)
    async def reader_error_handler(_request, exc: ReaderError):
        return JSONResponse(
            status_code=400,
            content={"code": exc.code, "message": exc.public_message, "detail": ""},
        )

    @app.exception_handler(StarletteHTTPException)
    async def http_error_handler(_request, exc: StarletteHTTPException):
        detail = exc.detail if isinstance(exc.detail, str) else "请求失败"
        return JSONResponse(
            status_code=exc.status_code,
            content={"code": "http_error", "message": detail, "detail": ""},
        )

    app.include_router(router, prefix="/api")

    dist = settings.frontend_dist
    if dist.is_dir():
        assets = dist / "assets"
        if assets.is_dir():
            app.mount("/assets", StaticFiles(directory=str(assets)), name="assets")

        @app.get("/{full_path:path}")
        async def spa_fallback(full_path: str):
            target = dist / full_path
            if full_path and target.is_file():
                return FileResponse(target)
            return FileResponse(dist / "index.html")

    return app


app = create_app()
