#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import argparse, json, os, subprocess, tempfile
from typing import Optional, List, Tuple, Dict
import numpy as np
import cv2
from PIL import Image

# Silence OpenCV spam
try:
    cv2.utils.logging.setLogLevel(cv2.utils.logging.LOG_LEVEL_SILENT)
except Exception:
    try:
        cv2.setLogLevel(cv2.LOG_LEVEL_SILENT)
    except Exception:
        pass

# ---------- utils ----------
def normp(p: str) -> str:
    return os.path.normpath(str(p).strip().strip('"')) if p else p

def ensure_dir(p: str) -> None:
    if p:
        os.makedirs(p, exist_ok=True)

def box_visible_on_canvas(box, W, H):
    x0, y0, x1, y1 = box
    dx0, dy0 = max(0, x0), max(0, y0)
    dx1, dy1 = min(W, x1), min(H, y1)
    return (dx1 > dx0) and (dy1 > dy0)

def video_meta(path: str) -> Tuple[float, int, float]:
    cap = cv2.VideoCapture(path)
    if not cap.isOpened():
        return (25.0, 0, 0.0)
    fps = cap.get(cv2.CAP_PROP_FPS) or 25.0
    n   = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
    dur = (n / fps) if fps > 0 else 0.0
    cap.release()
    return (float(fps), int(n), float(dur))

def read_frame_cv2_by_idx(path: str, idx: int) -> Optional[np.ndarray]:
    cap = cv2.VideoCapture(path)
    if not cap.isOpened():
        return None
    cap.set(cv2.CAP_PROP_POS_FRAMES, max(0, int(idx)))
    ok, fr = cap.read()
    cap.release()
    if not ok or fr is None:
        return None
    return cv2.cvtColor(fr, cv2.COLOR_BGR2RGB)

def read_frame_cv2_by_time(path: str, t_sec: float, fps_hint: float = 25.0) -> Optional[np.ndarray]:
    cap = cv2.VideoCapture(path)
    if not cap.isOpened():
        return None
    cap.set(cv2.CAP_PROP_POS_MSEC, max(0.0, float(t_sec)) * 1000.0)
    ok, fr = cap.read()
    if not ok or fr is None:
        if fps_hint and fps_hint > 0:
            cap.set(cv2.CAP_PROP_POS_FRAMES, int(max(0.0, t_sec) * fps_hint))
            ok, fr = cap.read()
    cap.release()
    if not ok or fr is None:
        return None
    return cv2.cvtColor(fr, cv2.COLOR_BGR2RGB)

def read_frame_ffmpeg(path: str, t_sec: float) -> Optional[np.ndarray]:
    with tempfile.TemporaryDirectory() as td:
        out_png = os.path.join(td, "still.png")
        cmd = [
            "ffmpeg", "-loglevel", "error", "-y",
            "-ss", f"{max(0.0, float(t_sec)):.6f}",
            "-i", path,
            "-frames:v", "1",
            out_png
        ]
        try:
            subprocess.run(cmd, check=True)
        except Exception:
            return None
        if not os.path.isfile(out_png):
            return None
        img = Image.open(out_png).convert("RGB")
        return np.array(img, dtype=np.uint8)

def read_frame_robust(path: str, t_sec: Optional[float], idx: Optional[int], fps_hint: float) -> Optional[np.ndarray]:
    # exact index
    if isinstance(idx, int):
        fr = read_frame_cv2_by_idx(path, idx)
        if fr is not None:
            return fr
    # exact time
    if t_sec is not None:
        fr = read_frame_cv2_by_time(path, t_sec, fps_hint=fps_hint)
        if fr is not None:
            return fr
    # neighbors around idx
    if isinstance(idx, int):
        for d in (1, -1, 2, -2, 3, -3, 4, -4):
            fr = read_frame_cv2_by_idx(path, max(0, idx + d))
            if fr is not None:
                return fr
    # ffmpeg fallback at time
    if t_sec is not None:
        fr = read_frame_ffmpeg(path, t_sec)
        if fr is not None:
            return fr
    return None

