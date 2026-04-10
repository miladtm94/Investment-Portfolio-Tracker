"""
Analysis History Router — Phase 5 (Feedback Loop)

Endpoints:
  GET  /analysis/history          — Paginated list of past analyses for current user
  GET  /analysis/stats            — Win rate and performance stats
  PATCH /analysis/{id}/outcome    — Record actual outcome for a past analysis
  DELETE /analysis/{id}           — Delete an analysis record
"""
from __future__ import annotations

import logging
from decimal import Decimal
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import select, func, desc
from sqlalchemy.ext.asyncio import AsyncSession

from database import get_db
from shared.models import User, AnalysisResult
from shared.auth import get_current_user

logger = logging.getLogger(__name__)
router = APIRouter()


# ─── Schemas ──────────────────────────────────────────────────────────────────

class OutcomeUpdate(BaseModel):
    outcome_price: float
    outcome_correct: bool
    outcome_note: Optional[str] = None


class AnalysisHistoryItem(BaseModel):
    id: str
    symbol: str
    name: str
    asset_class: str
    provider: str
    horizon: str
    rec: str
    score: Optional[int]
    confidence: Optional[str]
    target: Optional[float]
    stop_loss: Optional[float]
    entry_price: Optional[float]
    agent_scores: Optional[dict]
    # Outcome
    outcome_price: Optional[float]
    outcome_at: Optional[str]
    outcome_pnl_pct: Optional[float]
    outcome_correct: Optional[bool]
    outcome_note: Optional[str]
    created_at: str


class AnalysisStats(BaseModel):
    total_analyses: int
    with_outcomes: int
    win_rate: Optional[float]          # % of outcome_correct=True
    avg_score: Optional[float]
    avg_pnl_pct: Optional[float]
    by_provider: dict
    by_horizon: dict
    by_asset_class: dict
    by_rec: dict


# ─── Helpers ──────────────────────────────────────────────────────────────────

def _float(v) -> Optional[float]:
    if v is None:
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _to_item(row: AnalysisResult) -> AnalysisHistoryItem:
    return AnalysisHistoryItem(
        id=row.id,
        symbol=row.symbol,
        name=row.name,
        asset_class=row.asset_class,
        provider=row.provider,
        horizon=row.horizon,
        rec=row.rec,
        score=row.score,
        confidence=row.confidence,
        target=_float(row.target),
        stop_loss=_float(row.stop_loss),
        entry_price=_float(row.entry_price),
        agent_scores=row.agent_scores,
        outcome_price=_float(row.outcome_price),
        outcome_at=row.outcome_at.isoformat() if row.outcome_at else None,
        outcome_pnl_pct=_float(row.outcome_pnl_pct),
        outcome_correct=row.outcome_correct,
        outcome_note=row.outcome_note,
        created_at=row.created_at.isoformat(),
    )


# ─── Endpoints ────────────────────────────────────────────────────────────────

@router.get("/history", response_model=dict)
async def get_analysis_history(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    symbol: Optional[str] = Query(None),
    provider: Optional[str] = Query(None),
    horizon: Optional[str] = Query(None),
    with_outcomes_only: bool = Query(False),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Paginated analysis history for the current user."""
    q = select(AnalysisResult).where(AnalysisResult.user_id == current_user.id)

    if symbol:
        q = q.where(AnalysisResult.symbol == symbol.upper())
    if provider:
        q = q.where(AnalysisResult.provider == provider)
    if horizon:
        q = q.where(AnalysisResult.horizon == horizon)
    if with_outcomes_only:
        q = q.where(AnalysisResult.outcome_correct.is_not(None))

    # Count
    count_q = select(func.count()).select_from(q.subquery())
    total = (await db.execute(count_q)).scalar_one()

    # Paginate
    q = q.order_by(desc(AnalysisResult.created_at))
    q = q.offset((page - 1) * page_size).limit(page_size)
    rows = (await db.execute(q)).scalars().all()

    return {
        "total": total,
        "page": page,
        "page_size": page_size,
        "items": [_to_item(r) for r in rows],
    }


@router.get("/stats", response_model=AnalysisStats)
async def get_analysis_stats(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Aggregated win rate and performance statistics."""
    q = select(AnalysisResult).where(AnalysisResult.user_id == current_user.id)
    rows = (await db.execute(q)).scalars().all()

    if not rows:
        return AnalysisStats(
            total_analyses=0, with_outcomes=0, win_rate=None, avg_score=None,
            avg_pnl_pct=None, by_provider={}, by_horizon={}, by_asset_class={}, by_rec={},
        )

    with_outcomes = [r for r in rows if r.outcome_correct is not None]
    correct = [r for r in with_outcomes if r.outcome_correct]

    scores = [r.score for r in rows if r.score is not None]
    pnls = [float(r.outcome_pnl_pct) for r in with_outcomes if r.outcome_pnl_pct is not None]

    def _breakdown(field: str) -> dict:
        d: dict = {}
        for r in rows:
            key = getattr(r, field, "unknown") or "unknown"
            if key not in d:
                d[key] = {"total": 0, "with_outcomes": 0, "wins": 0, "win_rate": None}
            d[key]["total"] += 1
            if r.outcome_correct is not None:
                d[key]["with_outcomes"] += 1
                if r.outcome_correct:
                    d[key]["wins"] += 1
        for key in d:
            if d[key]["with_outcomes"] > 0:
                d[key]["win_rate"] = round(d[key]["wins"] / d[key]["with_outcomes"] * 100, 1)
        return d

    return AnalysisStats(
        total_analyses=len(rows),
        with_outcomes=len(with_outcomes),
        win_rate=round(len(correct) / len(with_outcomes) * 100, 1) if with_outcomes else None,
        avg_score=round(sum(scores) / len(scores), 1) if scores else None,
        avg_pnl_pct=round(sum(pnls) / len(pnls), 2) if pnls else None,
        by_provider=_breakdown("provider"),
        by_horizon=_breakdown("horizon"),
        by_asset_class=_breakdown("asset_class"),
        by_rec=_breakdown("rec"),
    )


@router.patch("/{analysis_id}/outcome", response_model=AnalysisHistoryItem)
async def record_outcome(
    analysis_id: str,
    body: OutcomeUpdate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Record the actual outcome of a past AI analysis (was it right?)."""
    row = await db.get(AnalysisResult, analysis_id)
    if not row or row.user_id != current_user.id:
        raise HTTPException(status_code=404, detail="Analysis not found")

    row.outcome_price = Decimal(str(body.outcome_price))
    row.outcome_correct = body.outcome_correct
    row.outcome_note = body.outcome_note
    row.outcome_at = datetime.now(timezone.utc)

    # Compute P&L % if we have entry price
    if row.entry_price:
        entry = float(row.entry_price)
        direction = 1 if row.rec in ("BUY", "STRONG BUY") else -1
        pnl = (body.outcome_price - entry) / entry * 100 * direction
        row.outcome_pnl_pct = Decimal(str(round(pnl, 4)))

    await db.commit()
    await db.refresh(row)
    return _to_item(row)


@router.delete("/{analysis_id}", status_code=204)
async def delete_analysis(
    analysis_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Delete an analysis record."""
    row = await db.get(AnalysisResult, analysis_id)
    if not row or row.user_id != current_user.id:
        raise HTTPException(status_code=404, detail="Analysis not found")
    await db.delete(row)
    await db.commit()
