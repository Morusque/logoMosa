#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# ce script vit dans ancien/ : config.py est un cran au-dessus
import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))

import argparse, json, os, sys, random
from collections import defaultdict
from typing import List, Dict, Any, Optional

import cv2
import numpy as np
from PIL import Image

# Optional: silence ffmpeg/OpenCV spam
try:
    cv2.setLogLevel(cv2.LOG_LEVEL_SILENT)
except Exception:
    pass

VIDEO_EXTS = {".mp4", ".mov", ".m4v", ".avi", ".mpg", ".mpeg", ".wmv", ".mkv", ".webm"}

def vprint(enabled: bool, *args, **kwargs):
    if enabled:
        print(*args, **kwargs)

def normalize_path_win(p: Optional[str]) -> Optional[str]:
    if not isinstance(p, str) or not p:
        return p
    if p.startswith("\\\\?\\"):
        p = p[4:]
    return os.path.normpath(p)

def scan_videos(root: str) -> List[str]:
    out = []
    for dirpath, _, filenames in os.walk(root):
        for fn in filenames:
            ext = os.path.splitext(fn)[1].lower()
            if ext in VIDEO_EXTS:
                out.append(normalize_path_win(os.path.join(dirpath, fn)))
    random.shuffle(out)
    return out

def open_video(path: str):
    cap = cv2.VideoCapture(path)
    if not cap or not cap.isOpened():
        return None
    return cap

def video_meta(path: str) -> Optional[Dict[str, float]]:
    cap = open_video(path)
    if cap is None:
        return None
    fps = cap.get(cv2.CAP_PROP_FPS) or 25.0
    frame_count = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
    duration = frame_count / fps if fps > 0 else 0.0
    cap.release()
    return {"fps": float(fps), "frame_count": float(frame_count), "duration": float(duration)}

def read_frame_at_idx(path: str, frame_idx: int) -> Optional[np.ndarray]:
    cap = open_video(path)
    if cap is None:
        return None
    cap.set(cv2.CAP_PROP_POS_FRAMES, max(0, int(frame_idx)))
    ok, frame = cap.read()
    cap.release()
    if not ok or frame is None:
        return None
    return cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)

def read_frame_at_time(path: str, t_seconds: float, fps_hint: Optional[float]=None) -> Optional[np.ndarray]:
    cap = open_video(path)
    if cap is None:
        return None
    cap.set(cv2.CAP_PROP_POS_MSEC, max(0.0, float(t_seconds))*1000.0)
    ok, frame = cap.read()
    if not ok or frame is None:
        if fps_hint and fps_hint > 0:
            cap.set(cv2.CAP_PROP_POS_FRAMES, int(max(0.0, t_seconds) * fps_hint))
            ok, frame = cap.read()
    cap.release()
    if not ok or frame is None:
        return None
    return cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)

def fetch_frame_safely(vid: str, t0: float, frame_idx: int, fps: float) -> Optional[np.ndarray]:
    fr = read_frame_at_idx(vid, frame_idx)
    if fr is not None:
        return fr
    fr = read_frame_at_time(vid, t0, fps_hint=fps)
    if fr is not None:
        return fr
    # Probe a few neighbors (helps with GOP/seek quirks)
    for d in (1, -1, 2, -2, 3, -3):
        fr = read_frame_at_idx(vid, max(0, frame_idx + d))
        if fr is not None:
            return fr
    return None

def reduce_img(img_rgb: np.ndarray, w: int, h: int) -> np.ndarray:
    return cv2.resize(img_rgb, (w, h), interpolation=cv2.INTER_AREA).astype(np.float32)

def ssd(a: np.ndarray, b: np.ndarray) -> float:
    d = a - b
    return float(np.vdot(d, d)) / (d.size)

def tiles_from_target(target_path: str, cols: int, rows: int):
    im = Image.open(target_path).convert("RGB")
    W, H = im.size
    im_np = np.array(im, dtype=np.uint8)
    tiles = []
    tw = W // cols
    th = H // rows
    for r in range(rows):
        for c in range(cols):
            x0 = c * tw
            y0 = r * th
            x1 = (c + 1) * tw if (c < cols - 1) else W
            y1 = (r + 1) * th if (r < rows - 1) else H
            tiles.append({"box":[x0,y0,x1,y1]})
    return tiles, im_np

