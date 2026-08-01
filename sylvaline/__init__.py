try:
    from .celery import app as celery_app
except Exception:  # pragma: no cover - fallback when Celery is unavailable
    celery_app = None

__all__ = ('celery_app',)
