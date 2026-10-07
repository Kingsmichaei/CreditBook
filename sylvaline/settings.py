from pathlib import Path
from decouple import Csv, config
import dj_database_url

try:
    from celery.schedules import crontab
except ImportError:  # pragma: no cover - graceful fallback when Celery is unavailable
    crontab = None

try:
    import django_celery_beat  # noqa: F401
except ImportError:  # pragma: no cover - graceful fallback when package is unavailable
    DJANGO_CELERY_BEAT_INSTALLED = False
else:
    DJANGO_CELERY_BEAT_INSTALLED = True

BASE_DIR = Path(__file__).resolve().parent.parent

SECRET_KEY = config('SECRET_KEY', default='django-insecure-sylvaline-ventures-change-in-production-2024')

DEBUG = config('DEBUG', default=False, cast=bool)

ALLOWED_HOSTS = config('ALLOWED_HOSTS', default='127.0.0.1,localhost', cast=Csv())
CSRF_TRUSTED_ORIGINS = config('CSRF_TRUSTED_ORIGINS', default='', cast=Csv())

INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'django.contrib.humanize',
    'crispy_forms',
    'crispy_bootstrap5',
    'core',
    'billing',
    'console',
]

if DJANGO_CELERY_BEAT_INSTALLED:
    INSTALLED_APPS.insert(INSTALLED_APPS.index('billing') + 1, 'django_celery_beat')

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'whitenoise.middleware.WhiteNoiseMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'core.middleware.TenantMiddleware',        # must run first — sets request.tenant
    'billing.middleware.SubscriptionMiddleware',  # reads request.tenant set above
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

ROOT_URLCONF = 'sylvaline.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.debug',
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
                'core.context_processors.business_stats',
            ],
        },
    },
]

WSGI_APPLICATION = 'sylvaline.wsgi.application'

DATABASE_URL = config('DATABASE_URL', default='')

if DATABASE_URL and DATABASE_URL != 'postgres://sylvaline:your-password@localhost:5432/sylvaline':
    DATABASES = {
        'default': dj_database_url.config(default=DATABASE_URL, conn_max_age=600)
    }
else:
    DB_ENGINE = config('DB_ENGINE', default='django.db.backends.sqlite3')
    if DB_ENGINE == 'django.db.backends.postgresql':
        DATABASES = {
            'default': {
                'ENGINE': DB_ENGINE,
                'NAME': config('DB_NAME', default='sylvaline'),
                'USER': config('DB_USER', default='sylvaline'),
                'PASSWORD': config('DB_PASSWORD', default=''),
                'HOST': config('DB_HOST', default='localhost'),
                'PORT': config('DB_PORT', default='5432'),
            }
        }
    else:
        DATABASES = {
            'default': {
                'ENGINE': DB_ENGINE,
                'NAME': BASE_DIR / 'db.sqlite3',
            }
        }

AUTH_PASSWORD_VALIDATORS = [
    {'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator'},
    {'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator'},
    {'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator'},
    {'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator'},
]

LANGUAGE_CODE = 'en-us'
TIME_ZONE = 'Africa/Lagos'
USE_I18N = True
USE_TZ = True

STATIC_URL = '/static/'
STATIC_ROOT = BASE_DIR / 'staticfiles'
STATICFILES_DIRS = [BASE_DIR / 'static']
STATICFILES_STORAGE = 'whitenoise.storage.CompressedManifestStaticFilesStorage'

DEFAULT_FILE_STORAGE = 'django.core.files.storage.FileSystemStorage'

MEDIA_URL = '/media/'
MEDIA_ROOT = BASE_DIR / 'media'

DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

NOMBA_CLIENT_ID = config('NOMBA_CLIENT_ID', default='')
NOMBA_CLIENT_SECRET = config('NOMBA_CLIENT_SECRET', default='')
NOMBA_ACCOUNT_ID = config('NOMBA_ACCOUNT_ID', default='')
NOMBA_WEBHOOK_SECRET = config('NOMBA_WEBHOOK_SECRET', default='')
NOMBA_BASE_URL = config('NOMBA_BASE_URL', default='')
SUBSCRIPTION_PRICE_NGN = config('SUBSCRIPTION_PRICE_NGN', default='')
REDIS_URL = config('REDIS_URL', default='redis://localhost:6379/0')
DEFAULT_FROM_EMAIL = config('DEFAULT_FROM_EMAIL', default=config('SMTP_FROM_EMAIL', default='no-reply@creditbook.com'))
SITE_DOMAIN = config('SITE_DOMAIN', default='http://127.0.0.1:8000')

CELERY_BROKER_URL = REDIS_URL
CELERY_RESULT_BACKEND = REDIS_URL
CELERY_TIMEZONE = 'Africa/Lagos'
CELERY_BEAT_SCHEDULE = {
    'charge-subscriptions-daily': {
        'task': 'billing.tasks.charge_due_subscriptions',
        'schedule': crontab(hour=0, minute=30) if crontab else None,
    },
    'expire-trials-daily': {
        'task': 'billing.tasks.expire_trials',
        'schedule': crontab(hour=0, minute=0) if crontab else None,
    },
    'trial-ending-reminders-daily': {
        'task': 'billing.tasks.send_trial_ending_reminders',
        'schedule': crontab(hour=0, minute=15) if crontab else None,
    },
}

CRISPY_ALLOWED_TEMPLATE_PACKS = 'bootstrap5'
CRISPY_TEMPLATE_PACK = 'bootstrap5'

LOGIN_URL = '/login/'
LOGIN_REDIRECT_URL = '/dashboard/'
LOGOUT_REDIRECT_URL = '/login/'

EMAIL_BACKEND = 'django.core.mail.backends.smtp.EmailBackend'
EMAIL_HOST = config('SMTP_HOST', default='smtp.gmail.com')
EMAIL_PORT = config('SMTP_PORT', default=587, cast=int)
EMAIL_HOST_USER = config('SMTP_USERNAME', default='')
EMAIL_HOST_PASSWORD = config('SMTP_PASSWORD', default='')
EMAIL_USE_TLS = config('SMTP_USE_TLS', default=True, cast=bool)
DEFAULT_FROM_EMAIL = config('SMTP_FROM_EMAIL', default='no-reply@creditbook.com')
SERVER_EMAIL = config('SMTP_FROM_EMAIL', default='no-reply@creditbook.com')
EMAIL_SUBJECT_PREFIX = '[CreditBook] '
PASSWORD_RESET_TIMEOUT = config('PASSWORD_RESET_TOKEN_EXPIRE_MINUTES', default=30, cast=int) * 60

BUSINESS_NAME = "CreditBook"
BUSINESS_CURRENCY = "₦"
