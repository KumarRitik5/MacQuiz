@echo off
cd /d C:\Users\DELL\QuizzApp-RBMI\backend
call C:\Users\DELL\QuizzApp-RBMI\.venv\Scripts\activate.bat
python -m uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
