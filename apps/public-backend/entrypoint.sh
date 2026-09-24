#!/bin/sh
set -eu

if [ -f /vault/secrets/secrets.env ]; then
    . /vault/secrets/secrets.env
fi

exec uvicorn main:app --host 0.0.0.0 --port 8000
