"""Portfolio-related Celery tasks."""
from __future__ import annotations

import logging

from workers.celery_app import celery_app

logger = logging.getLogger(__name__)


@celery_app.task(name="workers.tasks.portfolio_tasks.daily_snapshot")
def daily_snapshot() -> dict[str, str]:
    logger.info("Daily portfolio snapshot task executed")
    return {"status": "ok", "task": "daily_snapshot"}
