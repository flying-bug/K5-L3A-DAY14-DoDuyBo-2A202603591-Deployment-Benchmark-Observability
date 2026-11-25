"""
Production AI Agent — Part 6 Final Project.

Chạy: uvicorn app.main:app --workers 2
Chấm: python check_production_ready.py
"""
import json
import logging
import sys
import time
from contextlib import asynccontextmanager
from typing import Optional

from fastapi import Depends, FastAPI, HTTPException, Request
from pydantic import BaseModel, Field

from app.auth import verify_api_key
from app.config import settings
from app.cost_guard import check_budget, record_cost
from app.rate_limiter import check_rate_limit
from app.redis_client import redis_healthy
from utils.mock_llm import ask as llm_ask


# ── Structured logging (tiêu chí 10) ───────────────────────────────────────
# Logger riêng "agent" (không dùng root/basicConfig) để uvicorn.dictConfig
# (disable_existing_loggers=False nhưng có thể reset handler của root) không
# xoá mất handler của mình — xem phát hiện ở Part 1 / MISSION_ANSWERS.md.
class _JsonLineFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        # log_json() đã json.dumps() sẵn, format() chỉ cần trả nguyên văn.
        return record.getMessage()


_handler = logging.StreamHandler(sys.stdout)
_handler.setFormatter(_JsonLineFormatter())
logger = logging.getLogger("agent")
logger.setLevel(logging.INFO)
logger.handlers = [_handler]
logger.propagate = False


def log_json(event: str, **fields) -> None:
    payload = {"ts": time.time(), "lvl": "INFO", "event": event, **fields}
    logger.info(json.dumps(payload))


# ── Lifespan: startup/shutdown (tiêu chí 11 — graceful shutdown) ──────────
_state = {"ready": False}


@asynccontextmanager
async def lifespan(app: FastAPI):
    _state["ready"] = True
    log_json("startup", environment=settings.environment, port=settings.port)
    yield
    # Uvicorn đã ngừng nhận connection mới và đang chờ request đang chạy xong
    # TRƯỚC khi gọi phần sau "yield" này — /ready trả 503 trong lúc đó.
    _state["ready"] = False
    log_json("shutdown")


app = FastAPI(title="Production AI Agent", lifespan=lifespan)


class AskRequest(BaseModel):
    question: str = Field(..., min_length=1, max_length=2000)
    user_id: Optional[str] = None


@app.middleware("http")
async def log_requests(request: Request, call_next):
    started = time.perf_counter()
    response = await call_next(request)
    log_json(
        "http_request",
        method=request.method,
        path=request.url.path,
        status=response.status_code,
        ms=round((time.perf_counter() - started) * 1000, 2),
    )
    return response


@app.get("/health")
def health():
    """Liveness: luôn 200 khi process còn chạy, kể cả khi Redis chưa sẵn sàng."""
    return {"status": "ok"}


@app.get("/ready")
def ready():
    """Readiness: 200 khi sẵn sàng; 503 khi Redis không kết nối được."""
    if not _state["ready"] or not redis_healthy():
        raise HTTPException(status_code=503, detail="not ready")
    return {"ready": True}


@app.post("/ask")
def ask(body: AskRequest, api_key: str = Depends(verify_api_key)):
    check_rate_limit(api_key)
    check_budget()
    answer = llm_ask(body.question)
    input_tokens = max(1, len(body.question.split()))
    output_tokens = max(1, len(answer.split()))
    cost = record_cost(input_tokens, output_tokens)
    log_json("agent_response", user_id=body.user_id, q_len=len(body.question), cost_usd=cost)
    return {"question": body.question, "answer": answer, "model": "mock-llm"}
