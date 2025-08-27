@echo off
echo ========================================
echo    Lapis Monetae Wallet Web
echo ========================================
echo.
echo Iniciando servidor local...
echo.
echo Puerto: 8080
echo URL: http://localhost:8080
echo.
echo Presiona Ctrl+C para detener el servidor
echo.

REM Intentar usar Python 3
python -m http.server 8080 2>nul
if %errorlevel% neq 0 (
    REM Si Python no está disponible, intentar con Node.js
    echo Python no encontrado, intentando con Node.js...
    npx http-server -p 8080 2>nul
    if %errorlevel% neq 0 (
        echo.
        echo Error: No se pudo iniciar el servidor
        echo.
        echo Soluciones:
        echo 1. Instala Python 3: https://python.org
        echo 2. O instala Node.js: https://nodejs.org
        echo 3. O abre index.html directamente en tu navegador
        echo.
        pause
    )
)
