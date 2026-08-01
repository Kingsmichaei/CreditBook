#!/bin/sh
set -eu

exec python -m gunicorn --bind 0.0.0.0:${PORT:-8000} sylvaline.wsgi:application
