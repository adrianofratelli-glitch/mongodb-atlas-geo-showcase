#!/bin/sh
set -e

cd /app/backend
# One worker only: the preflight cache is in-process and the
# workload is Atlas-bound, not CPU-bound.
uvicorn main:app --host 127.0.0.1 --port 8000 --workers 1 &
nginx -g 'daemon off;'
