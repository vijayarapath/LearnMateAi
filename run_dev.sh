#!/usr/bin/env bash
# One-command local start (Linux/macOS). Windows: see README.
set -e
[ -d venv ] || python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
[ -f .env ] || cp .env.example .env
python manage.py migrate
python manage.py seed_demo
python manage.py runserver
