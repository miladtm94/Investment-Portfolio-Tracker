"""Scheduled market data tasks.

These task entrypoints keep Celery worker/beat aligned with the configured
schedule. The API currently refreshes market data on demand, so the scheduled
jobs are lightweight placeholders until a durable background refresh pipeline is
implemented.
"""
from __future__ import annotations

import logging

from workers.celery_app import celery_app

logger = logging.getLogger(__name__)


@celery_app.task(name="workers.tasks.market_data_tasks.fetch_equity_prices")
def fetch_equity_prices() -> dict[str, str]:
    logger.info("Equity price refresh task executed")
    return {"status": "ok", "task": "fetch_equity_prices"}


@celery_app.task(name="workers.tasks.market_data_tasks.fetch_crypto_prices")
def fetch_crypto_prices() -> dict[str, str]:
    logger.info("Crypto price refresh task executed")
    return {"status": "ok", "task": "fetch_crypto_prices"}
