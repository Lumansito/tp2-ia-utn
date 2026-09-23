@echo off
setlocal enabledelayedexpansion
cd /d "%~dp0"

echo ============================================
echo   DB Copilot - Inicio automatico (Windows)
echo ============================================
echo.

where python >nul 2>nul
if errorlevel 1 (
    echo [ERROR] No se encontro "python" en el PATH.
    echo Instala Python 3.10 o superior desde https://www.python.org/downloads/
    echo y volve a ejecutar este script.
    pause
    exit /b 1
)

if not exist ".venv" (
    echo Creando entorno virtual en .venv ...
    python -m venv .venv
    if errorlevel 1 (
        echo [ERROR] No se pudo crear el entorno virtual.
        pause
        exit /b 1
    )
)

call ".venv\Scripts\activate.bat"
if errorlevel 1 (
    echo [ERROR] No se pudo activar el entorno virtual.
    pause
    exit /b 1
)

echo.
echo Instalando/actualizando dependencias (puede tardar la primera vez)...
python -m pip install --upgrade pip >nul
pip install -r requirements.txt
if errorlevel 1 (
    echo.
    echo [ERROR] Fallo la instalacion de dependencias. Revisa el mensaje de arriba.
    pause
    exit /b 1
)

if not exist ".env" (
    echo.
    echo No existe .env: se crea una copia de .env.example
    copy /y ".env.example" ".env" >nul
    echo.
    echo *** IMPORTANTE ***
    echo Se creo el archivo .env a partir de .env.example.
    echo Complete DATABASE_URL y GOOGLE_API_KEY antes de continuar
    echo ^(ver README.md, seccion "Puesta en marcha"^).
    echo Se va a abrir el archivo en el Bloc de notas: guardelo y cierrelo para continuar.
    echo.
    pause
    notepad ".env"
)

findstr /C:"tu-api-key-de-gemini-aqui" ".env" >nul
if not errorlevel 1 (
    echo.
    echo [ERROR] GOOGLE_API_KEY todavia tiene el valor de ejemplo en .env.
    echo Edita el archivo .env con tu clave real de Google Gemini y volve a ejecutar este script.
    pause
    exit /b 1
)

echo.
echo ============================================
echo   Levantando la app en http://localhost:8501
echo   (para cerrarla, volve a esta ventana y apreta Ctrl+C)
echo ============================================
echo.
streamlit run db_copilot\app.py

echo.
echo La app se cerro.
pause
endlocal
