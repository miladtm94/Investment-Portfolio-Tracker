"""Broker and account sync Celery tasks."""
from __future__ import annotations

import logging

from workers.celery_app import celery_app

logger = logging.getLogger(__name__)


@celery_app.task(name="workers.tasks.sync_tasks.sync_all_accounts")
def sync_all_accounts() -> dict[str, str]:
    logger.info("Account sync task executed")
    return {"status": "ok", "task": "sync_all_accounts"}
