from fastapi import FastAPI

from .config import settings

app = FastAPI(title=settings.app_name)


@app.get("/healthz")
def healthz() -> dict[str, str]:
    return {"status": "ok"}
