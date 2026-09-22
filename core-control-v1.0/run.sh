#!/usr/bin/env bash
set -e
cd "$(dirname "$0")"
python -m uvicorn app:app --reload
