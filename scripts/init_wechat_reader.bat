@echo off
setlocal
cd /d "%~dp0\.."
echo 正在初始化微信读取，请保持微信已登录…
set BIN=
if exist "vendor\wechat-cli.exe" set BIN=vendor\wechat-cli.exe
if "%BIN%"=="" if exist ".venv\Scripts\wechat-cli.exe" set BIN=.venv\Scripts\wechat-cli.exe
if "%BIN%"=="" (
  echo 微信读取组件未就绪，请重新安装本系统。
  exit /b 1
)
"%BIN%" init
if errorlevel 1 (
  echo 尚未完成微信读取初始化，或当前微信版本不兼容。
  exit /b 1
)
echo 微信读取初始化完成。请打开系统，在「微信同步」页查看状态。
endlocal
