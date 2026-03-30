@echo off
chcp 65001 >nul
setlocal

cd /d %~dp0

echo [1/3] 安装或升级 PyInstaller...
python -m pip install --upgrade pyinstaller
if errorlevel 1 (
  echo 安装 PyInstaller 失败，请检查 Python 与网络。
  pause
  exit /b 1
)

echo [2/3] 安装或升级 Pillow...
python -m pip install --upgrade pillow
if errorlevel 1 (
  echo 安装 Pillow 失败，请检查 Python 与网络。
  pause
  exit /b 1
)

echo [3/3] 开始打包 EXE...
python -m PyInstaller --noconfirm --onefile --windowed --name PhotoPicker photo_sync_gui.py
if errorlevel 1 (
  echo 打包失败。
  pause
  exit /b 1
)

echo.
echo 打包完成！EXE 路径：dist\PhotoPicker2.exe
pause
