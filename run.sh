#!/usr/bin/env bash
# Setup + jalankan Tokoku. Pakai: ./run.sh
set -e

cd "$(dirname "$0")"

if [ ! -d .venv ]; then
  echo "Membuat virtualenv..."
  python3 -m venv .venv
fi

echo "Install dependency..."
./.venv/bin/pip install --quiet --upgrade pip
./.venv/bin/pip install --quiet -r requirements.txt

echo "Seed data demo..."
./.venv/bin/python seed.py

echo
echo "Server jalan di http://127.0.0.1:5000  (Ctrl+C untuk stop)"
exec ./.venv/bin/python run.py
