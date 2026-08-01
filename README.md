# 🏪 CreditBook

CreditBook is a Django-based business management web app for tracking sales, customers, debts, expenses, income, and staff. It is designed for small businesses that want a simple dashboard-driven workflow with a modern UI.

## ✨ What it includes

- Dashboard with quick business metrics
- Sales tracking with payment method support
- Customer records and debt history
- Outstanding debt tracking with reminder links
- Expense and income logging
- Staff management with login-capable accounts
- Demo data seeding for exploration

## 🚀 Quick start

### Prerequisites
- Python 3.10+
- pip

### Local setup

```bash
python -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate
pip install -r requirements.txt
python manage.py migrate
python manage.py runserver
```

Open http://127.0.0.1:8000/ in your browser.

### Demo data

```bash
python manage.py seed_demo
```

### Production build helper

```bash
./build.sh
```

Set these environment variables before running the build script if you want a superuser created automatically:

```bash
export DJANGO_SUPERUSER_USERNAME=admin
export DJANGO_SUPERUSER_EMAIL=admin@example.com
export DJANGO_SUPERUSER_PASSWORD=strong-password
```

## 🧱 Project structure

```text
sylvaline_ventures/
├── build.sh
├── manage.py
├── requirements.txt
├── sylvaline/
│   ├── settings.py
│   └── urls.py
└── core/
    ├── models.py
    ├── views.py
    ├── forms.py
    ├── templates/
    └── management/commands/seed_demo.py
```

## 🔧 Configuration tips

You can adjust business defaults in [sylvaline/settings.py](sylvaline/settings.py), including:
- BUSINESS_NAME
- BUSINESS_CURRENCY
- TIME_ZONE

## 🔐 Production notes

For production, set a strong secret key and configure allowed hosts before deployment. The app is already set up to use Django’s built-in authentication and staff accounts.

### Northflank deployment

This project is ready for Northflank with a standard Procfile and Gunicorn entrypoint.

Recommended environment variables:
- `SECRET_KEY`
- `DEBUG=False`
- `ALLOWED_HOSTS=your-domain.com,localhost`
- `DATABASE_URL=postgres://...` (optional; SQLite is used by default locally)

The app will start with:

```bash
gunicorn --bind 0.0.0.0:${PORT:-8000} sylvaline.wsgi:application
```
