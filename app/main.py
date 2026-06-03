"""FastAPI application factory and entrypoint.

Run locally with::

    uvicorn app.main:app --reload
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse

from app.api.router import api_router
from app.core.config import get_settings
from app.core.http_client import http_client
from app.core.logging import get_logger, setup_logging
from app.schemas.common import HealthResponse

DESCRIPTION = """
**OSINTp** is a modular OSINT framework that gathers open-source intelligence
from public, no-authentication sources.

Modules:

* **Username** — enumerate a handle across ~30 platforms.
* **Email** — syntax, MX deliverability, Gravatar (+ optional HIBP breaches).
* **Domain** — DNS records, WHOIS, TLS certificate, CT-log subdomains.
* **IP** — geolocation, reverse DNS (+ optional ipinfo.io).
* **Investigate** — auto-detect a target type and aggregate the above.

> ⚠️ Use responsibly and lawfully. Only query data you are authorised to access.
"""


@asynccontextmanager
async def lifespan(app: FastAPI):
    setup_logging()
    logger = get_logger("app")
    await http_client.start()
    logger.info("OSINTp started (%s)", get_settings().environment)
    try:
        yield
    finally:
        await http_client.stop()
        logger.info("OSINTp shut down")


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title=settings.app_name,
        version=settings.app_version,
        description=DESCRIPTION,
        lifespan=lifespan,
        contact={"name": "OSINTp", "url": "https://github.com/zapayox30/osintp"},
        license_info={"name": "MIT"},
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(api_router, prefix="/api")

    web_index = Path(__file__).parent / "web" / "index.html"

    @app.get("/", tags=["meta"], include_in_schema=False)
    async def console() -> FileResponse:
        """Serve the command-center console (single-page app)."""
        return FileResponse(web_index)

    @app.get("/health", tags=["meta"], response_model=HealthResponse)
    async def health() -> HealthResponse:
        return HealthResponse(
            app=settings.app_name,
            version=settings.app_version,
            environment=settings.environment,
        )

    return app


app = create_app()
