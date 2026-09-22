@echo off
cd /d %~dp0
python -m uvicorn app:app --reload
