import os
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.api.accounts import account_router, admin_router
from app.api.ai import router as ai_router
from app.api.search import index_router, router as search_router

STATIC_DIR = Path(__file__).with_name("static")


def create_app() -> FastAPI:
    application = FastAPI(
        title="Favorites Hub API",
        version="0.1.0",
    )
    allowed_origins = _allowed_origins()
    if allowed_origins:
        application.add_middleware(
            CORSMiddleware,
            allow_origins=allowed_origins,
            allow_methods=["GET", "POST", "PUT", "DELETE"],
            allow_headers=[
                "Authorization",
                "Content-Type",
                "Idempotency-Key",
                "AI-Job-Id",
            ],
        )

    application.include_router(admin_router)
    application.include_router(account_router)
    application.include_router(ai_router)
    application.include_router(index_router)
    application.include_router(search_router)
    application.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

    @application.get("/admin", include_in_schema=False, response_class=FileResponse)
    def admin_page() -> FileResponse:
        return FileResponse(
            STATIC_DIR / "admin.html",
            media_type="text/html",
            headers={
                "Cache-Control": "no-store",
                "Content-Security-Policy": (
                    "default-src 'self'; script-src 'self'; style-src 'self'; "
                    "img-src 'self' data:; connect-src 'self'; object-src 'none'; "
                    "base-uri 'none'; frame-ancestors 'none'; form-action 'self'"
                ),
                "Referrer-Policy": "no-referrer",
                "X-Content-Type-Options": "nosniff",
                "X-Frame-Options": "DENY",
            },
        )

    @application.get("/health", tags=["system"])
    def health() -> dict[str, str]:
        return {"status": "ok"}

    return application


def _allowed_origins() -> list[str]:
    origins = [
        origin.strip().rstrip("/")
        for origin in os.getenv("CORS_ALLOWED_ORIGINS", "").split(",")
        if origin.strip()
    ]
    if "*" in origins:
        raise RuntimeError("CORS_ALLOWED_ORIGINS 禁止使用通配符")
    return list(dict.fromkeys(origins))


app = create_app()
