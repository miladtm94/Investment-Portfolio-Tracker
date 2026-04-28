"""Analytics Celery tasks."""
from __future__ import annotations

import logging

from workers.celery_app import celery_app

logger = logging.getLogger(__name__)


@celery_app.task(name="workers.tasks.analytics_tasks.refresh_analytics")
def refresh_analytics() -> dict[str, str]:
    logger.info("Analytics refresh task executed")
    return {"status": "ok", "task": "refresh_analytics"}
