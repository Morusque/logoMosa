@echo off
chcp 65001 >nul
set PYTHONUTF8=1
set PYTHONIOENCODING=UTF-8

REM Tous les chemins (corpus, cible, sortie, grille) viennent de config.txt.
REM Rien a editer ici quand le disque change de lettre.
cd /d "%~dp0"

python mosaic_from_videos.py ^
  --tile_sample 16 ^
  --infinite ^
  --save_interval 50 ^
  --max_per_video 2 ^
  --margin_start 2 ^
  --margin_end 5 ^
  --verbose ^
  --resume "..\out_mosaic\matches_pass.json"

echo.
echo Termine. Sortie dans ..\out_mosaic\.
pause
