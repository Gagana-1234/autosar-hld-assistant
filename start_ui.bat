@echo off
REM start_ui.bat — Start the AUTOSAR HLD Assistant Streamlit UI

echo ============================================================
echo   AUTOSAR HLD Document Analysis Assistant — Streamlit UI
echo ============================================================

where streamlit >nul 2>&1
if errorlevel 1 (
    echo [ERROR] streamlit not found. Install dependencies first:
    echo   pip install -r requirements.txt
    pause
    exit /b 1
)

echo.
echo [*] Starting Streamlit UI on http://localhost:8501
echo [*] Make sure the API server is running on http://localhost:8000
echo [*] Press Ctrl+C to stop
echo.

streamlit run app/ui/streamlit_app.py --server.port 8501 --server.address localhost
