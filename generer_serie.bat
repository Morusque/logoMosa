@echo off
chcp 65001 >nul
set PYTHONUTF8=1
set PYTHONIOENCODING=UTF-8
cd /d "%~dp0"

REM ===================================================================
REM  Genere une SERIE de logos, dans un ordre aleatoire et sans remise.
REM
REM     generer_serie.bat          toutes les tuiles convenables (~583)
REM     generer_serie.bat 20       seulement 20
REM
REM  Interruptible a tout moment : Ctrl-C, ou eteindre la machine.
REM  Relancer la meme commande reprend ou on en etait.
REM  Les clips sortent dans out_mosaic\logos\.
REM ===================================================================

if not exist "data\banque.npy"                   python banque_vignettes.py
if not exist "out_mosaic\matches_exhaustif.json" python chercher_tuiles.py --apercu
if not exist "data\cache\manifeste.json"         python cache_tuiles.py

if "%~1"=="" (
  python generer_serie.py
) else (
  python generer_serie.py --combien %~1
)

echo.
pause
