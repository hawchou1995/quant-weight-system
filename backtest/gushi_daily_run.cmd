@echo off
rem ============================================================================
rem gushi daily pipeline (since 2026-09-24)
rem   preflight-login -> collector(--renew) -> bsk fallback -> guard(dedupe+health)
rem NOTE: resonance exists only for the LATEST trading day -> must be captured
rem       the same day, otherwise it is lost permanently.
rem
rem 2026-10-09 hardening (R-gushi-pipeline-1009). Three breaks that caused
rem 09-28 ~ 10-08 to silently collect nothing:
rem   (1) Run _gushi_login_v4.py FIRST: if the session is guest, it does the
rem       LINUX DO OAuth login automatically. There was no such step before,
rem       so a lost login just made the pipeline spin empty for 10 days.
rem       (v4 replaces v3: v3's "modal open?" test only looked for a password
rem        box, but the site defaults to the LD tab -> v3 always bailed out.)
rem   (2) Pass --renew to the collector: when non-VIP (masked data) it redeems
rem       a 1-day VIP for 30 forum points (guardrails inside the collector).
rem       Previously never passed, so once VIP expired collection was dead.
rem   (3) Do not end with an unconditional "exit /b 0". A still-missing today
rem       must surface as exit 3, otherwise Task Scheduler logs "success"
rem       every day while data is missing.
rem
rem NOTE: keep this file ASCII-only. cmd.exe reads .cmd in the OEM codepage
rem       (cp936 here), so UTF-8 Chinese in comments corrupts parsing.
rem       Chinese details -> backtest/gushi_data/README-gushi-pipeline.md
rem ============================================================================
cd /d "%~dp0.."
set PY=C:\Users\Admin\.workbuddy\binaries\python\envs\default\Scripts\python.exe
set PYTHONIOENCODING=utf-8
set LOG=backtest\gushi_data\collect_last.log
if not exist backtest\gushi_data mkdir backtest\gushi_data
if exist "%LOG%" for %%A in ("%LOG%") do if %%~zA GTR 2000000 move /y "%LOG%" "%LOG%.1" >nul
echo ===== %DATE% %TIME% start ===== >> "%LOG%"

echo ---- preflight login i.gushi.in ---- >> "%LOG%"
"%PY%" -X utf8 backtest\_gushi_login_v4.py >> "%LOG%" 2>&1
set LOGIN_RC=%ERRORLEVEL%
echo [preflight] login rc=%LOGIN_RC%  [0=vip / 2=logged-in-not-vip / 3=still-guest] >> "%LOG%"

echo ---- collect CDP 9223/9222, --renew ---- >> "%LOG%"
"%PY%" -X utf8 backtest\gushi_daily_collect.py --days 3 --renew %* >> "%LOG%" 2>&1
set COLLECT_RC=%ERRORLEVEL%

echo ---- bsk fallback ---- >> "%LOG%"
"%PY%" -X utf8 backtest\gushi_bsk_capture.py --only-if-missing >> "%LOG%" 2>&1

echo ---- guard dedupe + health ---- >> "%LOG%"
"%PY%" -X utf8 backtest\gushi_data_guard.py --days 5 --dedupe >> "%LOG%" 2>&1

echo ---- verify + one retry ---- >> "%LOG%"
"%PY%" -X utf8 backtest\gushi_data_guard.py --days 1 >> "%LOG%" 2>&1
if errorlevel 3 (
  echo [retry] today missing - wait 3min then retry >> "%LOG%"
  ping -n 180 127.0.0.1 >nul
  "%PY%" -X utf8 backtest\_gushi_login_v4.py >> "%LOG%" 2>&1
  "%PY%" -X utf8 backtest\gushi_daily_collect.py --days 1 --renew >> "%LOG%" 2>&1
  "%PY%" -X utf8 backtest\gushi_bsk_capture.py --only-if-missing >> "%LOG%" 2>&1
  "%PY%" -X utf8 backtest\gushi_data_guard.py --days 5 --dedupe >> "%LOG%" 2>&1
  "%PY%" -X utf8 backtest\gushi_data_guard.py --days 1 >> "%LOG%" 2>&1
)
rem Read the exit code outside the block: inside a block the ERRORLEVEL
rem would be expanded at parse time (no delayed expansion here) -> wrong code.
set VERIFY_RC=%ERRORLEVEL%
echo ===== %TIME% end : login_rc=%LOGIN_RC% collect_rc=%COLLECT_RC% verify_rc=%VERIFY_RC% ===== >> "%LOG%"

rem Publish-window awareness: the site does not post same-day data before
rem ~16:22 (the collector refuses to grab "today" before 16:20 via its own
rem --allow-early guard). So a missing "today" before ~17:00 is EXPECTED and
rem must not turn the task red; after that it is a real failure.
set /a HOUR=%TIME:~0,2%
set LATE=0
if %HOUR% GEQ 17 set LATE=1
rem NOTE: use flat "if A if B set X" instead of nested parens with exit /b.
rem Measured on this box: "exit /b N" inside nested parens did NOT propagate
rem the code (printed the FAIL branch yet returned 0). The flat form does.
set FINAL_RC=0
if %VERIFY_RC% GEQ 3 if %LATE%==1 set FINAL_RC=3
if %FINAL_RC%==3 echo [FAIL] today still missing verify_rc=%VERIFY_RC% hour=%HOUR% - after publish window >> "%LOG%"
if %FINAL_RC%==0 if %VERIFY_RC% GEQ 3 echo [note] verify_rc=%VERIFY_RC% hour=%HOUR% is before the publish window ~16:22 - not failing >> "%LOG%"
exit /b %FINAL_RC%