def init_preview_canvas(w: int, h: int) -> np.ndarray:
    return np.zeros((h, w, 3), dtype=np.uint8)

def paste_into(canvas: np.ndarray, patch_rgb: np.ndarray, box: List[int]) -> None:
    x0,y0,x1,y1 = box
    pw, ph = x1-x0, y1-y0
    rsz = cv2.resize(patch_rgb, (pw, ph), interpolation=cv2.INTER_AREA)
    canvas[y0:y1, x0:x1, :] = rsz

def load_resume(path: str):
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, list):
            return data
    except Exception:
        pass
    return []

def save_json(path: str, data: Any) -> None:
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)

def normalize_resume_entry(raw: dict) -> dict:
    if not isinstance(raw, dict):
        return {}
    out: Dict[str,Any] = {}
    if "box" in raw and isinstance(raw["box"], list) and len(raw["box"]) == 4:
        out["box"] = [int(v) for v in raw["box"]]
    m = raw.get("match", {}) if isinstance(raw.get("match"), dict) else {}
    video = m.get("video")
    if isinstance(video, str):
        video = normalize_path_win(video)
    frame_idx = m.get("frame_idx", m.get("frame"))
    try:
        frame_idx = int(frame_idx) if frame_idx is not None else None
    except:
        frame_idx = None
    t = m.get("t")
    try:
        t = float(t) if t is not None else None
    except:
        t = None
    dist = m.get("dist")
    try:
        dist = float(dist) if dist is not None else None
    except:
        dist = None
    out["match"] = {
        "video": video,
        "t": t,
        "frame_idx": frame_idx,
        "variant": m.get("variant", "center"),
        "dist": dist if dist is not None else 1e12,
    }
    return out

