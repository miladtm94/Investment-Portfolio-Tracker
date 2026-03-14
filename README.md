<div align="center">

# InvestIQ

### Open-Source Investment Intelligence Platform

**Unified portfolio tracking · AI-powered insights · ATO tax optimisation · Multi-broker sync**

[![Python](https://img.shields.io/badge/Python-3.12-3776AB?style=flat-square&logo=python&logoColor=white)](https://python.org)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.115-009688?style=flat-square&logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com)
[![Next.js](https://img.shields.io/badge/Next.js-15-000000?style=flat-square&logo=next.js&logoColor=white)](https://nextjs.org)
[![TypeScript](https://img.shields.io/badge/TypeScript-5.7-3178C6?style=flat-square&logo=typescript&logoColor=white)](https://typescriptlang.org)
[![PostgreSQL](https://img.shields.io/badge/PostgreSQL-16-336791?style=flat-square&logo=postgresql&logoColor=white)](https://postgresql.org)
[![Redis](https://img.shields.io/badge/Redis-7-DC382D?style=flat-square&logo=redis&logoColor=white)](https://redis.io)
[![Docker](https://img.shields.io/badge/Docker-Compose-2496ED?style=flat-square&logo=docker&logoColor=white)](https://docker.com)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg?style=flat-square)](LICENSE)

---

*Comparable in scope to Sharesight + CoinTracker + Personal Capital + Kubera — AUD-native and ATO-compliant, in a single self-hosted stack.*

[Quick Start](#-quick-start) · [Features](#-features) · [Architecture](#-architecture) · [API Reference](#-api-reference) · [Testing](#-testing) · [Deployment](#-production-deployment) · [Contributing](#-contributing)

</div>

---

## Overview

InvestIQ is a production-grade, full-stack investment intelligence platform that gives investors a single place to track, analyse, and optimise their entire financial portfolio — across equities, ETFs, bonds, mutual funds, cryptocurrency, and stablecoins.

Built specifically for **Australian investors**, InvestIQ uses **AUD as its base reporting currency** throughout and implements the full suite of **ATO (Australian Tax Office)** rules — including the 50% CGT discount, the Australian financial year (1 July – 30 June), RBA exchange rates for cost base conversion, and ATO Schedule 3 / Item 18 output.

**What makes it different:**

- **AUD-native architecture** — every cost base, gain, and tax estimate is in Australian dollars. Foreign-currency transactions (e.g. USD trades on Stake or IBKR) are automatically converted using RBA daily rates, which the ATO explicitly accepts.
- **Full ATO CGT engine** — implements ITAA 1997 Division 115 (50% discount for assets held ≥ 12 months), the correct loss application order per s102-5, LITO, Medicare Levy, and carried-forward losses. Output maps directly to myTax Item 18.
- **Event-sourcing portfolio engine** — portfolio state is never stored as mutable data; it is reconstructed by replaying the immutable transaction ledger. Any point-in-time snapshot is computable with exact accuracy.
- **Lot-level tax tracking** — every buy creates an individual tax lot. Cost base (in AUD), holding period, and gain/loss are computed at the lot level using FIFO, LIFO, or HIFO.
- **Bank & payment platform import** — upload CSV exports from Commonwealth Bank, ANZ, Westpac, NAB, Bendigo Bank, PayPal, Wise, and AirTM. Each statement is auto-detected, parsed, and enriched with RBA FX rates.
- **Agentic AI advisor** — uses Claude with tool use, not a static system prompt. The LLM calls live portfolio functions to fetch real data before answering, producing quantitative, grounded responses.
- **Real broker and exchange sync** — native connectors for Kraken, Coinbase, Binance, and Plaid that import trades, staking rewards, and corporate actions automatically.

---

## Features

### Portfolio Management
- **Multi-account aggregation** — brokerage, SMSF, crypto exchanges, bank accounts, international accounts
- **AUD base currency** — all holdings, gains, and analytics reported in AUD regardless of the account's native currency
- **Event-sourcing reconstruction** — replay transactions to get exact holdings at any point in time
- **Cost basis methods** — FIFO, LIFO, HIFO (switchable per account)
- **Corporate action handling** — stock splits, dividends, mergers, spin-offs, staking rewards, airdrops

### Asset Class Support

| Category | Supported |
|---|---|
| Australian Equities | ASX-listed stocks, LICs, ETFs (CommSec, MooMoo, CMC Invest) |
| International Equities | US stocks, global ETFs (Stake, IBKR) |
| Fixed Income | Bonds, Bond ETFs |
| Cryptocurrency | BTC, ETH, SOL, and 20+ altcoins (Kraken, Coinbase, Binance) |
| Stablecoins | USDT, USDC, and others |
| Cash | AUD, USD, EUR, GBP — all converted to AUD at RBA rates |

### Analytics Engine

| Tier | Metrics |
|---|---|
| **Performance** | Total Return, Annualised CAGR, Time-Weighted Return (TWR), Money-Weighted Return / XIRR, Alpha, Beta |
| **Risk** | Annualised Volatility, Sharpe Ratio, Sortino Ratio, Calmar Ratio, Maximum Drawdown, VaR 95%, CVaR (Expected Shortfall) |
| **Allocation** | Asset Class, Sector, Geography, HHI Concentration Score, Diversification Score |
| **Benchmarking** | vs ASX 200, SPY, QQQ, BTC, or any ticker |

All analytics values are denominated in AUD.

### AI Portfolio Advisor
- Powered by **Claude claude-opus-4-6** with an agentic tool-use loop
- Accesses live portfolio data via 4 real-time tools — never stale context
- Streaming responses via Server-Sent Events (SSE)
- Persistent conversation sessions with full history
- Financial guardrails and mandatory disclaimers

### ATO Tax Reporting

InvestIQ implements Australian tax rules in full:

| Feature | Detail |
|---|---|
| **Financial year** | 1 July – 30 June (e.g. FY2024-25) |
| **CGT discount** | 50% for individuals, 33.33% for SMSF, on assets held ≥ 365 days (ITAA 1997 Div 115) |
| **Loss application order** | Losses applied to non-discount gains first, then discount-eligible gains (s102-5) |
| **Cost base currency** | All cost bases stored and computed in AUD |
| **FX source** | RBA daily rates (ATO-authoritative); Yahoo Finance fallback |
| **Carried-forward losses** | Tracked and applied to future years automatically |
| **ATO output format** | Item 18A (gross gains), 18H (net gain), 18V (losses c/fwd); Schedule 3 ready |
| **Dividend franking credits** | Tracked separately; reduce tax payable |
| **Staking / crypto income** | Recorded as ordinary income in AUD at RBA rate on receipt date |
| **Tax brackets** | 2024-25 ATO marginal rates with LITO and Medicare Levy |
| **TLH scanner** | Finds open lots with unrealized losses; estimates tax saving |
| **Export** | AUD-denominated CSV formatted for tax agents and myTax |

### Bank & Payment Platform Import

Upload transaction history exports directly from:

| Institution | Country | Format |
|---|---|---|
| Commonwealth Bank (CBA) | 🇦🇺 | CSV — Date, Description, Debit, Credit, Balance |
| ANZ | 🇦🇺 | CSV — Date, Details, Debit, Credit, Balance |
| Westpac | 🇦🇺 | CSV — Date, Description, Credits, Debits, Balance |
| NAB | 🇦🇺 | CSV — Date, Time, Transaction Details, Credit, Debit |
| Bendigo Bank | 🇦🇺 | CSV — Transaction Date, Narration, Credit Amount, Debit Amount |
| PayPal | 🌐 | CSV — Date, Name, Type, Status, Currency, Amount |
| Wise (TransferWise) | 🌐 | CSV — TransferWise ID, Date, Amount, Currency, Description |
| AirTM | 🌐 | CSV — Operation ID, Date, Type, Amount, Currency, Status |

- Institution is **auto-detected** from column headers — no manual selection required
- Multi-currency transactions (PayPal USD, Wise EUR, etc.) are **automatically converted to AUD** using RBA rates at the transaction date
- **SHA-256 deduplication** prevents duplicate rows on re-import
- **Preview before confirm** — review parsed rows and deselect any you don't want

### Broker & Exchange Integration

| Provider | Type | Data Imported |
|---|---|---|
| **Plaid** | Traditional brokers (Fidelity, Schwab, Robinhood, etc.) | Investment transactions, dividends |
| **Kraken** | Crypto exchange | Trades, deposits, withdrawals, staking rewards |
| **Coinbase** | Crypto exchange | Order fills, transfers |
| **Binance** | Crypto exchange | Trades |
| **CSV / Excel / JSON** | Any broker export | Auto-detected schema, 20+ broker formats |
| **Australian bank CSVs** | CBA, ANZ, Westpac, NAB, Bendigo | Deposits, withdrawals — AUD native |

### Market Data

| Asset Class | Primary Provider | Fallback |
|---|---|---|
| Equities & ETFs | Polygon.io | Yahoo Finance |
| Cryptocurrency | CoinGecko | — |
| Exchange Rates | RBA Statistics API | Yahoo Finance |

- RBA FX rates are fetched and cached for each transaction date (86,400s TTL for historical, 3,600s for recent)
- 60-second Redis cache TTL for spot prices
- Automated Celery Beat tasks: equities every 60s, crypto every 30s

---

## Architecture

```
┌─────────────────────────────────────────────────────────────────────┐
│                              FRONTEND                                │
│  Next.js 15 · React 19 · TypeScript · TailwindCSS · Recharts        │
│                                                                      │
│  Dashboard │ Holdings │ Analytics │ AI Advisor │ Tax Centre │ Import │
└──────────────────────────────────┬──────────────────────────────────┘
                                   │  HTTPS · REST · Server-Sent Events
┌──────────────────────────────────▼──────────────────────────────────┐
│                           FASTAPI BACKEND                            │
│  Python 3.12 · Pydantic v2 · SQLAlchemy 2 (async) · JWT Auth        │
│                                                                      │
│  ┌──────────────────┐  ┌──────────────────┐  ┌────────────────────┐ │
│  │ Portfolio Engine │  │ Analytics Engine  │  │ AI Advisor Service │ │
│  │                  │  │                  │  │                    │ │
│  │ Event-sourcing   │  │ TWR · Sharpe     │  │ Claude claude-opus-4-6  │ │
│  │ reconstruction   │  │ Sortino · VaR    │  │ Tool-use loop      │ │
│  │ FIFO/LIFO/HIFO   │  │ Beta · Alpha     │  │ SSE streaming      │ │
│  └──────────────────┘  └──────────────────┘  └────────────────────┘ │
│                                                                      │
│  ┌──────────────────┐  ┌──────────────────┐  ┌────────────────────┐ │
│  │ ATO Tax Engine   │  │  FX Service       │  │  Sync Service      │ │
│  │                  │  │                  │  │                    │ │
│  │ ITAA 1997 Div115 │  │ RBA rates (ATO)  │  │ Plaid · Kraken     │ │
│  │ 50% CGT discount │  │ Yahoo fallback   │  │ Coinbase · Binance │ │
│  │ ATO Schedule 3   │  │ Redis cache      │  │ HMAC signing       │ │
│  └──────────────────┘  └──────────────────┘  └────────────────────┘ │
│                                                                      │
│  ┌──────────────────┐  ┌──────────────────┐  ┌────────────────────┐ │
│  │ Bank Import Svc  │  │ Market Data Svc   │  │  9 REST Routers    │ │
│  │                  │  │                  │  │                    │ │
│  │ CBA·ANZ·Westpac  │  │ Polygon → Yahoo  │  │ auth · portfolio   │ │
│  │ NAB·PayPal·Wise  │  │ CoinGecko        │  │ analytics · tax    │ │
│  │ AirTM·Bendigo    │  │ Redis cache      │  │ advisor · sync     │ │
│  │ Auto-detect+FX   │  │                  │  │ bank-import        │ │
│  └──────────────────┘  └──────────────────┘  └────────────────────┘ │
└──────────┬──────────────────────────────────────────────────────────┘
           │
┌──────────▼──────────┐   ┌─────────────────┐   ┌──────────────────────┐
│    PostgreSQL 16     │   │    Redis 7       │   │   Celery Workers     │
│                      │   │                 │   │                      │
│  users               │   │  Price cache    │   │  Price fetch (60s)   │
│  accounts            │   │  FX rate cache  │   │  Crypto fetch (30s)  │
│  assets              │   │  Session cache  │   │  Portfolio snapshot  │
│  transactions (AUD)  │   │  Portfolio snap │   │  Account sync jobs   │
│  tax_lots            │   │  Task queue     │   │  Analytics compute   │
│  holdings            │   └─────────────────┘   └──────────────────────┘
│  prices              │
│  api_credentials     │   ┌─────────────────┐
│  advisor_convos      │   │  Celery Beat     │
│  background_jobs     │   │  (Scheduler)     │
└──────────────────────┘   └─────────────────┘
```

### Key Design Decisions

<details>
<summary><strong>AUD as the Reporting Base Currency</strong></summary>

All cost bases, gains, losses, and tax estimates are stored and computed in Australian dollars. This is required by the ATO — you must report CGT in AUD using the exchange rate at the date of each CGT event.

**How it works:**
- Each `Transaction` row stores `fx_rate_to_aud`, `net_amount_aud`, and `price_per_unit_aud` alongside the original currency amounts
- The `FXService` fetches RBA daily rates (primary) or Yahoo Finance (fallback) for each transaction date
- RBA rates are cached in Redis: 86,400s for historical dates (they never change), 3,600s for recent dates
- The ATO explicitly accepts RBA daily exchange rates for cost base calculations

```python
# Every buy/sell: foreign amount → AUD at the RBA rate on that date
rate = await fx_service.get_aud_rate("USD", on_date=trade_date)
cost_base_aud = quantity * price_usd * rate
```

</details>

<details>
<summary><strong>ATO CGT Engine (ITAA 1997)</strong></summary>

The `ATOTaxEngine` implements the full Australian CGT rules as per the Income Tax Assessment Act 1997:

**CGT Discount (Division 115):**
- Assets held ≥ 365 days qualify for the 50% discount (33.33% for SMSF)
- The discount is applied only after capital losses have been deducted

**Loss Application Order (s102-5):**
```
1. Apply losses to non-discount gains first (short-held assets)
2. Apply remaining losses to discount-eligible gains
3. Apply 50% discount to the remainder
4. Any excess losses carried forward to the next financial year
```

**Tax Rates (2024-25):**
- ATO marginal brackets: 0%, 19%, 32.5%, 37%, 45%
- Low Income Tax Offset (LITO): up to $700 for incomes under $37,500
- Medicare Levy: 2% on taxable income above the threshold

**ATO Schedule 3 Output:**
- Item 18A: Gross capital gains (before discount)
- Item 18H: Net capital gain (after losses and discount)
- Item 18V: Capital losses carried forward to later income years

</details>

<details>
<summary><strong>Bank & Payment Platform Import Pipeline</strong></summary>

The `BankImportService` handles the full lifecycle for uploading bank statements:

```
Upload CSV/Excel
       ↓
Auto-detect institution from column headers
       ↓
Institution-specific parser (CBA, ANZ, Westpac, NAB, Bendigo, PayPal, Wise, AirTM)
       ↓
For each row: SHA-256 hash → check against existing_hashes → skip duplicates
       ↓
FX enrichment: if currency != AUD → fetch RBA rate for transaction date → compute amount_aud
       ↓
Return preview to frontend (user reviews & selects rows)
       ↓
POST /confirm → persist selected rows as DEPOSIT/WITHDRAWAL transactions
```

Each institution has a dedicated parser that normalises its specific column layout. Institution detection is heuristic — it matches column sets — but can be overridden via the `institution` form field.

</details>

<details>
<summary><strong>Event-Sourcing Portfolio Reconstruction</strong></summary>

Portfolio state is **never stored as a mutable "current positions" table**. Every call to the portfolio engine replays the full, ordered transaction ledger from a Redis checkpoint (or from epoch) to produce an exact `PortfolioState` at a given point in time.

**Why this matters:**
- Any `as_of` date query produces provably correct results — no stale data
- Point-in-time portfolio views are computed, not stored: `GET /portfolio/summary?as_of=2024-01-15`
- Corporate actions (splits, mergers) are inserted as synthetic transactions and handled uniformly
- The ledger is immutable; corrections are new transactions, not overwrites

```
reconstruct(user_id, as_of_date):
  1. Load Redis snapshot for nearest prior checkpoint
  2. SELECT transactions WHERE date > checkpoint AND date <= as_of ORDER BY date ASC
  3. Replay each transaction through pure apply_transaction() dispatch function
  4. Hydrate result with current prices from market-data-service
```

</details>

<details>
<summary><strong>Lot-Level Tax Tracking</strong></summary>

Every BUY transaction creates one or more rows in the `tax_lots` table. Holdings are an aggregation view over open lots, not a separate tracked quantity.

```sql
-- Holdings are always derived, never stored independently
SELECT asset_id, SUM(quantity_remaining) as quantity,
       SUM(quantity_remaining * cost_basis_per_unit_aud) as total_cost_basis_aud
FROM tax_lots
WHERE user_id = ? AND lot_status != 'CLOSED'
GROUP BY asset_id
```

When a partial sell occurs, `lot_matcher` closes fractional lots according to the user's configured cost method (FIFO/LIFO/HIFO), updates `quantity_remaining`, and records `realized_gain_aud`, `holding_period_days`, and `discount_eligible` on the lot row. This makes every historical ATO tax report recomputable from the same source of truth.

</details>

<details>
<summary><strong>Claude Agentic Tool-Use Loop</strong></summary>

The AI advisor does **not** inject the portfolio into the system prompt. Instead, Claude is given 4 tool schemas and decides what to fetch based on the user's question. The platform executes real service calls for each tool invocation and returns live data to Claude before synthesis.

```
User: "What's my biggest risk?"

Loop iteration 1:
  Claude → tool_use: get_portfolio_holdings()
  Platform → executes portfolio_engine.get_portfolio_summary()
  Platform → returns: {holdings: [...], total_value_aud: 142000, ...}

Loop iteration 2:
  Claude → tool_use: get_portfolio_analytics(period="1Y")
  Platform → executes analytics_engine.compute_all()
  Platform → returns: {risk: {volatility: 28.4, sharpe: 0.82, ...}}

stop_reason: "end_turn"
Claude → "Your portfolio's annualised volatility is 28.4%,
          driven primarily by your 34% allocation to NVDA (AUD $48,280)..."
```

The loop runs for up to 5 iterations. Token usage is tracked per session for cost attribution.

</details>

---

## Project Structure

```
investment-platform/
│
├── backend/                        # Python FastAPI application
│   ├── main.py                     # FastAPI app factory, 9 router registrations
│   ├── config.py                   # Pydantic settings — AUD defaults, ATO config
│   ├── database.py                 # Async SQLAlchemy engine + session
│   │
│   ├── shared/
│   │   ├── models.py               # All SQLAlchemy ORM models (9 tables, AUD columns)
│   │   ├── auth.py                 # JWT creation, verification, FastAPI deps
│   │   └── cache.py                # Redis async client, cache helpers
│   │
│   ├── services/
│   │   ├── portfolio_engine.py     # Event-sourcing reconstruction, FIFO/LIFO/HIFO
│   │   ├── analytics_engine.py     # TWR, Sharpe, VaR, beta via NumPy/Pandas
│   │   ├── ai_advisor_service.py   # Claude tool-use agentic loop, SSE streaming
│   │   ├── ato_tax_engine.py       # ATO CGT engine — ITAA 1997, 50% discount, Schedule 3
│   │   ├── tax_engine.py           # US-oriented engine (non-AU fallback)
│   │   ├── fx_service.py           # RBA + Yahoo FX rates, AUD conversion, Redis cache
│   │   ├── bank_import_service.py  # CBA/ANZ/Westpac/NAB/Bendigo/PayPal/Wise/AirTM parsers
│   │   ├── market_data_service.py  # Polygon → Yahoo, CoinGecko, Redis cache
│   │   ├── sync_service.py         # Kraken, Coinbase, Binance, Plaid connectors
│   │   └── transaction_import.py   # CSV/Excel/JSON parser, schema detection, dedup
│   │
│   ├── routers/
│   │   ├── auth.py                 # Register, login, profile
│   │   ├── portfolio.py            # Accounts, holdings, net worth
│   │   ├── transactions.py         # CRUD, file import endpoint
│   │   ├── analytics.py            # Performance, risk, allocation, time series
│   │   ├── advisor.py              # Chat, stream, session history
│   │   ├── tax.py                  # ATO endpoints + US fallback endpoints
│   │   ├── bank_import.py          # Bank/payment platform upload & confirm
│   │   ├── sync.py                 # Exchange connect, trigger sync, status
│   │   └── market_data.py          # Prices, history, asset search
│   │
│   ├── workers/
│   │   └── celery_app.py           # Celery app, queue routing, Beat schedule
│   │
│   ├── alembic/
│   │   └── env.py                  # Async Alembic migration environment
│   │
│   └── requirements.txt
│
├── frontend/                       # Next.js 15 application
│   └── src/
│       ├── app/
│       │   ├── layout.tsx          # Root layout, font, dark theme
│       │   ├── providers.tsx       # React Query + Toast providers
│       │   └── dashboard/
│       │       ├── page.tsx        # Main dashboard: metrics, charts, holdings
│       │       ├── analytics/      # Analytics page: performance + risk grid
│       │       ├── transactions/   # Transaction table + import panel
│       │       ├── advisor/        # AI chat interface with streaming
│       │       ├── tax/            # ATO Tax Centre: CGT waterfall, FY selector
│       │       └── import/         # Bank statement import: upload, preview, confirm
│       │
│       ├── components/
│       │   ├── charts/             # PortfolioValueChart, AllocationPie, RiskGauge
│       │   ├── portfolio/          # HoldingsTable
│       │   ├── layout/             # Sidebar, TopBar
│       │   └── ui/                 # MetricCard
│       │
│       └── lib/
│           ├── api/client.ts       # Axios instance, JWT injection, 401 handling
│           ├── hooks/              # usePortfolio, useAnalytics, useAdvisorChat
│           └── utils/formatters.ts # AUD formatters, AU date formats, FY helpers
│
├── infra/
│   ├── docker/
│   │   └── init.sql                # PostgreSQL schema initialisation
│   └── k8s/
│       ├── services/backend.yaml   # Deployment + Service + HPA (2→10 pods)
│       └── ingress/nginx-ingress.yaml  # TLS + rate limiting
│
├── scripts/
│   └── seed_dev_data.py            # Seeds 3 accounts, 13 assets, 30 transactions
│
├── docker-compose.yml              # Full local stack (7 services)
├── .env.example                    # All configuration variables documented
└── README.md
```

---

## Quick Start

### Prerequisites

| Requirement | Version | Notes |
|---|---|---|
| Docker Desktop | 24+ | Includes Docker Compose v2 |
| Git | Any | |
| An Anthropic API key | — | Required for AI Advisor |
| A Polygon.io API key | — | Free tier works for testing |

> **Minimum setup:** Only `ANTHROPIC_API_KEY` and `POLYGON_API_KEY` are required to run the full platform. All broker/exchange keys are optional.

---

### 1. Clone the repository

```bash
git clone https://github.com/your-org/investment-platform.git
cd investment-platform
```

---

### 2. Configure environment variables

```bash
cp .env.example .env
```

Open `.env` and fill in the required values:

```bash
# ── Required ──────────────────────────────────────────────────────────────────
ANTHROPIC_API_KEY=sk-ant-...        # https://console.anthropic.com
POLYGON_API_KEY=...                 # https://polygon.io (free tier available)

# ── Security (generate random values for local dev) ───────────────────────────
JWT_SECRET_KEY=your-32-char-secret-here
ENCRYPTION_KEY=your-32-char-encryption-key!
NEXTAUTH_SECRET=your-nextauth-secret

# ── Australian localisation (defaults are correct for AU investors) ────────────
DEFAULT_TAX_JURISDICTION=AU         # Uses ATO rules — CGT discount, AU financial year
DEFAULT_CURRENCY=AUD
DEFAULT_TIMEZONE=Australia/Sydney
CGT_DISCOUNT_RATE=0.50              # 0.50 for individuals; 0.3333 for SMSF
TAX_YEAR_START_MONTH=7              # Australian FY starts 1 July
TAX_YEAR_START_DAY=1

# ── Optional: Crypto prices (free tier available) ─────────────────────────────
COINGECKO_API_KEY=...

# ── Optional: Broker sync ─────────────────────────────────────────────────────
PLAID_CLIENT_ID=...
PLAID_SECRET=...
PLAID_ENV=sandbox

# ── Optional: Crypto exchange sync ────────────────────────────────────────────
KRAKEN_API_KEY=...
KRAKEN_API_SECRET=...
COINBASE_API_KEY=...
COINBASE_API_SECRET=...
BINANCE_API_KEY=...
BINANCE_API_SECRET=...
```

---

### 3. Start all services

```bash
docker compose up -d
```

Docker Compose starts 7 services. Wait for all health checks to pass (approximately 30 seconds):

```bash
docker compose ps
```

Expected output:

```
NAME                    STATUS              PORTS
investment-postgres     running (healthy)   0.0.0.0:5432->5432/tcp
investment-redis        running (healthy)   0.0.0.0:6379->6379/tcp
investment-backend      running             0.0.0.0:8000->8000/tcp
investment-frontend     running             0.0.0.0:3000->3000/tcp
investment-worker       running
investment-beat         running
investment-flower       running             0.0.0.0:5555->5555/tcp
```

---

### 4. Run database migrations

```bash
docker compose exec backend alembic upgrade head
```

Or let the app auto-create tables on first startup (development only):

```bash
docker compose logs backend | grep "Database tables initialized"
```

---

### 5. Seed development data

```bash
docker compose exec backend python /scripts/seed_dev_data.py
```

Or run the seed script directly:

```bash
cd backend
pip install -r requirements.txt
DATABASE_URL=postgresql+asyncpg://invest:investpass@localhost:5432/investment_platform \
  python ../scripts/seed_dev_data.py
```

The seeder creates:
- **User:** `demo@investiq.io` / `demo1234`
- **3 accounts:** Fidelity Brokerage, Coinbase Exchange, Roth IRA
- **13 assets:** AAPL, MSFT, GOOGL, AMZN, NVDA, JPM, JNJ, SPY, QQQ, AGG, BTC, ETH, SOL
- **30 transactions:** buys, sells, dividends, staking rewards spanning 900 days — all with AUD cost bases computed from RBA rates

---

### 6. Access the platform

| Service | URL | Credentials |
|---|---|---|
| **Frontend Dashboard** | http://localhost:3000 | `demo@investiq.io` / `demo1234` |
| **API Documentation** | http://localhost:8000/docs | Interactive Swagger UI |
| **API (ReDoc)** | http://localhost:8000/redoc | Alternative API docs |
| **Celery Monitor** | http://localhost:5555 | Task queue dashboard |
| **PostgreSQL** | `localhost:5432` | `invest` / `investpass` |
| **Redis** | `localhost:6379` | No auth in dev |

---

### Running Without Docker (Local Development)

**Backend:**

```bash
cd backend
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt

export DATABASE_URL=postgresql+asyncpg://invest:investpass@localhost:5432/investment_platform
export REDIS_URL=redis://localhost:6379/0
export ANTHROPIC_API_KEY=sk-ant-...
export POLYGON_API_KEY=...
export JWT_SECRET_KEY=dev-secret-change-in-prod
export DEFAULT_TAX_JURISDICTION=AU
export DEFAULT_CURRENCY=AUD

uvicorn main:app --reload --port 8000
```

**Celery worker (separate terminal):**

```bash
cd backend
source .venv/bin/activate
celery -A workers.celery_app worker --loglevel=info -Q high_priority,default,low_priority
```

**Frontend:**

```bash
cd frontend
npm install
cp .env.local.example .env.local    # Set NEXT_PUBLIC_API_URL=http://localhost:8000
npm run dev
```

**PostgreSQL + Redis** — use Docker for these even in local dev:

```bash
docker compose up -d postgres redis
```

---

## Configuration Reference

All configuration is loaded from environment variables via Pydantic Settings.

### Application

| Variable | Default | Description |
|---|---|---|
| `ENVIRONMENT` | `development` | `development` \| `staging` \| `production` |
| `LOG_LEVEL` | `INFO` | `DEBUG` \| `INFO` \| `WARNING` \| `ERROR` |
| `DEBUG` | `false` | Enable SQLAlchemy query logging |

### Australian Localisation

| Variable | Default | Description |
|---|---|---|
| `DEFAULT_TAX_JURISDICTION` | `AU` | `AU` uses ATO rules throughout; `US` uses IRS rules |
| `DEFAULT_CURRENCY` | `AUD` | Base reporting currency for all calculations |
| `DEFAULT_TIMEZONE` | `Australia/Sydney` | Used for FY boundary calculations |
| `CGT_DISCOUNT_RATE` | `0.50` | `0.50` for individuals; `0.3333` for SMSF trustees |
| `TAX_YEAR_START_MONTH` | `7` | ATO financial year starts 1 July |
| `TAX_YEAR_START_DAY` | `1` | |

### Database

| Variable | Default | Description |
|---|---|---|
| `DATABASE_URL` | `postgresql+asyncpg://invest:investpass@localhost:5432/investment_platform` | Async PostgreSQL connection string |
| `POSTGRES_USER` | `invest` | PostgreSQL username (Docker Compose) |
| `POSTGRES_PASSWORD` | `investpass` | PostgreSQL password (Docker Compose) |
| `POSTGRES_DB` | `investment_platform` | Database name (Docker Compose) |

### Cache & Queue

| Variable | Default | Description |
|---|---|---|
| `REDIS_URL` | `redis://localhost:6379/0` | Redis connection (cache + FX rate store) |
| `CELERY_BROKER_URL` | `redis://localhost:6379/1` | Redis connection (task queue) |
| `CACHE_TTL_SECONDS` | `300` | Default cache TTL (5 minutes) |

### Security

| Variable | Required | Description |
|---|---|---|
| `JWT_SECRET_KEY` | Yes | Min 32 chars. Used to sign/verify JWT tokens |
| `JWT_EXPIRY_MINUTES` | No (default: 1440) | Token lifetime in minutes |
| `ENCRYPTION_KEY` | Yes | 32-byte key for AES-256-GCM credential encryption |
| `NEXTAUTH_SECRET` | Yes | NextAuth.js secret for frontend sessions |

### AI

| Variable | Required | Description |
|---|---|---|
| `ANTHROPIC_API_KEY` | Yes | Anthropic API key (`sk-ant-...`) |
| `CLAUDE_MODEL` | No (default: `claude-opus-4-6`) | Claude model ID |
| `CLAUDE_MAX_TOKENS` | No (default: `4096`) | Max tokens per response |

### Market Data

| Variable | Required | Description |
|---|---|---|
| `POLYGON_API_KEY` | Yes (equity prices) | Polygon.io API key |
| `COINGECKO_API_KEY` | No | CoinGecko Pro API key (free tier works without) |
| `ALPHA_VANTAGE_API_KEY` | No | Alpha Vantage key (tertiary fallback) |

### Broker Integration (Optional)

| Variable | Description |
|---|---|
| `PLAID_CLIENT_ID` | Plaid client ID |
| `PLAID_SECRET` | Plaid secret key |
| `PLAID_ENV` | `sandbox` \| `development` \| `production` |
| `SNAPTRADE_CLIENT_ID` | SnapTrade client ID |
| `SNAPTRADE_CONSUMER_KEY` | SnapTrade consumer key |

### Crypto Exchange Sync (Optional)

| Variable | Description |
|---|---|
| `KRAKEN_API_KEY` | Kraken API key (requires Trade History permission) |
| `KRAKEN_API_SECRET` | Kraken API secret |
| `COINBASE_API_KEY` | Coinbase Advanced Trade API key |
| `COINBASE_API_SECRET` | Coinbase Advanced Trade API secret |
| `BINANCE_API_KEY` | Binance API key (requires Read Only permission) |
| `BINANCE_API_SECRET` | Binance API secret |

---

## Testing

### Running the Test Suite

**Backend tests:**

```bash
cd backend
pip install pytest pytest-asyncio httpx

# Run all tests
pytest

# Run with coverage
pytest --cov=. --cov-report=term-missing --cov-report=html

# Run specific module
pytest tests/test_portfolio_engine.py -v
pytest tests/test_ato_tax_engine.py -v
pytest tests/test_bank_import_service.py -v

# Run only fast unit tests (skip integration)
pytest -m "not integration" -v
```

**Frontend tests:**

```bash
cd frontend
npm run type-check          # TypeScript type checking
npm run lint                # ESLint
```

---

### Manual API Testing

The quickest way to explore the API is via the interactive Swagger UI at **http://localhost:8000/docs**.

#### Step 1 — Login

```bash
curl -s -X POST http://localhost:8000/api/v1/auth/login \
  -H "Content-Type: application/json" \
  -d '{"email": "demo@investiq.io", "password": "demo1234"}' | jq

export TOKEN="eyJhbGci..."
```

#### Step 2 — Get your portfolio summary (AUD)

```bash
curl -s http://localhost:8000/api/v1/portfolio/summary \
  -H "Authorization: Bearer $TOKEN" | jq '{
    total_market_value_aud,
    total_unrealized_gain_aud,
    holding_count: (.holdings | length)
  }'
```

#### Step 3 — Get ATO tax report for FY2024-25

```bash
# Full ATO summary — financial year 2024-25, FIFO method
curl -s "http://localhost:8000/api/v1/tax/ato/summary?fy=2025&method=FIFO" \
  -H "Authorization: Bearer $TOKEN" | jq '{
    financial_year,
    "18A_gross_gains_aud": .gross_capital_gains_aud,
    "cgt_discount_applied": .cgt_discount_applied,
    "18H_net_capital_gain_aud": .net_capital_gain_aud,
    "18V_losses_carried_forward": .capital_losses_carried_forward,
    franking_credits_aud
  }'
```

#### Step 4 — Get ATO Schedule 3 output for myTax

```bash
# Returns Item 18A, 18B, 18H, 18V labels ready for myTax entry
curl -s "http://localhost:8000/api/v1/tax/ato/schedule3?fy=2025" \
  -H "Authorization: Bearer $TOKEN" | jq
```

#### Step 5 — Upload a bank statement (CBA example)

Prepare your CBA CSV export (download from NetBank → Statements → Export):

```csv
Date,Description,Debit,Credit,Balance
15/01/2025,BPAY PAYMENT - KOGAN,120.00,,4880.00
20/01/2025,TRANSFER FROM SAVINGS,,500.00,5380.00
01/02/2025,COINSPOT PURCHASE,1000.00,,4380.00
```

```bash
# Preview (does not save anything yet)
curl -s -X POST http://localhost:8000/api/bank-import/upload \
  -H "Authorization: Bearer $TOKEN" \
  -F "file=@cba_export.csv" \
  -F "account_id=your-account-uuid" | jq '{
    institution,
    total_rows,
    imported,
    duplicates,
    "first_tx": .transactions[0]
  }'

# Confirm selected transactions (pass import_hashes from the preview)
curl -s -X POST http://localhost:8000/api/bank-import/confirm \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "account_id": "your-account-uuid",
    "institution": "cba",
    "import_hashes": ["abc123...", "def456..."],
    "transactions": [...]
  }' | jq '{saved, skipped_duplicates}'
```

#### Step 6 — Upload a Wise statement (multi-currency)

```bash
# Wise CSVs contain multi-currency rows; each is auto-converted to AUD via RBA rates
curl -s -X POST http://localhost:8000/api/bank-import/upload \
  -H "Authorization: Bearer $TOKEN" \
  -F "file=@wise_statement.csv" \
  -F "institution=wise" \
  -F "account_id=your-account-uuid" | jq '.transactions[] | {date, amount, currency, amount_aud, fx_rate_to_aud}'
```

#### Step 7 — Download ATO tax CSV export

```bash
# AUD-denominated CSV formatted for your tax agent / myTax
curl -s -OJ \
  "http://localhost:8000/api/v1/tax/ato/export/csv?fy=2025&method=FIFO" \
  -H "Authorization: Bearer $TOKEN"
# File: cgt_report_fy2024-25.csv
```

#### Step 8 — Get analytics (AUD-denominated)

```bash
curl -s "http://localhost:8000/api/v1/analytics/?period=1Y&benchmark=SPY" \
  -H "Authorization: Bearer $TOKEN" | jq '{
    twr: .performance.twr_pct,
    sharpe: .risk.sharpe_ratio,
    max_drawdown: .risk.max_drawdown_pct,
    allocation: .allocation.by_asset_class
  }'
```

#### Step 9 — Chat with the AI advisor

```bash
curl -s -X POST http://localhost:8000/api/v1/advisor/chat \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"message": "Am I on track for retirement and what is my CGT exposure this financial year?"}' | jq '{
    content,
    session_id,
    tokens_used: (.input_tokens + .output_tokens)
  }'
```

#### Step 10 — Import broker CSV transactions

```bash
ACCOUNT=$(curl -s -X POST http://localhost:8000/api/v1/portfolio/accounts \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"name": "Stake", "account_type": "BROKERAGE"}' | jq -r '.id')

curl -s -X POST http://localhost:8000/api/v1/transactions/import \
  -H "Authorization: Bearer $TOKEN" \
  -F "file=@stake_transactions.csv" \
  -F "account_id=$ACCOUNT" | jq '{imported, duplicates, errors}'
```

---

### Testing the Portfolio Engine Logic

```bash
# Portfolio as it was at start of FY2024-25 (1 July 2024)
curl -s "http://localhost:8000/api/v1/portfolio/summary?as_of=2024-07-01T00:00:00Z" \
  -H "Authorization: Bearer $TOKEN" | jq '.as_of, (.holdings | length), .total_market_value_aud'
```

---

## API Reference

Full interactive documentation is available at **http://localhost:8000/docs** after startup.

### Authentication

| Method | Endpoint | Description |
|---|---|---|
| `POST` | `/api/v1/auth/register` | Register a new user account |
| `POST` | `/api/v1/auth/login` | Authenticate and receive a JWT |
| `GET` | `/api/v1/auth/me` | Get current user profile |
| `PATCH` | `/api/v1/auth/me` | Update profile, currency, cost basis method |

All endpoints except register and login require an `Authorization: Bearer <token>` header.

---

### Portfolio

| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/api/v1/portfolio/accounts` | List all linked accounts |
| `POST` | `/api/v1/portfolio/accounts` | Create a new account |
| `DELETE` | `/api/v1/portfolio/accounts/{id}` | Deactivate an account |
| `GET` | `/api/v1/portfolio/summary` | Consolidated holdings with live AUD prices |
| `GET` | `/api/v1/portfolio/summary?account_ids=a,b` | Filter to specific accounts |
| `GET` | `/api/v1/portfolio/summary?as_of=2024-07-01` | Point-in-time holdings |
| `GET` | `/api/v1/portfolio/accounts/{id}/holdings` | Holdings for one account |
| `GET` | `/api/v1/portfolio/net-worth` | Net worth breakdown by asset class (AUD) |

---

### Transactions

| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/api/v1/transactions/` | Paginated transaction history |
| `GET` | `/api/v1/transactions/?symbol=AAPL` | Filter by asset symbol |
| `GET` | `/api/v1/transactions/?type=BUY&start_date=2025-01-01` | Filter by type and date |
| `POST` | `/api/v1/transactions/` | Add a manual transaction |
| `DELETE` | `/api/v1/transactions/{id}` | Delete a transaction |
| `POST` | `/api/v1/transactions/import` | Import CSV / Excel / JSON file |

**Supported transaction types:** `BUY` `SELL` `DIVIDEND` `SPLIT` `TRANSFER_IN` `TRANSFER_OUT` `DEPOSIT` `WITHDRAWAL` `STAKE_REWARD` `AIRDROP` `MINING_REWARD` `SWAP` `FEE` `MERGER` `SPIN_OFF`

---

### Analytics

| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/api/v1/analytics/` | Full analytics bundle (AUD-denominated) |
| `GET` | `/api/v1/analytics/?period=YTD&benchmark=QQQ` | Specify period and benchmark |
| `GET` | `/api/v1/analytics/performance` | Performance metrics only |
| `GET` | `/api/v1/analytics/risk` | Risk metrics only |
| `GET` | `/api/v1/analytics/allocation` | Allocation breakdown |
| `GET` | `/api/v1/analytics/portfolio-value-history?period=1Y` | Daily value time series (AUD) |

**Period options:** `1M` `3M` `6M` `YTD` `1Y` `3Y` `ALL`

---

### AI Advisor

| Method | Endpoint | Description |
|---|---|---|
| `POST` | `/api/v1/advisor/chat` | Send a message, get AI response |
| `GET` | `/api/v1/advisor/chat/stream?message=...` | Streaming response via SSE |
| `GET` | `/api/v1/advisor/sessions` | List past conversation sessions |
| `GET` | `/api/v1/advisor/sessions/{id}/messages` | Full message history for a session |
| `DELETE` | `/api/v1/advisor/sessions/{id}` | Delete a conversation |

---

### ATO Tax (Australian users)

All amounts returned in AUD. Uses Australian financial year (1 July – 30 June).

| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/api/v1/tax/ato/summary?fy=2025` | Full ATO tax report — CGT, income, franking credits |
| `GET` | `/api/v1/tax/ato/cgt-events?fy=2025` | Lot-by-lot CGT events with discount eligibility |
| `GET` | `/api/v1/tax/ato/schedule3?fy=2025` | ATO Schedule 3 / Item 18 formatted output for myTax |
| `GET` | `/api/v1/tax/ato/export/csv?fy=2025` | Download AUD CGT report CSV |
| `GET` | `/api/v1/tax/tlh-opportunities` | Tax-loss harvesting opportunities |

**Query parameters:**
- `fy` — financial year end (e.g. `2025` for FY2024-25). Defaults to current FY.
- `method` — cost base method: `FIFO` (default), `LIFO`, `HIFO`
- `other_income_aud` — other assessable income (salary etc.) for marginal rate calculation

**ATO Summary response fields:**

| Field | ATO Item | Description |
|---|---|---|
| `gross_capital_gains_aud` | 18A | Total gains before discount and losses |
| `capital_losses_current_aud` | — | Losses realised this financial year |
| `discount_gains_before_discount` | — | Gains eligible for 50% discount |
| `cgt_discount_applied` | — | The 50% reduction amount |
| `net_capital_gain_aud` | 18H | Assessable net capital gain |
| `capital_losses_carried_forward` | 18V | Losses to carry to next year |
| `dividend_income_aud` | 11 | Franked + unfranked dividends |
| `franking_credits_aud` | 11 | Imputation credits (reduce tax payable) |
| `staking_income_aud` | — | Crypto staking / mining rewards |

---

### Bank & Payment Platform Import

| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/api/bank-import/institutions` | List supported institutions |
| `POST` | `/api/bank-import/upload` | Parse & preview a statement (no data saved) |
| `POST` | `/api/bank-import/confirm` | Persist confirmed transactions |

**Upload form fields:**
- `file` — CSV or Excel file (max 10 MB)
- `institution` — optional hint: `cba`, `anz`, `westpac`, `nab`, `bendigo`, `paypal`, `wise`, `airtm`
- `account_id` — optional account UUID (used for duplicate detection)

---

### Sync

| Method | Endpoint | Description |
|---|---|---|
| `POST` | `/api/v1/sync/connect/exchange` | Store encrypted exchange API credentials |
| `POST` | `/api/v1/sync/accounts/{id}/trigger` | Manually trigger account sync |
| `GET` | `/api/v1/sync/accounts/{id}/status` | Get sync status and last sync time |

---

### Market Data

| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/api/v1/market/prices?symbols=AAPL,BTC,ETH` | Current prices for symbols |
| `GET` | `/api/v1/market/prices/{symbol}` | Current price for one symbol |
| `GET` | `/api/v1/market/prices/{symbol}/history?start=...&end=...` | Historical OHLCV data |
| `GET` | `/api/v1/market/assets/search?q=apple` | Search asset registry |

---

## Database Schema

```
┌──────────────────────────────────────────────────────────────┐
│ users                                                         │
│  id · email · password_hash · full_name                      │
│  preferred_currency · cost_basis_method · tax_country        │
└────────────────────────┬─────────────────────────────────────┘
                         │ 1:many
┌────────────────────────▼─────────────────────────────────────┐
│ accounts                                                      │
│  id · user_id · name · institution_name                      │
│  account_type · account_subtype · is_taxable                 │
│  sync_status · last_synced_at                                │
└──────────────┬───────────────────────────────────────────────┘
               │ 1:many
┌──────────────▼──────────────────────────────────────────────┐
│ transactions                          (immutable ledger)     │
│  id · account_id · user_id · asset_id                       │
│  transaction_type · quantity · price_per_unit                │
│  fees · net_amount · currency                                │
│  ── AUD cost base (ATO-required) ──                          │
│  fx_rate_to_aud · net_amount_aud · price_per_unit_aud        │
│  ─────────────────────────────────                           │
│  transacted_at · settled_at                                  │
│  external_id · import_hash (SHA-256, UNIQUE)                 │
│  institution · source · raw_data (JSONB) · split_ratio       │
└──────────────┬──────────────────────────────────────────────┘
               │
┌──────────────▼──────────────────────────────────────────────┐
│ tax_lots                              (lot-level tracking)   │
│  id · account_id · user_id · asset_id                       │
│  opening_transaction_id · acquired_at                        │
│  quantity_acquired · cost_basis_per_unit · total_cost_basis  │
│  ── all cost basis fields stored in AUD ──                   │
│  quantity_remaining · lot_status (OPEN|PARTIALLY_CLOSED|CLOSED) │
│  closing_transaction_id · closed_at                          │
│  proceeds · realized_gain · holding_period_days              │
│  is_long_term · discount_eligible (≥365 days → ATO 50%)     │
│  is_wash_sale · wash_sale_disallowed_loss                    │
└─────────────────────────────────────────────────────────────┘

┌──────────────────────────────────────────────────────────────┐
│ assets                                (symbol registry)      │
│  id · symbol · name · asset_class · exchange                 │
│  sector · country · coingecko_id · polygon_ticker            │
│  isin · cusip                                                │
└──────────────────────────────────────────────────────────────┘

┌──────────────────────────────────────────────────────────────┐
│ prices                                (time series)          │
│  id · asset_id · price · price_date · price_type · source   │
│  UNIQUE(asset_id, price_date, price_type, source)            │
└──────────────────────────────────────────────────────────────┘

┌──────────────────────────────────────────────────────────────┐
│ holdings                              (materialised snapshot) │
│  id · account_id · user_id · asset_id                       │
│  quantity · average_cost_basis_aud · total_cost_basis_aud    │
│  last_price_aud · market_value_aud · unrealized_gain_aud     │
│  as_of_date                                                  │
└──────────────────────────────────────────────────────────────┘

┌──────────────────────────────────────────────────────────────┐
│ api_credentials               (encrypted exchange keys)      │
│  id · user_id · account_id · provider · credential_type      │
│  encrypted_api_key (BYTEA) · encrypted_api_secret (BYTEA)   │
│  encrypted_access_token · encrypted_refresh_token            │
│  encryption_key_id · token_expires_at · scopes               │
└──────────────────────────────────────────────────────────────┘

┌──────────────────────────────────────────────────────────────┐
│ advisor_conversations         (AI chat history)              │
│  id · user_id · title                                        │
│  messages (JSONB) — full Claude message format               │
│  total_input_tokens · total_output_tokens                    │
└──────────────────────────────────────────────────────────────┘

┌──────────────────────────────────────────────────────────────┐
│ background_jobs               (Celery task tracking)         │
│  id · user_id · job_type · celery_task_id                   │
│  status (PENDING|RUNNING|SUCCESS|FAILED) · result (JSONB)   │
└──────────────────────────────────────────────────────────────┘
```

---

## Production Deployment

### Kubernetes (Recommended)

```bash
kubectl create namespace investment-platform

kubectl create secret generic db-secret \
  --from-literal=url="postgresql+asyncpg://user:pass@postgres:5432/investment_platform" \
  -n investment-platform

kubectl create secret generic api-keys \
  --from-literal=anthropic="sk-ant-..." \
  --from-literal=polygon="..." \
  -n investment-platform

kubectl create secret generic app-secrets \
  --from-literal=jwt-secret="$(openssl rand -hex 32)" \
  --from-literal=encryption-key="$(openssl rand -hex 16)" \
  -n investment-platform

kubectl apply -f infra/k8s/postgres/
kubectl apply -f infra/k8s/redis/
kubectl apply -f infra/k8s/services/
kubectl apply -f infra/k8s/celery/
kubectl apply -f infra/k8s/ingress/

kubectl get pods -n investment-platform
kubectl get hpa -n investment-platform
```

The backend `HorizontalPodAutoscaler` scales **2 → 10 replicas** at 70% CPU utilisation.

---

### Docker Compose (Production)

```bash
docker compose -f docker-compose.yml build

ENVIRONMENT=production \
JWT_SECRET_KEY=$(openssl rand -hex 32) \
ANTHROPIC_API_KEY=sk-ant-... \
DEFAULT_TAX_JURISDICTION=AU \
DEFAULT_CURRENCY=AUD \
  docker compose up -d

docker compose exec backend alembic upgrade head
```

---

### Required External Services

| Service | Purpose | Free Tier |
|---|---|---|
| [Anthropic](https://console.anthropic.com) | AI Advisor (Claude) | Pay-per-use |
| [Polygon.io](https://polygon.io) | Equity market data | Yes (delayed) |
| [CoinGecko](https://coingecko.com/api) | Crypto market data | Yes |
| [RBA Statistics API](https://www.rba.gov.au/statistics/) | AUD exchange rates (ATO-accepted) | Free / public |
| PostgreSQL 16+ | Primary database | Self-hosted |
| Redis 7+ | Cache + task queue + FX rate cache | Self-hosted |

---

## Security

### Authentication
- JWT HS256 tokens with configurable expiry (default 24h)
- `passlib[bcrypt]` password hashing with salt rounds
- Tokens validated on every request via FastAPI dependency injection

### Data Protection
- Exchange API keys encrypted at rest with AES-256-GCM before writing to `api_credentials`
- Encryption uses envelope encryption: a per-record data key encrypted with the master `ENCRYPTION_KEY`
- Raw plaintext API key never persists to disk after the initial write

### Network
- CORS restricted to configured frontend origins only
- Nginx ingress rate limiting: 100 requests/minute per IP
- All production traffic TLS-only (cert-manager + Let's Encrypt)

### Operations
- No secrets in source code or Docker images — all via environment variables / K8s secrets
- `raw_data` JSONB column stores original broker payloads for full audit trail
- `import_hash` (SHA-256) prevents duplicate transaction ingestion on re-imports
- `institution` column on transactions provides a complete audit trail for bank imports

> **Responsible disclosure:** If you discover a security vulnerability, please email security@yourdomain.com rather than opening a public issue.

---

## Transaction Import Format

### Broker CSV (Auto-detected)

The broker CSV importer auto-detects column names using fuzzy matching. Minimum required: `date`, `type`, `symbol`.

| Field | Aliases Accepted |
|---|---|
| `date` | `time`, `datetime`, `trade date`, `transaction date`, `timestamp` |
| `type` | `transaction type`, `action`, `side`, `order type` |
| `symbol` | `ticker`, `asset`, `coin`, `instrument`, `security` |
| `quantity` | `qty`, `shares`, `units`, `size`, `filled qty` |
| `price` | `price per share`, `unit price`, `fill price`, `avg price` |
| `fees` | `fee`, `commission`, `charges` |
| `currency` | `ccy`, `quote currency` |
| `net_amount` | `total`, `net`, `proceeds`, `value`, `subtotal` |

```csv
date,type,symbol,quantity,price,fees,currency
2024-01-10,BUY,AAPL,50,185.50,4.95,USD
2024-03-15,BUY,BTC,0.5,42000.00,21.00,USD
2024-06-01,SELL,AAPL,20,213.00,4.95,USD
2024-09-20,DIVIDEND,SPY,,,0,USD
2024-10-01,STAKE_REWARD,ETH,0.12,2600.00,0,USD
```

### Bank Statement CSV (Institution-specific)

Each Australian bank uses its own column format. InvestIQ auto-detects the institution and applies the matching parser. Download your statement from your bank's internet banking portal and upload it directly — no reformatting required.

**Commonwealth Bank example:**
```csv
Date,Description,Debit,Credit,Balance
15/01/2025,BPAY PAYMENT - ELECTRICITY,220.50,,4779.50
20/01/2025,SALARY - EMPLOYER PTY LTD,,5000.00,9779.50
01/02/2025,COINSPOT PTY LTD,1000.00,,8779.50
```

**Wise (multi-currency) example:**
```csv
TransferWise ID,Date,Amount,Currency,Description,Payment Reference,Running Balance
TX12345678,2025-01-10,-500.00,AUD,Transfer to USD account,,8279.50
TX12345679,2025-01-10,320.45,USD,Received funds,,320.45
```
Multi-currency rows are automatically converted to AUD using the RBA rate on the transaction date.

---

## Roadmap

- [ ] Options contract support (calls, puts, covered writes)
- [ ] On-chain wallet tracking (Ethereum and Bitcoin addresses via Alchemy/Covalent)
- [ ] Mean-variance portfolio optimisation and efficient frontier
- [ ] Risk parity allocation engine
- [ ] IBKR (Interactive Brokers) native API connector
- [ ] SnapTrade aggregation provider integration
- [ ] CommSec / MooMoo / Stake / CMC Invest native connectors
- [ ] PDF tax report generation (ATO Schedule 3, CGT worksheet)
- [ ] SMSF reporting mode (33.33% CGT discount, separate member balances)
- [ ] Automated Alembic migration generation
- [ ] End-to-end test suite (Playwright)
- [ ] OpenTelemetry tracing and Prometheus metrics
- [ ] Mobile-responsive frontend improvements
- [ ] Two-factor authentication (TOTP)
- [ ] NZ investor support (IRD rules)

---

## Contributing

Contributions are welcome. Please follow these steps:

1. **Fork** the repository and create a feature branch:
   ```bash
   git checkout -b feature/my-feature
   ```

2. **Set up your dev environment** using the [Running Without Docker](#running-without-docker-local-development) instructions above.

3. **Follow the code style:**
   - Backend: PEP 8, type annotations on all public functions, async-first
   - Frontend: strict TypeScript, no `any` without a comment explaining why
   - All new API endpoints must have a Pydantic response model
   - All monetary amounts in new code must use `Decimal`, never `float`

4. **Write tests** for new portfolio engine, ATO tax engine, or bank import logic. The reconstruction engine and ATO engine are the most critical paths — changes require test coverage.

5. **Open a pull request** with:
   - A description of what changed and why
   - Any new environment variables added to `.env.example`
   - Updated API reference if endpoints changed

### Development Guidelines

- **Backend services** must be async (`async def`, `await`). Do not block the event loop.
- **All monetary amounts** use `Decimal` — not `float`. Use `Decimal("0.01")` quantisation for AUD display values.
- **AUD cost base** — any new transaction source must populate `fx_rate_to_aud`, `net_amount_aud`, and `price_per_unit_aud` using `FXService` before inserting.
- **Portfolio state mutations** always go through `apply_transaction()` — never modify state directly in a router.
- **Deduplication** — any new transaction source must generate an `import_hash` before inserting.
- **Cache invalidation** — call `cache_invalidate_user(user_id)` after any write that changes portfolio state.
- **No raw SQL** in routers — use the ORM or service layer.

---

## License

```
MIT License

Copyright (c) 2026 InvestIQ Contributors

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT.
```

---

## Disclaimer

InvestIQ is a software tool for tracking and analysing investment data. It is **not a registered tax agent, financial adviser, or accountant** and does not provide financial, legal, or tax advice. All analytics, AI advisor responses, and tax estimates are for informational purposes only.

**Tax information:** ATO tax calculations implement the rules as of FY2024-25 and are based on publicly available ATO guidance. They do not account for individual circumstances, state taxes, trust structures, SMSF-specific rules beyond the CGT discount rate, or legislative changes after the knowledge cut-off. Always consult a **registered tax agent** (BAS agent or tax agent registered with the Tax Practitioners Board) before lodging your tax return.

**Exchange rates:** RBA daily rates are used for ATO cost base conversion. Rates are fetched from the RBA Statistics API and cached. Always verify the rate used against the RBA website for high-value transactions.

**Market data:** Prices may be delayed or inaccurate. Do not make trading decisions based solely on data from this platform.

---

<div align="center">

Built with [FastAPI](https://fastapi.tiangolo.com) · [Next.js](https://nextjs.org) · [Claude](https://anthropic.com) · [PostgreSQL](https://postgresql.org) · [Redis](https://redis.io)

*AUD-native · ATO-compliant · Self-hosted*

</div>
