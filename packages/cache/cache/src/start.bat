@echo off
setlocal

    set MODULES_PATH=%~dp0..\..\..\modules

    @REM echo !!!
    @REM echo **********************************************************
    @REM echo * CHECK THE ENVIRONMENT VARIABLES IN THE START-UP SCRIPT *
    @REM echo **********************************************************
    @REM echo !!!

    set ASSETDB_PATH=C:\Users\arozantsev\Documents\projects\Digital_World\omni_asset\assetDB_test
    set PLUGINS_PATH=%~dp0..\..\..\plugins
    @REM set MONITOR_CACHE_N_WORKERS=2
    @REM set MONITOR_CACHE_SCHEMA=ws

    @REM echo Installing "deeptag" packages
    @REM pip install -e %MODULES_PATH%\..\ngsearch\modules\deeptag_utils
    @REM if errorlevel 1 goto ERROR

    "python" "%~dp0monitor_cache.py" %*

    exit /B 0

    :ERROR
    echo Failure running!!!
    exit /B 1

endlocal
