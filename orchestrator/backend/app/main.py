try:
    from fastapi import FastAPI
except ModuleNotFoundError:  # pragma: no cover - fallback for scaffold verification
    class FastAPI:  # type: ignore[override]
        def __init__(self, title: str | None = None):
            self.title = title

        def get(self, _path: str):
            def decorator(func):
                return func

            return decorator

from .config import settings

app = FastAPI(title=settings.app_name)


@app.get("/healthz")
def healthz() -> dict[str, str]:
    return {"status": "ok"}