def main():
    ap = argparse.ArgumentParser(description="Iterative video mosaic builder (with resume).")
    # Chemins absents = ceux de config.txt. Le disque du corpus n'est pas
    # toujours monte sur la meme lettre : la config en essaie plusieurs.
    ap.add_argument("--videos", default=None)
    ap.add_argument("--target", default=None)
    ap.add_argument("--out_dir", default=None)
    ap.add_argument("--grid", nargs=2, type=int, default=None)
    ap.add_argument("--tile_sample", type=int, default=8)
    ap.add_argument("--resume", type=str, default="")
    ap.add_argument("--infinite", action="store_true")
    ap.add_argument("--save_interval", type=int, default=50)
    ap.add_argument("--max_per_video", type=int, default=2)
    ap.add_argument("--margin_start", type=float, default=0.0)
    ap.add_argument("--margin_end", type=float, default=0.0)
    ap.add_argument("--preview_name", type=str, default="preview.png")
    ap.add_argument("--verbose", action="store_true")
    ap.add_argument("--rebuild_preview_only", action="store_true")
    args = ap.parse_args()

    from config import CFG
    args.videos = args.videos or CFG.path("corpus")
    args.target = args.target or CFG.path("target")
    args.out_dir = args.out_dir or CFG.path("out_dir", doit_exister=False)
    args.grid = args.grid or CFG.ints("grid", "27 27")
    print("videos : %s" % args.videos)
    print("target : %s" % args.target)
    print("out    : %s" % args.out_dir)

    os.makedirs(args.out_dir, exist_ok=True)
    random.seed()

    # Target & tiles
    tiles, target_np = tiles_from_target(args.target, args.grid[0], args.grid[1])
    target_h, target_w = target_np.shape[:2]
    preview = init_preview_canvas(target_w, target_h)
    TILES_R = [reduce_img(target_np[y0:y1, x0:x1, :], args.tile_sample, args.tile_sample)
               for (x0,y0,x1,y1) in [t["box"] for t in tiles]]

    # Resume & preview rebuild
    matches_path = args.resume if args.resume else os.path.join(args.out_dir, "matches_pass.json")
    print("Checking for resume file:", matches_path)
    resume_raw = load_resume(matches_path)
    if resume_raw:
        print(f"Resuming with {len(resume_raw)} entries.")
    else:
        print("No resume data found.")

    tile_entries: List[Dict[str,Any]] = []
    pasted = missing_video = frame_fail = skipped_no_match = 0

    for i, t in enumerate(tiles):
        entry = {"box": t["box"], "match": {"video": None, "t": None, "frame_idx": None, "variant":"center", "dist":1e12}}
        if resume_raw and i < len(resume_raw) and isinstance(resume_raw[i], dict):
            norm = normalize_resume_entry(resume_raw[i])
            entry["match"].update(norm.get("match", {}))
        tile_entries.append(entry)

        # rebuild preview tile if possible
        m = entry["match"]
        v, idx = m.get("video"), m.get("frame_idx")
        if v and idx is not None:
            fr = fetch_frame_safely(v, m.get("t") or 0.0, int(idx), fps=25.0)  # fps unused unless time seek fallback
            if fr is None:
                if not os.path.isfile(v): missing_video += 1
                else: frame_fail += 1
            else:
                paste_into(preview, fr, entry["box"])
                pasted += 1
        else:
            skipped_no_match += 1

    print(f"Preview rebuilt: pasted={pasted}, missing={missing_video}, fail={frame_fail}, skipped={skipped_no_match}")
    if args.rebuild_preview_only:
        Image.fromarray(preview).save(os.path.join(args.out_dir, args.preview_name))
        print("Preview saved and exit.")
        return

    # Scan videos
    all_videos = scan_videos(args.videos)
    if not all_videos:
        sys.exit("No videos found.")

    # Meta cache
    vmeta: Dict[str, Dict[str, float]] = {}
    def get_meta(v):
        if v not in vmeta:
            vmeta[v] = video_meta(v) or {"fps":25.0, "frame_count":0.0, "duration":0.0}
        return vmeta[v]

    def current_counts():
        c = defaultdict(int)
        for t in tile_entries:
            mv = t["match"].get("video")
            if mv:
                c[mv] += 1
        return c

    successful = 0

    def save_all():
        save_json(matches_path, tile_entries)
        Image.fromarray(preview).save(os.path.join(args.out_dir, args.preview_name))
        print("Saved.")

    print("Starting loop. Ctrl+C to stop.")
    try:
        while True:
            counts = current_counts()
            eligible = [v for v in all_videos if counts[v] < args.max_per_video] or all_videos

            vid = random.choice(eligible)
            meta = get_meta(vid)
            if meta["duration"] <= 0 or meta["fps"] <= 0 or meta["frame_count"] <= 0:
                vprint(args.verbose, f"[skip] bad meta: {os.path.basename(vid)}")
                continue

            # margins
            start, end = max(0.0, args.margin_start), max(0.0, args.margin_end)
            if start + end >= meta["duration"]:
                vprint(args.verbose, f"[skip] margins too large for {os.path.basename(vid)} (dur={meta['duration']:.2f})")
                continue

            t0 = random.uniform(start, meta["duration"] - end)
            # clamp index with margins at ends
            frame_idx = int(t0 * meta["fps"])
            max_idx = max(0, int(meta["frame_count"]) - 2)
            frame_idx = min(max(1, frame_idx), max_idx)

            fr = fetch_frame_safely(vid, t0, frame_idx, fps=meta["fps"])
            if fr is None:
                vprint(args.verbose, f"[skip] unreadable frame idx={frame_idx} t={t0:.2f}s {os.path.basename(vid)}")
                continue

            fr_r = reduce_img(fr, args.tile_sample, args.tile_sample)

            # find best improvement
            best_impr = 0.0
            best_i = None
            best_dist = None
            for i, t in enumerate(tile_entries):
                cur = float(t["match"].get("dist", 1e12))
                new = ssd(fr_r, TILES_R[i])
                impr = cur - new
                if impr > best_impr:
                    best_impr, best_i, best_dist = impr, i, new

            if best_i is not None and best_impr > 0.0:
                tile_entries[best_i]["match"] = {
                    "video": vid,
                    "t": float(t0),
                    "frame_idx": int(frame_idx),
                    "variant": "center",
                    "dist": float(best_dist)
                }
                paste_into(preview, fr, tile_entries[best_i]["box"])
                successful += 1
                vprint(args.verbose, f"[accept] tile#{best_i} ← {os.path.basename(vid)} "
                                     f"frame={frame_idx} dist={best_dist:.1f} (impr={best_impr:.1f})")

                if successful % args.save_interval == 0:
                    save_all()
            else:
                vprint(args.verbose, "[reject] no improvement")

            if not args.infinite and successful >= args.save_interval:
                break

        save_all()

    except KeyboardInterrupt:
        print("Interrupted. Saving...")
        save_all()

    print("Done.")

if __name__ == "__main__":
    main()
