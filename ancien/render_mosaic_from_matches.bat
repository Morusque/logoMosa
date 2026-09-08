@echo off
chcp 65001 >nul
set PYTHONUTF8=1
set PYTHONIOENCODING=UTF-8

REM Rend une sequence d'images PNG par tuile de focus.
REM Les chemins et la geometrie viennent de config.txt ; il ne reste ici que
REM la liste des tuiles a rendre. Chaque tuile ecrit dans son propre dossier
REM ..\out_mosaic\frames_tileNNNN\ et son propre apercu out_mosaic\mosaic_tileNNNN.jpg,
REM donc deux rendus ne s'ecrasent plus l'un l'autre.
REM
REM ATTENTION : ce script ne code AUCUNE video, il n'ecrit que des PNG.
REM L'assemblage se fait ensuite (DaVinci, ou le futur script de montage).
REM
REM Les numeros de tuile se relevent avec le sketch Processing pointTile01.
cd /d "%~dp0"

for %%T in (364 337 203 198 609 504 549 145 147) do (
  echo.
  echo === tuile %%T ===
  python render_mosaic_from_matches.py ^
    --focus_tile %%T ^
    --pre_roll 100 ^
    --post_roll 2 ^
    --zoom_gamma 3.0
)

echo.
echo Termine. Images dans ..\out_mosaic\frames_tileNNNN\.
pause
