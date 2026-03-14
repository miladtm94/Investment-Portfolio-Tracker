"""AI Advisor router — chat, session history, streaming."""
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, desc

from database import get_db
from shared.models import AdvisorConversation, User
from shared.auth import get_current_user
from services.ai_advisor_service import AIAdvisorService
from services.portfolio_engine import PortfolioEngine
from services.analytics_engine import AnalyticsEngine
from services.market_data_service import MarketDataService
from services.tax_engine import TaxEngine

router = APIRouter()


class ChatRequest(BaseModel):
    message: str
    session_id: Optional[str] = None


class ChatResponse(BaseModel):
    content: str
    session_id: str
    tool_calls: list[str]
    input_tokens: int
    output_tokens: int


class ConversationSummary(BaseModel):
    id: str
    title: Optional[str]
    last_active_at: datetime
    total_input_tokens: int
    total_output_tokens: int
    message_count: int


def _get_advisor(db: AsyncSession) -> AIAdvisorService:
    market = MarketDataService()
    portfolio = PortfolioEngine(db, market)
    analytics = AnalyticsEngine(portfolio, market)
    tax = TaxEngine(db, market)
    return AIAdvisorService(db, portfolio, analytics, market, tax)


@router.post("/chat", response_model=ChatResponse)
async def chat(
    body: ChatRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Send a message to the AI portfolio advisor.
    The advisor has access to your real portfolio data via tool use.
    """
    advisor = _get_advisor(db)
    response = await advisor.chat(
        user=current_user,
        message=body.message,
        session_id=body.session_id,
    )
    return ChatResponse(
        content=response.content,
        session_id=response.session_id,
        tool_calls=response.tool_calls,
        input_tokens=response.input_tokens,
        output_tokens=response.output_tokens,
    )


@router.get("/chat/stream")
async def stream_chat(
    message: str,
    session_id: Optional[str] = None,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Stream AI advisor response via Server-Sent Events."""
    advisor = _get_advisor(db)

    async def event_generator():
        try:
            async for token in advisor.stream_chat(
                user=current_user,
                message=message,
                session_id=session_id,
            ):
                yield f"data: {token}\n\n"
            yield "data: [DONE]\n\n"
        except Exception as e:
            yield f"data: [ERROR] {str(e)}\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.get("/sessions", response_model=list[ConversationSummary])
async def list_sessions(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """List all conversation sessions for the current user."""
    result = await db.execute(
        select(AdvisorConversation)
        .where(AdvisorConversation.user_id == current_user.id)
        .order_by(desc(AdvisorConversation.last_active_at))
        .limit(50)
    )
    convs = result.scalars().all()
    return [
        ConversationSummary(
            id=c.id,
            title=c.title,
            last_active_at=c.last_active_at,
            total_input_tokens=c.total_input_tokens,
            total_output_tokens=c.total_output_tokens,
            message_count=len(c.messages) // 2,  # user + assistant pairs
        )
        for c in convs
    ]


@router.get("/sessions/{session_id}/messages")
async def get_session_messages(
    session_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get full message history for a session."""
    result = await db.execute(
        select(AdvisorConversation).where(
            AdvisorConversation.id == session_id,
            AdvisorConversation.user_id == current_user.id,
        )
    )
    conv = result.scalar_one_or_none()
    if not conv:
        raise HTTPException(status_code=404, detail="Session not found")

    # Extract user-facing messages (role: user/assistant, text only)
    messages = []
    for msg in conv.messages:
        role = msg.get("role", "")
        content = msg.get("content", "")
        if isinstance(content, str):
            messages.append({"role": role, "content": content})
        elif isinstance(content, list):
            text = " ".join(
                block.get("text", "") for block in content
                if isinstance(block, dict) and block.get("type") == "text"
            )
            if text:
                messages.append({"role": role, "content": text})

    return {"session_id": session_id, "messages": messages}


@router.delete("/sessions/{session_id}", status_code=204)
async def delete_session(
    session_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(AdvisorConversation).where(
            AdvisorConversation.id == session_id,
            AdvisorConversation.user_id == current_user.id,
        )
    )
    conv = result.scalar_one_or_none()
    if not conv:
        raise HTTPException(status_code=404, detail="Session not found")
    await db.delete(conv)
    await db.commit()
