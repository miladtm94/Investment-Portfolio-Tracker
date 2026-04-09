"""
Investment Intelligence Platform — FastAPI Application
"""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware

from config import get_settings
from database import engine, Base

# Import routers
from routers import auth, portfolio, transactions, analytics, advisor, tax, sync, market_data, bank_import, trading

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)
settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup and shutdown events."""
    logger.info("Starting Investment Intelligence Platform...")

    # Create all tables on startup (use Alembic migrations in production)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    logger.info("Database tables initialized.")
    yield

    logger.info("Shutting down...")
    await engine.dispose()


app = FastAPI(
    title="Investment Intelligence Platform",
    description=(
        "A production-grade investment analytics platform combining portfolio tracking, "
        "AI-powered insights, tax reporting, and multi-broker synchronization."
    ),
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
    lifespan=lifespan,
)

# ─── Middleware ────────────────────────────────────────────────────────────────
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",
        "https://*.vercel.app",       # Vercel preview + production
        "https://app.yourdomain.com", # custom domain (optional)
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.add_middleware(GZipMiddleware, minimum_size=1000)

# ─── Routers ──────────────────────────────────────────────────────────────────
app.include_router(auth.router, prefix="/api/v1/auth", tags=["Authentication"])
app.include_router(portfolio.router, prefix="/api/v1/portfolio", tags=["Portfolio"])
app.include_router(transactions.router, prefix="/api/v1/transactions", tags=["Transactions"])
app.include_router(analytics.router, prefix="/api/v1/analytics", tags=["Analytics"])
app.include_router(advisor.router, prefix="/api/v1/advisor", tags=["AI Advisor"])
app.include_router(tax.router, prefix="/api/v1/tax", tags=["Tax"])
app.include_router(sync.router, prefix="/api/v1/sync", tags=["Sync"])
app.include_router(market_data.router, prefix="/api/v1/market", tags=["Market Data"])
app.include_router(bank_import.router, tags=["Bank Import"])
app.include_router(trading.router, prefix="/api/v1/trading", tags=["Trading"])


@app.get("/health", tags=["Health"])
async def health_check():
    return {
        "status": "healthy",
        "version": "1.0.0",
        "environment": settings.environment,
    }


@app.get("/", tags=["Root"])
async def root():
    return {
        "message": "Investment Intelligence Platform API",
        "docs": "/docs",
        "health": "/health",
    }
