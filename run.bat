@echo off
REM Quick start script for the SAS Field Lineage Explorer web app.
REM The explorer is a zero-dependency (stdlib-only) web server + faithful web UI.
REM The legacy Streamlit app is still available at src\sas_lineage\ui\app.py.

echo Field Lineage ^& Golden Source Explorer
echo ========================================
echo.

REM Check if Python is available
python --version >nul 2>&1
if errorlevel 1 (
    echo Error: Python is not installed. Please install Python 3.8 or higher.
    exit /b 1
)

echo Python found
echo.

REM The explorer needs only the standard library; it does NOT need streamlit.
echo Launching web explorer...
echo Open http://127.0.0.1:8010 in your browser
echo.
echo Press Ctrl+C to stop
echo.

set PYTHONPATH=%CD%\src
python -m sas_lineage.ui.server %*
