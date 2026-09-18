import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import text

from app.api import router
from app.db import get_session

logger = logging.getLogger(__name__)

app = FastAPI(title="Kalshi News API")
app.add_middleware(
    CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"]
)
app.include_router(router)


@app.get("/health")
def health():
    """A static {"status": "ok"} dict means a deployed instance with an
    unreachable database still reports healthy and keeps receiving traffic.
    Execute a trivial query so a broken DB connection is actually reflected.
    """
    try:
        with get_session() as session:
            session.execute(text("SELECT 1"))
    except Exception:
        logger.exception("health check failed: database unreachable")
        return JSONResponse(status_code=503, content={"status": "error"})
    return {"status": "ok"}
