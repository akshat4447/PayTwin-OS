"""Commander chat endpoint (deterministic composer; never executes actions)."""
from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from paytwin_api.auth import Principal
from paytwin_api.deps import current_principal, get_db
from paytwin_api.services import commander as commander_svc

router = APIRouter(prefix="/api/commander", tags=["commander"])


class ChatBody(BaseModel):
    message: str
    scope: str | None = None
    incident: str | None = None


@router.post("/chat")
def chat(body: ChatBody, p: Principal = Depends(current_principal),
         db: Session = Depends(get_db)):
    out = commander_svc.handle_message(db, p, body.message)
    return {
        "reply_md": out["reply"],
        "citations": out["citations"],
        "evidence": out["evidence"],
        "tools": [{"name": t, "latency_ms": 0, "args": {"scope": body.scope}}
                  for t in out["tool_trace"]],
        "mode": ("fallback" if get_settings_mode() == "none" else "hosted"),
        "intent": out["intent"],
        "action_request": ({"verdict_present": True}
                           if out["intent"] == "action_policy" else None),
    }


def get_settings_mode() -> str:
    from paytwin_api.config import get_settings

    return get_settings().llm_provider