def crop_resize_fill(img: np.ndarray, tw: int, th: int, variant: str = "center") -> np.ndarray:
    sh, sw = img.shape[:2]
    tgt_aspect = max(1, tw) / float(max(1, th))
    src_aspect = sw / float(sh) if sh else 1.0

    if src_aspect > tgt_aspect:
        new_w = int(round(sh * tgt_aspect))
        new_w = max(1, min(sw, new_w))
        if   variant == "x0": x0 = 0
        elif variant == "x2": x0 = sw - new_w
        else:                 x0 = (sw - new_w) // 2
        x0 = max(0, min(sw - new_w, x0))
        img = img[:, x0:x0 + new_w]
    else:
        new_h = int(round(sw / tgt_aspect)) if tgt_aspect > 0 else sh
        new_h = max(1, min(sh, new_h))
        if   variant == "y0": y0 = 0
        elif variant == "y2": y0 = sh - new_h
        else:                 y0 = (sh - new_h) // 2
        y0 = max(0, min(sh - new_h, y0))
        img = img[y0:y0 + new_h, :]

    tw = max(1, tw); th = max(1, th)
    return cv2.resize(img, (tw, th), interpolation=cv2.INTER_AREA)

def paste_tile(canvas: np.ndarray, patch: np.ndarray, box: List[int]) -> None:
    x0, y0, x1, y1 = [int(v) for v in box]
    H, W = canvas.shape[:2]
    dx0, dy0 = max(0, x0), max(0, y0)
    dx1, dy1 = min(W, x1), min(H, y1)
    if dx1 <= dx0 or dy1 <= dy0:
        return
    sx0 = max(0, dx0 - x0)
    sy0 = max(0, dy0 - y0)
    sx1 = sx0 + (dx1 - dx0)
    sy1 = sy0 + (dy1 - dy0)
    ph, pw = patch.shape[:2]
    sx0 = max(0, min(pw, sx0)); sx1 = max(0, min(pw, sx1))
    sy0 = max(0, min(ph, sy0)); sy1 = max(0, min(ph, sy1))
    if sx1 <= sx0 or sy1 <= sy0:
        return
    canvas[dy0:dy1, dx0:dx1] = patch[sy0:sy1, sx0:sx1]

# ---- zoom ----
def compute_focus_params(entries, focus_tile, W, H):
    # centre de la tile focus + échelle s0 pour que cette tile remplisse l’écran à fi=0
    focus_tile = max(0, min(len(entries)-1, int(focus_tile)))
    x0,y0,x1,y1 = [int(v) for v in entries[focus_tile]["box"]]
    fx = 0.5*(x0+x1)
    fy = 0.5*(y0+y1)
    tw = max(1, x1-x0)
    th = max(1, y1-y0)
    s0 = max(W/float(tw), H/float(th))
    return fx, fy, float(s0)

def compute_transform_origin(entries, focus_tile, W, H, s0):
    # calcule P tel que: screen = (mosaic - P)*s + P soit identité quand s=1
    # et centre la tile focus au milieu quand s = s0
    focus_tile = max(0, min(len(entries)-1, int(focus_tile)))
    x0,y0,x1,y1 = [int(v) for v in entries[focus_tile]["box"]]
    fx = 0.5*(x0+x1); fy = 0.5*(y0+y1)
    Cx = W*0.5; Cy = H*0.5
    if abs(s0 - 1.0) < 1e-9:
        return 0.0, 0.0
    Px = (Cx - fx*s0) / (1.0 - s0)
    Py = (Cy - fy*s0) / (1.0 - s0)
    return float(Px), float(Py)

