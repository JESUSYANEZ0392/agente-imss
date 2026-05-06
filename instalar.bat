@echo off
echo ================================================
echo  Instalacion del Agente IMSS
echo ================================================
echo.

REM Crear entorno virtual
python -m venv .venv
call .venv\Scripts\activate.bat

REM Instalar dependencias
pip install --upgrade pip
pip install -r requirements.txt

REM Instalar browsers de Playwright
playwright install chromium

REM Copiar .env de ejemplo si no existe
if not exist .env (
    copy .env.example .env
    echo AVISO: Se creo el archivo .env. Por favor configura tus credenciales.
)

REM Inicializar base de datos
python main.py init-db

echo.
echo ================================================
echo  Instalacion completada.
echo  Para iniciar el dashboard ejecuta:
echo    .venv\Scripts\activate
echo    python main.py dashboard
echo ================================================
pause
