import os

try:
    from celery import Celery
except ImportError:  # pragma: no cover - graceful fallback when Celery is unavailable
    Celery = None

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'sylvaline.settings')

if Celery is not None:
    app = Celery('sylvaline')
    app.config_from_object('django.conf:settings', namespace='CELERY')
    app.autodiscover_tasks()
else:
    app = None