def apply_zoom_to_box_identity_at_1(box, Px, Py, s):
    x0,y0,x1,y1 = [float(v) for v in box]
    x0p = (x0 - Px)*s + Px
    y0p = (y0 - Py)*s + Py
    x1p = (x1 - Px)*s + Px
    y1p = (y1 - Py)*s + Py
    xa, xb = sorted((x0p, x1p))
    ya, yb = sorted((y0p, y1p))
    return [int(round(xa)), int(round(ya)), int(round(xb)), int(round(yb))]
    
def zoom_factor(fi, focus_idx, s0, gamma):
    if fi >= focus_idx:
        return 1.0
    if focus_idx <= 0:
        return 1.0
    prog  = fi / float(focus_idx)
    eased = pow(prog, max(1e-6, float(gamma)))
    return 1.0 + (s0 - 1.0) * (1.0 - eased)

import math

def zoom_factor_S(fi, focus_idx, s0, steepness=2.0):
    """
    S-shaped easing from s0 at frame 0 to 1.0 at focus_idx.
    steepness >= 1.0 (1.0 = linear; higher = steeper S in the middle).
    """
    if fi >= focus_idx or focus_idx <= 0:
        return 1.0

    # progress in [0,1]
    t = fi / float(focus_idx)
    t = max(0.0, min(1.0, t))

    a = max(1.0, float(steepness))  # ensure S-shape
    if t == 0.0:
        eased = 0.0
    elif t == 1.0:
        eased = 1.0
    else:
        ta = t ** a
        ua = (1.0 - t) ** a
        eased = ta / (ta + ua)  # symmetric S, exact endpoints

    return 1.0 + (s0 - 1.0) * (1.0 - eased)

def apply_zoom_to_box(box: List[int], fx: float, fy: float, s: float, W: int, H: int) -> List[int]:
    x0,y0,x1,y1 = [float(v) for v in box]
    x0p = (x0 - fx) * s + (W * 0.5)
    y0p = (y0 - fy) * s + (H * 0.5)
    x1p = (x1 - fx) * s + (W * 0.5)
    y1p = (y1 - fy) * s + (H * 0.5)
    xa, xb = sorted((x0p, x1p))
    ya, yb = sorted((y0p, y1p))
    return [int(round(xa)), int(round(ya)), int(round(xb)), int(round(yb))]

def draw_grid(canvas, entries, Px, Py, s, W, H):# for debug
    color = (255, 255, 255)
    thickness = 1
    line_type = cv2.LINE_8

    for e in entries:
        bx = apply_zoom_to_box_identity_at_1(e.get("box", [0,0,0,0]), Px, Py, s)
        x0, y0, x1, y1 = bx
        dx0, dy0 = max(0, x0), max(0, y0)
        dx1, dy1 = min(W, x1), min(H, y1)
        if dx1 <= dx0 or dy1 <= dy0:
            continue
        cv2.rectangle(
            canvas,
            (dx0, dy0),
            (dx1 - 1, dy1 - 1),
            color,
            thickness,
            lineType=line_type
        )

