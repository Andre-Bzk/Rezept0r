import os
from contextlib import asynccontextmanager
from pathlib import Path
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from app.config import get_settings
from app.api import extract, tandoor, history
from app.services.history_service import init_db

settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    os.makedirs(settings.tmp_dir, exist_ok=True)
    for f in Path(settings.tmp_dir).iterdir():
        if f.is_file():
            f.unlink(missing_ok=True)
    init_db()
    yield

app = FastAPI(title="Rezept0r", version="1.0.0", lifespan=lifespan)

app.include_router(extract.router, prefix="/api")
app.include_router(tandoor.router, prefix="/api")
app.include_router(history.router, prefix="/api")

static_dir = Path(__file__).parent / "app" / "static"
app.mount("/static", StaticFiles(directory=static_dir), name="static")


@app.get("/")
async def root():
    return FileResponse(static_dir / "index.html")


@app.get("/v1")
async def v1():
    return FileResponse(static_dir / "v1.html")


@app.get("/v2")
async def v2():
    return FileResponse(static_dir / "v2.html")


@app.get("/v3")
async def v3():
    return FileResponse(static_dir / "v3.html")


@app.get("/v4")
async def v4():
    return FileResponse(static_dir / "v4.html")


@app.get("/v5")
async def v5():
    return FileResponse(static_dir / "v5.html")


@app.get("/api/health")
async def health():
    s = get_settings()
    return {
        "status": "ok",
        "tandoor_configured": bool(s.tandoor_api_token and s.tandoor_base_url),
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host=settings.app_host, port=settings.app_port, workers=1)
