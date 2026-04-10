# AI Analysis Enhancement Plan — InvestIQ

> **Purpose**: Step-by-step roadmap to transform the current single-prompt AI analysis into a
> professional-grade, multi-signal trading intelligence engine.
>
> **How to use**: Work through phases sequentially across sessions. Each phase has a
> **Session Restart Prompt** — paste it at the start of a new Claude Code session to
> resume with full context.

---

## Status Overview

| Phase | Description | Status |
|-------|-------------|--------|
| 1 | Rich Technical Context (indicators + candlesticks) | ✅ **Complete** |
| 2 | News, Sentiment & Macro Context | ✅ **Complete** |
| 3 | Multi-Agent Architecture | ✅ **Complete** |
| 4.1 | FinBERT Neural Sentiment | ⏳ **Pending** (deferred — large torch dependency) |
| 4.2 | Rule-Based Chart Pattern Detection | ✅ **Complete** |
| 4.3 | On-Chain Data (crypto) | 🔲 Not started |
| 5.1 | AnalysisResult DB schema + persistence | ✅ **Complete** |
| 5.2 | Analysis History UI + outcome tracking | ✅ **Complete** |
| 5.3 | pgvector RAG (similar-setup retrieval) | ⏳ **Pending** |
| 6 | Fine-Tuning (custom model) | 🔲 Not started (needs 500+ labeled examples) |

---

## Current State (as of April 2026)

| Component | What exists |
|-----------|-------------|
| Backend | FastAPI + PostgreSQL + Redis (Docker Compose) |
| AI providers | Claude (`claude-opus-4-6`), OpenAI (`gpt-4o`), Gemini (`gemma-4-31b-it`), Ollama (local) |
| Market data | Yahoo Finance v8 (equities OHLCV 90d), CoinGecko (crypto, Redis-cached) |
| Technical indicators | EMA9/21/50, SMA200, RSI(14), MACD, Bollinger Bands, ATR(14), Stochastic, OBV, Volume ratio, Pivot points, S/R clusters |
| Candlestick patterns | Hammer, Engulfing, Doji, Shooting Star, Morning/Evening Star, Three Soldiers/Crows (last 5 candles) |
| Chart patterns | Head & Shoulders, Double Top/Bottom, Triangles, Flags, Channel, Cup & Handle (rule-based geometry) |
| News | CryptoCompare (crypto), NewsAPI (equities), keyword sentiment scoring |
| Macro | Fear & Greed Index, BTC Dominance, DXY, VIX, 10Y Treasury yield |
| Architecture | 3 parallel specialist agents (cheap model) → synthesis agent (best model) |
| Agents | technical_agent.py, news_agent.py, fundamental_agent.py, synthesis_agent.py |
| Cheap agent model | `gemma-4-26b-a4b-it` (Gemini) / `gemma3:4b` (Ollama) |
| Synthesis model | `gemma-4-31b-it` (Gemini) / `gemma3:4b` (Ollama) |
| Feedback loop | `analysis_results` DB table, every analysis persisted, outcome tracking |
| History UI | `/dashboard/analysis/history` — stats, table, outcome recording, pagination |
| Search | Live asset search (Yahoo Finance + CoinGecko) on Markets page |
| Local inference | Ollama provider via `http://host.docker.internal:11434` with model fallback |

**Key files:**
- `backend/services/trading_analysis_service.py` — orchestrates multi-agent pipeline
- `backend/services/agents/` — technical, news, fundamental, synthesis agents
- `backend/services/agents/_base.py` — LLM provider routing (Claude/OpenAI/Gemini/Ollama)
- `backend/services/technical_engine.py` — TechnicalAnalysisEngine (indicators + candlesticks)
- `backend/services/chart_patterns.py` — ChartPatternDetector (geometric rule-based)
- `backend/services/news_service.py` — news fetching + keyword sentiment
- `backend/services/macro_service.py` — macro context (Fear&Greed, VIX, DXY, yields)
- `backend/routers/trading.py` — `/analyze`, `/search`, `/ollama/status` endpoints
- `backend/routers/analysis_history.py` — `/analysis/history`, `/stats`, outcome PATCH/DELETE
- `backend/shared/models.py` — AnalysisResult ORM model
- `backend/config.py` — all API keys + model names including Ollama config
- `frontend/src/app/dashboard/analysis/[symbol]/page.tsx` — analysis UI (with Local provider)
- `frontend/src/app/dashboard/analysis/history/page.tsx` — history UI
- `frontend/src/app/dashboard/markets/page.tsx` — live asset search + custom assets
- `frontend/src/lib/hooks/useTrading.ts` — API hooks including useAssetSearch, useOllamaStatus

