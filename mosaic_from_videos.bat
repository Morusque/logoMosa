@echo off
chcp 65001 >nul
set PYTHONUTF8=1
set PYTHONIOENCODING=UTF-8

python "mosaic_from_videos.py" ^
  --videos "G:\Kino\mtp" ^
  --target "D:\project\current\logoMosa\logo.png" ^
  --out_dir "D:\project\current\logoMosa\out_mosaic" ^
  --grid 27 27 ^
  --tile_sample 16 ^
  --infinite ^
  --save_interval 50 ^
  --max_per_video 2 ^
  --margin_start 2 ^
  --margin_end 5 ^
  --verbose ^
  --resume "D:\project\current\logoMosa\out_mosaic\matches_pass.json"

echo Finished. Output in "%OUT_DIR%".
pause
