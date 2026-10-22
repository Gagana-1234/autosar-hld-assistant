@echo off
REM start_api.bat — Start the AUTOSAR HLD Assistant FastAPI backend

echo ============================================================
echo   AUTOSAR HLD Document Analysis Assistant — API Server
echo ============================================================

REM Check if virtual environment is active
where uvicorn >nul 2>&1
if errorlevel 1 (
    echo [ERROR] uvicorn not found. Install dependencies first:
    echo   pip install -r requirements.txt
    pause
    exit /b 1
)

REM Ensure data directories exist
if not exist "data\sqlite" mkdir "data\sqlite"
if not exist "data\chroma" mkdir "data\chroma"
if not exist "data\uploads" mkdir "data\uploads"
if not exist "data\sample" mkdir "data\sample"

echo.
echo [*] Starting FastAPI server on http://localhost:8000
echo [*] Swagger UI: http://localhost:8000/api/docs
echo [*] Press Ctrl+C to stop
echo.

uvicorn app.api.main:app --reload --host 0.0.0.0 --port 8000
