"""Celery application for background task processing."""
from celery import Celery
from config import get_settings

settings = get_settings()

celery_app = Celery(
    "investment_platform",
    broker=settings.celery_broker_url,
    backend=settings.celery_broker_url.replace("/1", "/2"),
    include=[
        "workers.tasks.portfolio_tasks",
        "workers.tasks.market_data_tasks",
        "workers.tasks.sync_tasks",
        "workers.tasks.analytics_tasks",
    ],
)

celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    task_track_started=True,
    task_routes={
        "workers.tasks.sync_tasks.*": {"queue": "high_priority"},
        "workers.tasks.portfolio_tasks.*": {"queue": "default"},
        "workers.tasks.market_data_tasks.*": {"queue": "default"},
        "workers.tasks.analytics_tasks.*": {"queue": "low_priority"},
    },
    beat_schedule={
        "fetch-equity-prices": {
            "task": "workers.tasks.market_data_tasks.fetch_equity_prices",
            "schedule": 60.0,  # Every 60 seconds during market hours
            "options": {"queue": "default"},
        },
        "fetch-crypto-prices": {
            "task": "workers.tasks.market_data_tasks.fetch_crypto_prices",
            "schedule": 30.0,  # Every 30 seconds (crypto 24/7)
            "options": {"queue": "default"},
        },
        "daily-portfolio-snapshot": {
            "task": "workers.tasks.portfolio_tasks.daily_snapshot",
            "schedule": 86400.0,  # Daily
            "options": {"queue": "low_priority"},
        },
    },
)
