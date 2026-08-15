@echo off
REM v8 月度看板更新（Windows 计划任务建议：每月 1 号 18:00）
REM 注册：schtasks /create /tn "v8_dashboard_update" /tr "C:\Users\XAUTHUB\WorkBuddy\投资\量化权重系统\v8_update.bat" /sc monthly /d 1 /st 18:00
cd /d C:\Users\XAUTHUB\WorkBuddy\投资\量化权重系统
C:\Users\XAUTHUB\.workbuddy\binaries\python\envs\default\Scripts\python.exe v8_daily_update.py >> v8_update.log 2>&1