---

## Phase 1 — Rich Technical Context ✅ COMPLETE

**Implemented:**
- `pandas-ta` installed in backend (EMA, RSI, MACD, Bollinger Bands, ATR, Stochastic, OBV)
- `TechnicalAnalysisEngine` in `backend/services/technical_engine.py`
- 90-day OHLCV fetch (extended from 35d)
- Full multi-section prompt: TREND / MOMENTUM / VOLATILITY / VOLUME / KEY LEVELS / PATTERNS
- Chain-of-thought prompting in synthesis agent
- Context grows from ~300 chars to ~1300+ chars per analysis

---

## Phase 2 — News, Sentiment & Macro Context ✅ COMPLETE

**Implemented:**
- `backend/services/news_service.py` — CryptoCompare (crypto) + NewsAPI (equities)
- `backend/services/macro_service.py` — Fear & Greed, BTC Dominance, DXY, VIX, 10Y yield
- All sources fetched in parallel with Redis caching (15-min TTL)
- Keyword-based sentiment scoring (positive/negative/neutral per headline)
- Prompt sections: `=== Recent News & Sentiment ===` + `=== Macro Context ===`
- Graceful degradation — each source failure returns empty string, analysis still proceeds

---

## Phase 3 — Multi-Agent Architecture ✅ COMPLETE

**Implemented:**
- `backend/services/agents/` directory with 4 agents + shared `_base.py`
- **Technical Agent**: chart indicators only, outputs `TechAgentOutput` (Pydantic)
- **News Agent**: headlines + macro, outputs `NewsAgentOutput` with sentiment + macro_regime
- **Fundamental Agent**: uses model training knowledge, outputs `FundAgentOutput` with fair value
- **Synthesis Agent**: receives all 3 JSON blocks, applies horizon-weighted scoring
  - Trading: tech 50% / news 35% / fund 15%
  - Investing: fund 50% / tech 25% / news 25%
- `run_trading_analysis()` runs 3 agents in parallel via `asyncio.gather(return_exceptions=True)`
- Agent failures degrade gracefully to default Pydantic output (analysis continues)
- `_agent_scores` dict returned in payload: `{tech: N, news: N, fund: N}`
- Added **Ollama** as a 4th provider for local/offline inference

**Provider routing (`backend/services/agents/_base.py`):**
- `call_cheap_llm()` → Gemini Flash / GPT-4o-mini / Ollama (specialist agents)
- `call_synthesis_llm()` → Claude Opus / GPT-4o / Gemini Pro / Ollama (synthesis)
- Ollama: HTTP POST to `host.docker.internal:11434/api/chat`, model fallback to `llama3.2:latest`
- Gemini JSON mode: auto-retry without `responseMimeType` on 400 (not all Gemma variants support it)

---

## Phase 4.1 — FinBERT Neural Sentiment ⏳ PENDING

**Status**: Deferred. Current implementation uses keyword-based sentiment in `news_service.py`.

**Reason deferred**: `transformers` + `torch` add ~1.5GB to Docker image, significant cold-start
latency on first call (~440MB model download), and CPU inference can be slow.

**When to implement**: When news quality becomes the limiting factor in prediction accuracy.
Consider running FinBERT as a separate sidecar container to avoid bloating the main backend.

### Implementation Plan

**New file**: `backend/services/sentiment_service.py`

