@echo off
setlocal EnableDelayedExpansion

:: ============================================================
::  Portfolio Analyzer Agent — Launcher
::  Double-click this file to start the agent.
:: ============================================================

title Portfolio Analyzer Agent

:: Move to the folder where this .bat lives
cd /d "%~dp0"

cls
echo.
echo  ============================================================
echo   PORTFOLIO ANALYZER AGENT
echo   Scrapes developer portfolios from GitHub and generates
echo   per-alphabet summary docs in: portfolio_docs\
echo  ============================================================
echo.

:: ── Check Python is available ────────────────────────────────
python --version >nul 2>&1
if errorlevel 1 (
    echo  [ERROR] Python not found. Please install Python 3.10+
    echo          https://www.python.org/downloads/
    echo.
    pause
    exit /b 1
)

:: ── Show menu ────────────────────────────────────────────────
echo  Choose a run mode:
echo.
echo    1. Run ALL portfolios (~2000 entries)  [full run, hours]
echo    2. Run specific letters only           [e.g. A B C]
echo    3. Quick test — first 20 entries only  [~2 minutes]
echo    4. Fresh start  (clear previous run)
echo    5. Resume previous run                 [default]
echo    6. Open output folder
echo    7. Exit
echo.
set /p CHOICE="  Enter choice [1-7]: "

if "%CHOICE%"=="1" goto RUN_ALL
if "%CHOICE%"=="2" goto RUN_LETTERS
if "%CHOICE%"=="3" goto RUN_TEST
if "%CHOICE%"=="4" goto RUN_FRESH
if "%CHOICE%"=="5" goto RUN_RESUME
if "%CHOICE%"=="6" goto OPEN_DOCS
if "%CHOICE%"=="7" goto END

echo  [ERROR] Invalid choice. Please enter 1-7.
pause
goto END

:: ── Option 1: Full run ────────────────────────────────────────
:RUN_ALL
echo.
echo  Starting full run of all portfolios...
echo  (Press Ctrl+C at any time to stop — progress is saved)
echo.
python agent.py
goto DONE

:: ── Option 2: Specific letters ───────────────────────────────
:RUN_LETTERS
echo.
set /p LETTERS="  Enter letters separated by spaces (e.g. A B C): "
echo.
echo  Processing letters: %LETTERS%
echo.
python agent.py --letters %LETTERS%
goto DONE

:: ── Option 3: Quick test ─────────────────────────────────────
:RUN_TEST
echo.
echo  Running quick test — first 20 entries...
echo.
python agent.py --letters A --limit 20
goto DONE

:: ── Option 4: Fresh start ─────────────────────────────────────
:RUN_FRESH
echo.
echo  WARNING: This will delete all previous results and progress.
set /p CONFIRM="  Are you sure? (yes/no): "
if /i not "%CONFIRM%"=="yes" (
    echo  Cancelled.
    pause
    goto END
)
echo.
echo  Starting fresh run...
echo.
python agent.py --no-resume
goto DONE

:: ── Option 5: Resume ─────────────────────────────────────────
:RUN_RESUME
echo.
echo  Resuming from previous run...
echo.
python agent.py
goto DONE

:: ── Option 6: Open docs folder ───────────────────────────────
:OPEN_DOCS
if exist "portfolio_docs\" (
    explorer "portfolio_docs"
) else (
    echo.
    echo  [INFO] No docs folder yet. Run the agent first to generate docs.
)
pause
goto END

:: ── Done ──────────────────────────────────────────────────────
:DONE
echo.
if errorlevel 1 (
    echo  [ERROR] Agent exited with an error. Check the output above.
) else (
    echo  ============================================================
    echo   Done! Docs saved to: %~dp0portfolio_docs\
    echo  ============================================================
    echo.
    set /p OPEN="  Open the docs folder now? (yes/no): "
    if /i "!OPEN!"=="yes" (
        if exist "portfolio_docs\" explorer "portfolio_docs"
    )
)

:END
echo.
pause
endlocal
