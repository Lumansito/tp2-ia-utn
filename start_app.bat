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
    echo Se creo el archivo .env a partir de .env.example. Completa:
    echo   - DATABASE_URL  ^(o dejala apuntando al Postgres del docker-compose^)
    echo   - LLM_PROVIDER  ^(OPENAI o GEMINI^)
    echo   - LLM_API_KEY   ^(tu clave real del proveedor elegido^)
    echo   - LLM_MODEL y EMBEDDING_MODEL
    echo Se va a abrir el archivo en el Bloc de notas: guardalo y cerralo para continuar.
    echo.
    pause
    notepad ".env"
)

findstr /C:"tu_clave_de_api_aqui" ".env" >nul
if not errorlevel 1 (
    echo.
    echo [ERROR] LLM_API_KEY todavia tiene el valor de ejemplo en .env.
    echo Edita el archivo .env con tu clave real ^(OpenAI o Gemini, segun LLM_PROVIDER^)
    echo y volve a ejecutar este script.
    pause
    exit /b 1
)

findstr /R /C:"^LLM_API_KEY=$" ".env" >nul
if not errorlevel 1 (
    echo.
    echo [ERROR] LLM_API_KEY esta vacia en .env.
    echo Completa tu clave real y volve a ejecutar este script.
    pause
    exit /b 1
)

where docker >nul 2>nul
if not errorlevel 1 (
    echo.
    echo Levantando la base de datos con Docker ^(docker-compose.yml^)...
    docker compose up -d
    if errorlevel 1 (
        echo [AVISO] No se pudo levantar el contenedor de Postgres con Docker.
        echo Si tu DATABASE_URL apunta a otra base ^(no la del docker-compose^), podes ignorar esto.
    )
) else (
    echo.
    echo [AVISO] No se encontro Docker. Si tu DATABASE_URL.env apunta al Postgres
    echo de docker-compose.yml, instala Docker Desktop o levanta esa base a mano.
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