```python
from transformers import pipeline
_finbert = None

def get_finbert():
    global _finbert
    if _finbert is None:
        _finbert = pipeline("sentiment-analysis", model="ProsusAI/finbert", device=-1)
    return _finbert

async def score_headlines(headlines: list[str]) -> list[dict]:
    """Returns [{label: positive|negative|neutral, score: float}]"""
    pipe = get_finbert()
    return pipe(headlines, truncation=True, max_length=512)
```

**Integration**: Replace `_sentiment_label()` in `news_service.py` with `score_headlines()`.

**Alternative**: Use Ollama with a financial-tuned model (`finma-7b-nlp` or `analyst`) for
sentiment scoring — no extra Docker dependency beyond what's already there.

### Phase 4.1 Session Restart Prompt

```
We are building InvestIQ — an AUD-native investment intelligence platform (FastAPI backend,
Next.js 15 frontend, PostgreSQL + Redis via Docker Compose).

Phases 1-3 and 4.2 are complete (indicators, news/macro, multi-agent, chart patterns).
I need to implement Phase 4.1: FinBERT neural sentiment scoring.

Current state: news_service.py uses keyword heuristic (_sentiment_label) for scoring.
Goal: replace with ProsusAI/finbert or an Ollama-based financial sentiment model.

Key files:
- backend/services/news_service.py       — _sentiment_label() is the target
- backend/services/agents/news_agent.py  — consumes news context
- backend/requirements.txt

Option A (recommended): Use Ollama with a financial model instead of torch:
  - Check available models on user's Ollama instance
  - Add a sentiment scoring call in news_service.py using the existing Ollama client

Option B: Add transformers + torch to requirements.txt
  - Create backend/services/sentiment_service.py with lazy FinBERT loader
  - Update news_service.py to call it, fallback to keyword on failure
  - Note: this adds ~1.5GB to Docker image

Test: Run analysis on a news-heavy asset like TSLA or BTC during a major event.

Read AI_ANALYSIS_PLAN.md in the project root for full spec.
```

---

## Phase 4.2 — Chart Pattern Detection ✅ COMPLETE

**Implemented:**
- `backend/services/chart_patterns.py` — `ChartPatternDetector` class
- Patterns: Head & Shoulders, Inverse H&S, Double Top/Bottom, Ascending/Descending Triangle,
  Bull/Bear Flag, Channel (ascending/descending), Cup & Handle
- Each returns `PatternResult(name, direction, confidence, target_move_pct, description)`
- Integrated into `TechnicalAnalysisEngine.build_prompt_context()` via lazy import
- Verified on BTC: 5 patterns detected, technical context grew from 1292 → 1907 chars

---

## Phase 4.3 — On-Chain Data (crypto) 🔲 NOT STARTED

For BTC/ETH, on-chain metrics add powerful fundamental signals:
```
Realized Price: $42,100 (current price above = profit-taking zone)
MVRV Ratio: 2.1 (historical sell zone >3.5)
Exchange outflows: 42,000 BTC/week (accumulation signal)
Active addresses: +12% WoW (growing adoption)
```

**Sources**: Blockchair (free API), Glassnode (paid ~$39/mo), CoinGecko on-chain endpoints.

**When to implement**: After Phase 4.1. On-chain data primarily benefits crypto analysis.

---

## Phase 5.1 — Trade Tracking Schema ✅ COMPLETE

**Implemented:**
- `AnalysisResult` SQLAlchemy model in `backend/shared/models.py`
- Fields: user_id, symbol, name, asset_class, provider, horizon, rec, score, confidence,
  target, stop_loss, entry_price, agent_scores (JSONB), payload (JSONB)
- Outcome fields: outcome_price, outcome_at, outcome_pnl_pct, outcome_correct, outcome_note
- Indexes on: user_id, symbol, created_at
- Table auto-created via `Base.metadata.create_all` on startup

**Every analysis is persisted** in `routers/trading.py` analyze endpoint.
Response includes `_analysis_id` for linking to outcome recording.

---

## Phase 5.2 — Analysis History UI ✅ COMPLETE

