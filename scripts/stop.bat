@echo off
setlocal
set FOUND=
for /f "tokens=5" %%P in ('netstat -ano ^| findstr ":8090" ^| findstr "LISTENING"') do (
  taskkill /F /PID %%P >nul 2>&1
  set FOUND=1
)
if defined FOUND (
  echo 已停止 Judy（端口 8090）
) else (
  echo Judy 未在运行
)
endlocal
