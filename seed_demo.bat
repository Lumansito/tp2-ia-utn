@echo off
setlocal
cd /d "%~dp0"

if not exist ".venv" (
    echo No se encontro el entorno virtual .venv.
    echo Ejecuta primero start_app.bat para instalar todo, despues corre este script.
    pause
    exit /b 1
)

call ".venv\Scripts\activate.bat"

echo ============================================
echo   DB Copilot - Sembrado de la base de demo
echo ============================================
echo.
echo Esto crea (o recrea) el modelo de 15 tablas de e-commerce con datos de
echo prueba generados con Faker, en la base que apunte DATABASE_URL del .env
echo (o la que le pases con --url). Te va a pedir confirmacion antes de tocar
echo el esquema.
echo.

python scripts\seed_demo.py %*

pause
endlocal
