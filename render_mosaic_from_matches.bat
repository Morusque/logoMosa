@echo off

python "D:\project\current\logoMosa\render_mosaic_from_matches.py" ^
  --matches "D:\project\current\logoMosa\out_mosaic\matches_pass.json" ^
  --fps 20 ^
  --pre_roll 20 ^
  --post_roll 2 ^
  --focus_tile 283 ^
  --zoom_gamma 0.5 ^
  --width 1920 ^
  --height 1080 ^
  --frames_dir "D:\project\current\logoMosa\out_mosaic\frames_mosaic" ^
  --video_out "D:\project\current\logoMosa\out_mosaic\mosaic_from_matches.mp4"

pause