**Implemented:**
- `frontend/src/app/dashboard/analysis/history/page.tsx`
- Stats bar: total analyses, with outcomes, win rate %, avg score, avg P&L %
- Table: asset | rec | score (T/N/F agent sub-scores) | entry | target | provider | outcome | P&L | date
- `OutcomeBadge` component: Pending / Correct / Incorrect with color coding
- `OutcomeModal`: price input + yes/no toggle + optional note → PATCH `/analysis/{id}/outcome`
- Pagination (page state, prev/next controls)
- Sidebar link: "AI History" under Trading section

**Backend endpoints** (`backend/routers/analysis_history.py`):
- `GET /api/v1/analysis/history` — paginated, filterable by symbol/provider/horizon
- `GET /api/v1/analysis/stats` — aggregated stats + breakdowns by provider/horizon/rec
- `PATCH /api/v1/analysis/{id}/outcome` — records outcome + auto-computes P&L %
- `DELETE /api/v1/analysis/{id}`

---

## Phase 5.3 — pgvector RAG ⏳ PENDING

**Goal**: Retrieve the 3 most similar historical technical setups and include their outcomes
in the prompt — "You previously saw a similar setup for X that resulted in Y."

### Implementation Plan

**Step 1 — Enable pgvector:**
```sql
-- In Postgres container
CREATE EXTENSION IF NOT EXISTS vector;
ALTER TABLE analysis_results ADD COLUMN embedding vector(1536);
```

**Step 2 — Embedding service** (`backend/services/embedding_service.py`):
```python
# Option A: OpenAI text-embedding-3-small (~$0.00002/call)
# Option B: local all-MiniLM-L6-v2 via sentence-transformers (384 dims, free)
async def embed_text(text: str) -> list[float]:
    ...
```

**Step 3 — Save embedding on analysis persist** (in `routers/trading.py`):
```python
embedding = await embed_text(technical_context)
result.embedding = embedding
```

**Step 4 — Retrieve similar setups before synthesis:**
```python
similar = await find_similar_setups(db, current_embedding, user_id, limit=3)
# Returns: list of (symbol, rec, outcome_correct, outcome_pnl_pct, technical_summary)
```

**Step 5 — Inject into synthesis agent prompt:**
```
=== Similar Historical Setups ===
1. BTC (2025-11-14): RSI 62, MACD bullish, Flag pattern → BUY → ✓ Correct (+8.2%)
2. ETH (2026-01-03): RSI 58, EMA cross, Double Bottom → BUY → ✓ Correct (+5.1%)
3. BTC (2025-09-22): RSI 61, MACD bullish → BUY → ✗ Incorrect (-3.4%)
```

### Phase 5.3 Session Restart Prompt

```
We are building InvestIQ — an AUD-native investment intelligence platform (FastAPI backend,
Next.js 15 frontend, PostgreSQL + Redis via Docker Compose).

Phases 1-4.2 and 5.1/5.2 are complete (full multi-agent pipeline + analysis history UI).
I need to implement Phase 5.3: pgvector RAG for similar-setup retrieval.

Key files:
- backend/shared/models.py              — AnalysisResult model (add embedding column)
- backend/routers/trading.py            — analyze endpoint (embed + save + retrieve)
- backend/services/trading_analysis_service.py — synthesis agent (inject similar setups)
- docker-compose.yml                    — may need pgvector-enabled postgres image

Tasks for this session:
1. Update docker-compose.yml to use pgvector/pgvector:pg16 image instead of plain postgres
2. Enable vector extension in DB (migration or startup)
3. Add embedding vector(384) column to AnalysisResult + update SQLAlchemy model
4. Create backend/services/embedding_service.py:
   - Use sentence-transformers all-MiniLM-L6-v2 (local, 384 dims, no API key)
   - embed_text(str) → list[float]
   - Cache model as singleton
5. In routers/trading.py: after saving analysis, compute and store embedding
6. Add find_similar_setups(db, embedding, user_id, limit=3) query using pgvector cosine distance
7. Pass similar setups context to synthesis agent
8. Test: run two similar BTC analyses and verify the second references the first

Note: Use sentence-transformers (not OpenAI) to avoid API cost per analysis.
Requires adding sentence-transformers to requirements.txt (no GPU needed).

Read AI_ANALYSIS_PLAN.md in the project root for full spec.
```

