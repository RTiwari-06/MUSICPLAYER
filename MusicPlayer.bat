@echo off
setlocal enabledelayedexpansion
title MusicPlayer Launcher

cd /d "%~dp0"

set "PYTHON_CMD=python"
if exist ".venv\Scripts\python.exe" set "PYTHON_CMD=.venv\Scripts\python.exe"

if /i "%~1"=="build" goto :build
if /i "%~1"=="install" goto :install
if /i "%~1"=="clean" goto :clean

:run
echo [MusicPlayer] Starting application...
"%PYTHON_CMD%" main.py %2 %3 %4
if errorlevel 1 (
    echo.
    echo [MusicPlayer] Application exited with an error.
    pause
)
goto :eof

:install
echo [MusicPlayer] Installing dependencies...
"%PYTHON_CMD%" -m pip install --upgrade pip
"%PYTHON_CMD%" -m pip install -r requirements.txt
if errorlevel 1 (
    echo [MusicPlayer] Dependency installation failed.
    pause
    exit /b 1
)
echo [MusicPlayer] Dependencies installed.
goto :eof

:build
echo [MusicPlayer] Building Windows executable with PyInstaller...
if not exist "build" mkdir "build"
if not exist "dist" mkdir "dist"
"%PYTHON_CMD%" -m pip install --upgrade pyinstaller
"%PYTHON_CMD%" -m PyInstaller --noconfirm --clean --windowed ^
    --name MusicPlayer ^
    --icon "app\assets\icon.ico" ^
    --add-data "app\assets\icon.png;assets" ^
    --add-data "app\assets\icon.ico;assets" ^
    --collect-all spotdl ^
    --collect-all yt_dlp ^
    --collect-all pykakasi ^
    --hidden-import app.core.fetch_tracks_child ^
    --hidden-import customtkinter ^
    main.py
if errorlevel 1 (
    echo.
    echo [MusicPlayer] Build failed.
    pause
    exit /b 1
)
echo [MusicPlayer] Build finished: dist\MusicPlayer\MusicPlayer.exe
goto :eof

:clean
echo [MusicPlayer] Removing build artifacts...
if exist "build" rmdir /s /q "build"
if exist "dist" rmdir /s /q "dist"
echo [MusicPlayer] Clean done.
goto :eof
