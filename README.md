<div align="center">

# InvestIQ

**Open-source investment portfolio tracker with AI-powered insights**

[![Python](https://img.shields.io/badge/Python-3.12-3776AB?style=flat-square&logo=python&logoColor=white)](https://python.org)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.115-009688?style=flat-square&logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com)
[![Next.js](https://img.shields.io/badge/Next.js-15-000000?style=flat-square&logo=next.js&logoColor=white)](https://nextjs.org)
[![Docker](https://img.shields.io/badge/Docker-Compose-2496ED?style=flat-square&logo=docker&logoColor=white)](https://docker.com)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg?style=flat-square)](LICENSE)

</div>

---

A self-hosted platform for tracking equities, ETFs, and crypto across multiple brokers — with multi-agent AI analysis, an interactive portfolio advisor, and ATO-compliant tax reporting. Built for Australian investors; works globally.

## Features

**Portfolio**
- Import CSV exports from CommSec, IBKR, Kraken, and more — auto-detected and parsed
- Multi-account view grouped by broker, with active/demo account toggle
- AUD base currency with automatic FX conversion (RBA rates)
- Cost basis tracking (FIFO/LIFO/HIFO), unrealised P&L, dividend income

**AI Analysis**
- Multi-agent pipeline: Technical · News · Fundamental agents run in parallel, synthesised by a best-model provider
- Choose your AI provider: **Gemini · Claude · OpenAI · Ollama · LM Studio**
- Historical backtesting — set an analysis date and verify predictions against actual outcomes
- Professional output: price map, support/resistance, catalysts, risks, agent sub-scores

**AI Portfolio Advisor**
- Chat interface that knows your actual holdings
- Answers questions about risk, P&L, sector exposure, tax-loss harvesting
- Works with any configured provider (no Anthropic credits required)

**Markets & Watchlist**
- Live prices for top crypto and equities (CoinGecko + Yahoo Finance)
- Watchlist with real-time price tracking
- TradingView live candlestick charts on every asset

**Tax**
- ATO CGT rules — 50% discount, FIFO lot tracking, Australian financial year (Jul–Jun)
- Tax summary with realised gains/losses and estimated liability

## Stack

| Layer | Technology |
|---|---|
| Backend | Python 3.12, FastAPI, SQLAlchemy (async), PostgreSQL 16, Redis |
| Frontend | Next.js 15, TypeScript, Tailwind CSS, TanStack Query |
| AI | Anthropic Claude, OpenAI, Google Gemini, Ollama, LM Studio |
| Infrastructure | Docker Compose |

## Quick Start

**Prerequisites:** Docker, Docker Compose

```bash
git clone https://github.com/your-username/investment-portfolio-tracker
cd investment-portfolio-tracker
cp .env.example .env   # add your API keys
docker compose up -d
```

Open [http://localhost:3000](http://localhost:3000) — register, then start importing.

**Minimum viable `.env`** (only one AI key needed):
```env
GEMINI_API_KEY=your-key      # free tier works
# or ANTHROPIC_API_KEY / OPENAI_API_KEY
POSTGRES_DB=investment_platform
JWT_SECRET_KEY=change-me
ENCRYPTION_KEY=32-char-string-here!!
```

## Local AI (no API key needed)

**LM Studio:** Download [LM Studio](https://lmstudio.ai), load any model, enable **Local Server** tab. The app auto-detects it and shows a green dot in the provider selector.

**Ollama:** `ollama serve` then `ollama pull gemma3:4b`. Same auto-detection applies.

## Importing Brokers

| Broker | Format | Notes |
|---|---|---|
| CommSec | CSV export | Equities, ETFs |
| Interactive Brokers | Flex Query CSV | All asset classes |
| Kraken | Trades CSV export | Crypto |
| MooMoo, Stake | CSV | Auto-detected |

Go to **Portfolio** → **Add Portfolio** → select your broker → upload CSV.

## Project Structure

```
backend/
  routers/          # FastAPI endpoints (portfolio, trading, advisor, tax…)
  services/         # Business logic
    agents/         # Multi-agent AI pipeline (_base, technical, news, fundamental, synthesis)
  shared/           # Models, auth, cache
frontend/
  src/app/dashboard/
    page.tsx        # Dashboard overview
    transactions/   # Portfolio management & CSV import
    analysis/       # AI asset analysis
    advisor/        # AI portfolio chat
    markets/        # Live markets
    watchlist/      # Watchlist
    analytics/      # Performance & risk metrics
```

## Contributing

PRs welcome. Please open an issue first for significant changes.

## License

MIT
