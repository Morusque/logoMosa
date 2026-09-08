#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Extrait une fois pour toutes le petit bout de film que chaque tuile joue.

Le rendu actuel ouvre le fichier video, cherche, lit UNE image, referme --
et recommence pour chacune des 729 tuiles, a chacune des 103 images de la
sequence. Soit 75 000 acces disperses dans 441 Go. Mesure : 13 minutes pour
une seule image, dont 2,4 secondes de calcul. Tout le reste est de l'attente
disque.

Or chaque tuile a besoin d'un segment CONTIGU : de t-5 s a t+0,1 s. Un seul
decodage sequentiel par tuile suffit donc, au lieu de 103 seeks.

Et ce segment ne depend PAS de la tuile de focus : le decalage temporel est le
meme pour tout le monde, seule la geometrie du zoom change. Le cache se paie
une fois et sert a tous les logos qu'on voudra ensuite.

Le recadrage est deja applique (centre, au format de la tuile), comme le fera
le rendu.

  python cache_tuiles.py                    # construit ce qui manque
  python cache_tuiles.py --largeur 240      # plus fin, plus lourd
  python cache_tuiles.py --force            # tout refaire

INTERRUPTIBLE : Ctrl-C, puis relance la meme commande pour reprendre.
"""
import argparse
import io
import json
import os
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor

from config import CFG

HERE = os.path.dirname(os.path.abspath(__file__))


def parametres(args):
    """Les reglages dont depend le contenu du cache. S'ils changent, le cache
    est perime : on le compare a ce qui est inscrit dans le manifeste."""
    return {"pre_roll": args.pre_roll, "post_roll": args.post_roll,
            "fps": args.fps, "largeur": args.largeur,
            "matches": os.path.basename(args.matches)}


def extraire(job):
    """Un segment -> un petit mp4. -> (indice, nb d'images, message d'erreur)"""
    i, chemin, t0, args, ratio, dst = job
    n = args.pre_roll + 1 + args.post_roll
    debut = t0 - args.pre_roll / float(args.fps)
    # Un film peut commencer moins de 5 s avant l'instant retenu : on part de 0
    # et le rendu tiendra compte du nombre d'images reellement obtenues.
    debut = max(0.0, debut)
    duree = n / float(args.fps) + 0.5
    h = int(round(args.largeur / ratio)) // 2 * 2
    vf = ("fps=%d,crop=w='min(iw,ih*%.6f)':h='min(ih,iw/%.6f)':"
          "x='(iw-out_w)/2':y='(ih-out_h)/2',scale=%d:%d"
          % (args.fps, ratio, ratio, args.largeur, h))
    tmp = dst + ".tmp.mp4"
    p = subprocess.run(
        ["ffmpeg", "-v", "error", "-y", "-ss", "%.4f" % debut, "-i", chemin,
         "-t", "%.4f" % duree, "-vf", vf, "-frames:v", str(n),
         "-an", "-c:v", "libx264", "-crf", "16", "-preset", "veryfast",
         "-pix_fmt", "yuv420p", tmp],
        capture_output=True)
    if p.returncode != 0 or not os.path.exists(tmp):
        return i, 0, (p.stderr.decode("utf-8", "replace").strip().splitlines()
                      or ["echec ffmpeg"])[-1][:160]
    # combien d'images a-t-on vraiment ?
    q = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0",
                        "-count_frames", "-show_entries", "stream=nb_read_frames",
                        "-of", "default=nw=1:nk=1", tmp], capture_output=True)
    try:
        got = int((q.stdout or b"0").decode().strip() or 0)
    except ValueError:
        got = 0
    if got <= 0:
        os.unlink(tmp)
        return i, 0, "aucune image extraite"
    os.replace(tmp, dst)
    return i, got, None


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--matches", default=None,
                    help="defaut : out_mosaic/matches_exhaustif.json")
    ap.add_argument("--dossier", default=None, help="defaut : data/cache")
    ap.add_argument("--pre_roll", type=int, default=None)
    ap.add_argument("--post_roll", type=int, default=None)
    ap.add_argument("--fps", type=int, default=None)
    ap.add_argument("--largeur", type=int, default=160,
                    help="largeur d'une tuile en cache. 160 couvre les tuiles "
                         "montrees jusqu'a ~2x ; celles qui grossissent plus "
                         "pres du focus seront reextraites au rendu")
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--workers", type=int, default=6)
    args = ap.parse_args()

    corpus = CFG.path("corpus")
    out_dir = CFG.path("out_dir", doit_exister=False)
    args.matches = args.matches or os.path.join(out_dir, "matches_exhaustif.json")
    args.fps = args.fps or int(CFG.get("fps", "20"))
    args.pre_roll = args.pre_roll if args.pre_roll is not None else int(CFG.get("pre_roll", "100"))
    args.post_roll = args.post_roll if args.post_roll is not None else int(CFG.get("post_roll", "2"))
    dossier = args.dossier or os.path.join(HERE, "data", "cache")
    os.makedirs(dossier, exist_ok=True)

    entrees = json.load(io.open(args.matches, encoding="utf-8"))
    x0, y0, x1, y1 = entrees[0]["box"]
    ratio = (x1 - x0) / float(y1 - y0)
    n = args.pre_roll + 1 + args.post_roll

    manif = os.path.join(dossier, "manifeste.json")
    params = parametres(args)
    ancien = {}
    if os.path.exists(manif):
        try:
            ancien = json.load(io.open(manif, encoding="utf-8"))
        except ValueError:
            ancien = {}
    if ancien.get("parametres") and ancien["parametres"] != params and not args.force:
        sys.exit("le cache existant a ete construit avec d'autres reglages :\n"
                 "  %s\n  %s\nrelance avec --force pour le refaire"
                 % (ancien["parametres"], params))
    images = {int(k): v for k, v in (ancien.get("images") or {}).items()}

    jobs, deja = [], 0
    for i, e in enumerate(entrees):
        m = e.get("match", {})
        rel = m.get("rel")
        if not rel or m.get("t") is None:
            continue
        dst = os.path.join(dossier, "%04d.mp4" % i)
        if not args.force and os.path.exists(dst) and images.get(i):
            deja += 1
            continue
        jobs.append((i, os.path.join(corpus, rel), float(m["t"]), args, ratio, dst))

    print("cache : %s" % dossier)
    print("  %d images par tuile a %d im/s  (de t-%.2f s a t+%.2f s)"
          % (n, args.fps, args.pre_roll / float(args.fps),
             args.post_roll / float(args.fps)))
    print("  %d tuiles a extraire, %d deja en cache\n" % (len(jobs), deja), flush=True)
    if not jobs:
        print("rien a faire")
        return

    def sauver():
        json.dump({"parametres": params, "n_images": n, "ratio": ratio,
                   "images": {str(k): v for k, v in images.items()}},
                  io.open(manif, "w", encoding="utf-8"))

    faits, rates = 0, []
    try:
        with ThreadPoolExecutor(max_workers=args.workers) as ex:
            for i, got, err in ex.map(extraire, jobs):
                faits += 1
                if err:
                    rates.append((i, err))
                else:
                    images[i] = got
                if faits % 50 == 0:
                    sauver()
                    print("  %d/%d" % (faits, len(jobs)), flush=True)
    except KeyboardInterrupt:
        print("\ninterrompu -- relance la meme commande pour reprendre", flush=True)
    finally:
        sauver()

    courts = [(i, v) for i, v in images.items() if v < n]
    print("\nok : %d tuiles en cache" % len(images))
    if courts:
        print("  %d tuiles plus courtes que %d images (film trop court avant "
              "l'instant retenu) -- le rendu tiendra la premiere image" % (len(courts), n))
    for i, err in rates[:8]:
        print("  ECHEC tuile %d : %s" % (i, err))
    taille = sum(os.path.getsize(os.path.join(dossier, f))
                 for f in os.listdir(dossier) if f.endswith(".mp4"))
    print("  %.0f Mo sur le disque" % (taille / 1e6))


if __name__ == "__main__":
    main()