---

## Phase 6 — Fine-Tuning (Long-term) 🔲 NOT STARTED

**Prerequisites**: 500+ labeled examples with `outcome_correct IS NOT NULL`.
Accumulates via Phase 5.2 outcome tracking — realistically 3-6 months of active use.

**Approach:**
1. Export `analysis_results` where `outcome_correct IS NOT NULL`
2. Format as fine-tuning JSONL (system prompt / technical context / correct recommendation)
3. Fine-tune `Mistral-7B-Instruct` or `Llama-3.1-8B` via LoRA (~$20-50/run on RunPod)
4. Deploy via Ollama as "investiq" provider

### Phase 6 Session Restart Prompt

```
We are building InvestIQ — an AUD-native investment intelligence platform (FastAPI backend,
Next.js 15 frontend, PostgreSQL + Redis via Docker Compose).

Phases 1-5 are complete. We have accumulated enough labeled analysis outcomes in the DB.
I need to prepare and run a fine-tuning job to create a custom trading analysis model.

Check: SELECT COUNT(*) FROM analysis_results WHERE outcome_correct IS NOT NULL;
(need >= 500 rows before proceeding)

Tasks for this session:
1. Export analysis_results as JSONL fine-tuning dataset
   (filter: outcome_correct IS NOT NULL)
2. Format for HuggingFace LoRA (system prompt / technical context / correct JSON output)
3. Create backend/scripts/prepare_finetune_dataset.py
4. Generate LoRA training script for Mistral-7B or Llama-3.1-8B using PEFT library
5. After training: add fine-tuned model as "investiq" provider in config + UI

Read AI_ANALYSIS_PLAN.md for full context.
```

---

## Technology Stack Summary

| Layer | Current (Phase 4.2 complete) | Remaining phases |
|-------|------------------------------|-----------------|
| Indicators | Full pandas-ta suite (EMA, RSI, MACD, BB, ATR, OBV) | — |
| Patterns | pandas-ta candlestick + rule-based chart patterns | — |
| News sentiment | Keyword heuristic | Phase 4.1: FinBERT or Ollama-based |
| News sources | CryptoCompare + NewsAPI | — |
| Macro | Fear & Greed, DXY, VIX, yields, BTC dominance | — |
| AI Architecture | 3 parallel specialist agents + synthesis agent | — |
| Local inference | Ollama (gemma3:4b, llama3.2) | Phase 6: fine-tuned branded model |
| Memory | None | Phase 5.3: pgvector RAG |
| Feedback | Outcome tracking + win rate dashboard | Phase 5.3: RAG integration |
| Custom model | None | Phase 6: LoRA fine-tuned Llama/Mistral |

## Dependency Additions by Phase

```
Phase 1: pandas-ta, pandas, numpy  ✅ installed
Phase 2: httpx (already present), redis caching (already present)  ✅
Phase 3: no new deps  ✅
Phase 4.1: transformers, torch (cpu), accelerate  ⏳ pending
Phase 4.2: no new deps (pure numpy/pandas)  ✅ installed
Phase 5.3: sentence-transformers, pgvector postgres image  ⏳ pending
Phase 6: peft, datasets, trl (for LoRA fine-tuning)  🔲 not started
```

## API Keys Needed by Phase

```
Phase 1: none  ✅
Phase 2: NEWSAPI_KEY (newsapi.org, free 100 req/day)  ✅ configured
Phase 3: no new keys  ✅
Phase 4.1: none (FinBERT local) or none (Ollama)
Phase 5.3: none (sentence-transformers local)
Phase 6: depends on fine-tuning provider
```

---

*Last updated: April 2026. Phases 1–3, 4.2, 5.1, 5.2 are complete and production-ready.
Next priority: Phase 5.3 (pgvector RAG) to close the feedback loop end-to-end.*
