@echo off
chcp 65001 >nul
set PYTHONUTF8=1
set PYTHONIOENCODING=UTF-8
cd /d "%~dp0"

REM ===================================================================
REM  Genere un logo anime. Sans argument : une tuile au hasard.
REM
REM     generer_logo.bat              une tuile au hasard
REM     generer_logo.bat 364          la tuile 364
REM     generer_logo.bat 364 5        la 364, puis 4 autres au hasard
REM
REM  Les numeros de tuile se relevent avec le sketch Processing
REM  pointTile01, ou dans out_mosaic\matches_exhaustif.json.
REM  Tous les chemins viennent de config.txt.
REM ===================================================================

REM --- les deux passes qui ne coutent qu'une fois
if not exist "data\banque.npy"           python banque_vignettes.py
if not exist "out_mosaic\matches_exhaustif.json" python chercher_tuiles.py --apercu
if not exist "data\cache\manifeste.json" python cache_tuiles.py

set TUILE=%~1
set COMBIEN=%~2
if "%COMBIEN%"=="" set COMBIEN=1

if "%TUILE%"=="" (
  echo.
  echo === %COMBIEN% logo(s), tuile(s) au hasard ===
  for /L %%N in (1,1,%COMBIEN%) do python rendre_logo.py --hasard --son
) else (
  echo.
  echo === logo sur la tuile %TUILE% ===
  python rendre_logo.py --focus %TUILE% --son
  if not "%COMBIEN%"=="1" (
    for /L %%N in (2,1,%COMBIEN%) do python rendre_logo.py --hasard --son
  )
)

echo.
echo Termine. Les clips sont dans out_mosaic\.
pause
