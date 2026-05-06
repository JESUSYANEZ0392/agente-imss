@echo off
setlocal EnableDelayedExpansion
title Agente IMSS — Build System

echo.
echo ============================================================
echo   AGENTE IMSS — Sistema de Compilacion
echo   Genera: AgenteIMSS_Setup_v1.0.0.exe
echo ============================================================
echo.

REM ── Configuracion ─────────────────────────────────────────────────────────
set APP_VERSION=1.0.0
set PYTHON_URL=https://www.python.org/ftp/python/3.12.4/python-3.12.4-amd64.exe
set INNO_PATH=C:\Program Files (x86)\Inno Setup 6\ISCC.exe
set ROOT=%~dp0

REM ── Verificar entorno virtual ───────────────────────────────────────────────
if not exist "%ROOT%.venv\Scripts\activate.bat" (
    echo [ERROR] Entorno virtual no encontrado.
    echo Ejecuta primero: instalar.bat
    pause & exit /b 1
)

call "%ROOT%.venv\Scripts\activate.bat"

REM ── Verificar PyInstaller ────────────────────────────────────────────────────
python -c "import PyInstaller" 2>nul
if errorlevel 1 (
    echo [INFO] Instalando PyInstaller...
    pip install pyinstaller pillow pystray --quiet
)

REM ── Verificar pystray y pillow (para bandeja) ────────────────────────────────
python -c "import pystray, PIL" 2>nul
if errorlevel 1 (
    echo [INFO] Instalando pystray y Pillow...
    pip install pystray pillow --quiet
)

REM ── Crear carpetas de salida ─────────────────────────────────────────────────
if not exist "%ROOT%dist"    mkdir "%ROOT%dist"
if not exist "%ROOT%build"   mkdir "%ROOT%build"
if not exist "%ROOT%dist\installer" mkdir "%ROOT%dist\installer"

REM ── Crear icono placeholder si no existe ────────────────────────────────────
if not exist "%ROOT%assets\icon.ico" (
    echo [INFO] Generando icono placeholder...
    python -c "
from PIL import Image, ImageDraw
img = Image.new('RGBA', (256, 256), (26, 26, 46, 255))
draw = ImageDraw.Draw(img)
draw.ellipse([20, 20, 236, 236], fill=(76, 110, 245, 255))
draw.text((75, 85), 'IM', fill='white')
img.save('assets/icon.ico', format='ICO', sizes=[(256,256),(128,128),(64,64),(32,32),(16,16)])
print('Icono creado.')
"
)

REM ── PASO 1: Compilar launcher con PyInstaller ────────────────────────────────
echo.
echo [PASO 1/4] Compilando launcher con PyInstaller...
echo.

pyinstaller --clean "%ROOT%agente_imss.spec" --distpath "%ROOT%dist" --workpath "%ROOT%build\pyinstaller"

if errorlevel 1 (
    echo [ERROR] Fallo la compilacion con PyInstaller.
    pause & exit /b 1
)
echo [OK] Launcher compilado: dist\AgenteIMSS\AgenteIMSS.exe

REM ── PASO 2: Descargar Python 3.12 installer ──────────────────────────────────
echo.
echo [PASO 2/4] Descargando Python 3.12...
echo.

if not exist "%ROOT%build\python-3.12.4-amd64.exe" (
    echo Descargando desde python.org...
    powershell -Command "& { Invoke-WebRequest -Uri '%PYTHON_URL%' -OutFile '%ROOT%build\python-3.12.4-amd64.exe' -UseBasicParsing }"
    if errorlevel 1 (
        echo [ERROR] No se pudo descargar Python.
        echo Descarga manualmente desde: %PYTHON_URL%
        echo Guarda en: %ROOT%build\python-3.12.4-amd64.exe
        pause & exit /b 1
    )
) else (
    echo [OK] Python ya descargado, usando cache.
)

REM ── PASO 3: Compilar instalador con Inno Setup ──────────────────────────────
echo.
echo [PASO 3/4] Compilando instalador con Inno Setup...
echo.

if not exist "%INNO_PATH%" (
    echo [AVISO] Inno Setup no encontrado en: %INNO_PATH%
    echo Descarga desde: https://jrsoftware.org/isinfo.php
    echo Instala y luego vuelve a ejecutar este script.
    echo.
    echo Alternativa: el .exe del launcher ya esta en dist\AgenteIMSS\
    pause
    goto :fin_build
)

"%INNO_PATH%" "%ROOT%installer\setup.iss"

if errorlevel 1 (
    echo [ERROR] Fallo la compilacion del instalador.
    pause & exit /b 1
)

echo [OK] Instalador generado.

:fin_build

REM ── PASO 4: Resumen ─────────────────────────────────────────────────────────
echo.
echo ============================================================
echo   BUILD COMPLETADO
echo ============================================================
echo.

if exist "%ROOT%dist\installer\AgenteIMSS_Setup_v%APP_VERSION%.exe" (
    echo   Instalador:  dist\installer\AgenteIMSS_Setup_v%APP_VERSION%.exe
    for %%A in ("%ROOT%dist\installer\AgenteIMSS_Setup_v%APP_VERSION%.exe") do (
        set /a SIZE=%%~zA / 1048576
        echo   Tamano:      !SIZE! MB aprox.
    )
) else (
    echo   Launcher:    dist\AgenteIMSS\AgenteIMSS.exe  (sin instalador)
)

echo.
echo   Para distribuir, comparte el archivo Setup .exe con tus clientes.
echo ============================================================
echo.
pause