# ---------- main ----------
def main():
    ap = argparse.ArgumentParser(description="Render full frame sequence with unzoom; focus timing exact; white grid overlay.")
    ap.add_argument("--matches", required=True)
    ap.add_argument("--fps", type=int, default=20)
    ap.add_argument("--pre_roll", type=int, default=80)
    ap.add_argument("--post_roll", type=int, default=20)
    ap.add_argument("--focus_tile", type=int, default=0)
    ap.add_argument("--zoom_gamma", type=float, default=0.7)
    ap.add_argument("--width", type=int, default=1920)
    ap.add_argument("--height", type=int, default=1080)
    ap.add_argument("--frames_dir", required=True)
    ap.add_argument("--video_out", required=True)
    ap.add_argument("--start_frame", type=int, default=0)
    args = ap.parse_args()

    # normalize + ensure dirs
    args.matches    = normp(args.matches)
    args.frames_dir = normp(args.frames_dir)
    args.video_out  = normp(args.video_out)
    ensure_dir(args.frames_dir)
    preview_dir = os.path.dirname(args.video_out) if args.video_out else args.frames_dir
    ensure_dir(preview_dir)

    # load matches
    with open(args.matches, "r", encoding="utf-8") as f:
        entries = json.load(f)

    W, H = int(args.width), int(args.height)
    focus_idx = int(args.pre_roll)
    total_frames = int(args.pre_roll) + 1 + int(args.post_roll)
    start_frame = args.start_frame;

    # focus center & starting scale
    fx, fy, s0 = compute_focus_params(entries, args.focus_tile, W, H)
    Px, Py     = compute_transform_origin(entries, args.focus_tile, W, H, s0)

    # meta cache
    vmeta: Dict[str, Tuple[float, int, float]] = {}
    def get_meta(v: str) -> Tuple[float, int, float]:
        if v not in vmeta:
            vmeta[v] = video_meta(v)
        return vmeta[v]

    # render
    for fi in range(start_frame, total_frames):
        t_offset = (fi - focus_idx) / float(args.fps)
        s = zoom_factor_S(fi, focus_idx, s0, args.zoom_gamma)

        canvas = np.zeros((H, W, 3), dtype=np.uint8)
        skipped = 0

        for i, e in enumerate(entries):
            # ----- for quicker debug
            # if (i%10!=0) & (i != args.focus_tile):
            #     continue

            box = e.get("box", [0, 0, 0, 0])
            box_zoomed = apply_zoom_to_box_identity_at_1(box, Px, Py, s)

            m   = e.get("match", {})
            vid = m.get("video")
            t0  = m.get("t")
            idx = m.get("frame_idx")
            var = m.get("variant", "center")

            if not vid or not box_visible_on_canvas(box_zoomed, W, H):
                skipped += 1
                continue

            fps_hint, frame_count, duration = get_meta(vid)

            # Prefer exact index stepping when available
            frame = None
            if isinstance(idx, int) and fps_hint > 0:
                idx_final = int(round(idx + t_offset * fps_hint))
                # Clamp by duration if known
                if duration > 0 and fps_hint > 0:
                    max_idx = max(0, int(round(duration * fps_hint)) - 1)
                    idx_final = max(0, min(max_idx, idx_final))
                frame = read_frame_robust(vid, None, idx_final, fps_hint=fps_hint)

            if frame is None:
                # Time-based fallback (or when no idx)
                if isinstance(t0, (int, float)):
                    t_base = float(t0)
                elif isinstance(idx, int) and fps_hint > 0:
                    t_base = float(idx) / float(fps_hint)
                else:
                    t_base = 0.0
                t_final = t_base + t_offset
                if duration > 0.0:
                    t_final = max(0.0, min(duration, t_final))
                frame = read_frame_robust(vid, t_final, None, fps_hint=fps_hint)

            if frame is None:
                skipped += 1
                continue

            x0, y0, x1, y1 = box_zoomed
            tw, th = max(1, x1 - x0), max(1, y1 - y0)
            patch = crop_resize_fill(frame, tw, th, var)
            paste_tile(canvas, patch, box_zoomed)

        # draw white grid (all tiles, regardless of skipping)
        # draw_grid(canvas, entries, Px, Py, s, W, H)        

        out_png = os.path.join(args.frames_dir, f"frame_{fi:04d}.png")
        ensure_dir(os.path.dirname(out_png))
        Image.fromarray(canvas).save(out_png)

        if fi == focus_idx:
            preview_jpg = os.path.join(preview_dir, "mosaic_from_matches.jpg")
            ensure_dir(os.path.dirname(preview_jpg))
            Image.fromarray(canvas).save(preview_jpg, quality=95)

        if (fi % 1) == 0 or fi == total_frames - 1:
            print(f"[{fi+1}/{total_frames}] {os.path.basename(out_png)}  zoom={s:.3f}  skipped={skipped}")

if __name__ == "__main__":
    main()

