@echo off
rem gushi daily pipeline (since 2026-09-24): collector -> bsk fallback -> guard(dedupe+health)
rem NOTE: resonance exists only for the LATEST trading day -> must be captured the same day.
cd /d "%~dp0.."
set PY=C:\Users\Admin\.workbuddy\binaries\python\envs\default\Scripts\python.exe
set PYTHONIOENCODING=utf-8
set LOG=backtest\gushi_data\collect_last.log
if not exist backtest\gushi_data mkdir backtest\gushi_data
if exist "%LOG%" for %%A in ("%LOG%") do if %%~zA GTR 2000000 move /y "%LOG%" "%LOG%.1" >nul
echo ===== %DATE% %TIME% start ===== >> "%LOG%"
echo ---- collect (CDP 9223/9222) ---- >> "%LOG%"
"%PY%" -X utf8 backtest\gushi_daily_collect.py --days 3 %* >> "%LOG%" 2>&1
echo ---- bsk fallback ---- >> "%LOG%"
"%PY%" -X utf8 backtest\gushi_bsk_capture.py --only-if-missing >> "%LOG%" 2>&1
echo ---- guard (dedupe + health) ---- >> "%LOG%"
"%PY%" -X utf8 backtest\gushi_data_guard.py --days 5 --dedupe >> "%LOG%" 2>&1
echo ---- verify + one retry ---- >> "%LOG%"
"%PY%" -X utf8 backtest\gushi_data_guard.py --days 1 >> "%LOG%" 2>&1
if errorlevel 3 (
  echo [retry] today missing - wait 3min then retry >> "%LOG%"
  ping -n 180 127.0.0.1 >nul
  "%PY%" -X utf8 backtest\gushi_daily_collect.py --days 1 >> "%LOG%" 2>&1
  "%PY%" -X utf8 backtest\gushi_bsk_capture.py --only-if-missing >> "%LOG%" 2>&1
  "%PY%" -X utf8 backtest\gushi_data_guard.py --days 5 --dedupe >> "%LOG%" 2>&1
)
echo ===== %TIME% end ===== >> "%LOG%"
exit /b 0