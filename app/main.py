"""SolarClear FastAPI application: REST API + static single-page UI."""
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from app.config import BASE_DIR, settings
from app.database import connect, init_db
from app.routers import agent, analytics, applications, assets, auth

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("solarclear")
STATIC_DIR = BASE_DIR / "static"


@asynccontextmanager
async def lifespan(_: FastAPI):
    from db.seed import is_seeded, seed

    conn = connect()
    try:
        init_db(conn)
        if not is_seeded(conn):
            log.info("Empty database: loading sample data")
            seed(conn)
    finally:
        conn.close()
    if settings.secret_key == "dev-only-change-me":
        log.warning("SECRET_KEY is not set; using an insecure development key")
    log.info("Agent engine: %s", "D360 AI" if settings.llm_enabled else "offline rule mode")
    yield


app = FastAPI(
    title="D360 AI SolarClear API",
    description="Solar forecasting, DTR hosting capacity and net-meter clearance for distribution utilities.",
    version="1.0.0",
    lifespan=lifespan,
)
for module in (auth, assets, analytics, applications, agent):
    app.include_router(module.router)


@app.exception_handler(Exception)
async def unhandled(_: Request, exc: Exception):
    log.exception("Unhandled error: %s", exc)
    return JSONResponse(status_code=500, content={"detail": "Internal server error"})


@app.get("/api/health", tags=["system"])
def health():
    return {"status": "ok", "llm_enabled": settings.llm_enabled}


app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.get("/", include_in_schema=False)
def index():
    return FileResponse(STATIC_DIR / "index.html")
