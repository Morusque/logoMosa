#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Mesure ce qu'un fichier de matches donne VRAIMENT, en decodant ses images.

Les 'dist' inscrits dans un fichier de matches ne sont pas comparables d'un
fichier a l'autre : ils ont ete calcules par le chercheur qui les a produits,
avec sa metrique a lui. mosaic_from_videos.py ecrasait l'image entiere dans un
carre de 16x16 ; chercher_tuiles.py la recadre au centre au format de la tuile,
comme le fait le rendu. Deux echelles differentes, donc deux colonnes qu'on ne
peut pas mettre cote a cote.

Ce script rejuge tout le monde a la meme aune : il va chercher l'image reelle
de chaque tuile, applique le cadrage du RENDU, et compare a la cible. Il ecrit
au passage la mosaique statique -- gratuitement, puisqu'il a decode les images.

  python evaluer_matches.py out_mosaic/matches_pass.json
  python evaluer_matches.py out_mosaic/matches_v3.json --apercu comparaison.jpg

Le detail par famille de tuiles compte plus que la moyenne : sur ce logo, 514
tuiles sur 729 sont noires et n'ont aucun merite a etre reussies, tandis que
les 207 tuiles detaillees portent tout le dessin.
"""

# ce script vit dans outils/ : config.py est un cran au-dessus
import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))

import argparse
import io
import json
import os
import subprocess
from concurrent.futures import ThreadPoolExecutor

import numpy as np
from PIL import Image

from config import CFG
from banque_vignettes import RED, recadrer

HERE = os.path.dirname(os.path.abspath(__file__))


def image_a(chemin, t, largeur=160):
    """L'image du film a l'instant t, en RGB, ou None."""
    p = subprocess.run(
        ["ffmpeg", "-v", "error", "-ss", "%.4f" % max(0.0, t), "-i", chemin,
         "-frames:v", "1", "-vf", "scale=%d:-2" % largeur,
         "-f", "image2pipe", "-vcodec", "png", "-"],
        capture_output=True)
    if not p.stdout:
        return None
    try:
        return np.asarray(Image.open(io.BytesIO(p.stdout)).convert("RGB"), dtype=np.uint8)
    except Exception:
        return None


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("matches")
    ap.add_argument("--cible", default=None)
    ap.add_argument("--apercu", nargs="?", const="AUTO", default=None)
    ap.add_argument("--workers", type=int, default=6)
    args = ap.parse_args()

    corpus = CFG.path("corpus")
    cible = args.cible or CFG.path("target")
    if args.apercu == "AUTO":
        args.apercu = os.path.splitext(args.matches)[0] + "_reel.jpg"

    entrees = json.load(io.open(args.matches, encoding="utf-8"))
    logo = np.asarray(Image.open(cible).convert("RGB"), dtype=np.float32)
    H, W = logo.shape[:2]
    # ratio de tuile : celui de la premiere boite, comme au rendu
    x0, y0, x1, y1 = entrees[0]["box"]
    ratio = (x1 - x0) / float(y1 - y0)

    def tache(e):
        m = e.get("match", {})
        chemin = (os.path.join(corpus, m["rel"]) if m.get("rel") else m.get("video"))
        if not chemin or not os.path.isfile(chemin) or m.get("t") is None:
            return None
        return image_a(chemin, float(m["t"]))

    print("%s : %d tuiles, decodage des images reelles..."
          % (os.path.basename(args.matches), len(entrees)), flush=True)
    imgs = []
    with ThreadPoolExecutor(max_workers=args.workers) as ex:
        for n, im in enumerate(ex.map(tache, entrees), 1):
            imgs.append(im)
            if n % 150 == 0:
                print("  %d/%d" % (n, len(entrees)), flush=True)

    apercu = np.zeros((H, W, 3), dtype=np.uint8) if args.apercu else None
    familles, ecarts, absents = [], [], 0
    for e, im in zip(entrees, imgs):
        bx0, by0, bx1, by1 = e["box"]
        t = logo[by0:by1, bx0:bx1]
        plate = float(t.std()) < 3.0
        famille = ("noire" if plate and float(t.mean()) < 8
                   else "unie" if plate else "detaillee")
        if im is None:
            absents += 1
            familles.append(famille)
            ecarts.append(np.nan)
            continue
        coupe = recadrer(im, ratio)
        v = np.asarray(Image.fromarray(coupe).resize((RED, RED), Image.BILINEAR),
                       dtype=np.float32)
        c = np.asarray(Image.fromarray(t.astype(np.uint8)).resize((RED, RED),
                                                                  Image.BILINEAR),
                       dtype=np.float32)
        familles.append(famille)
        ecarts.append(float(((v - c) ** 2).mean()))
        if apercu is not None:
            apercu[by0:by1, bx0:bx1] = np.asarray(
                Image.fromarray(coupe).resize((bx1 - bx0, by1 - by0), Image.LANCZOS))

    fam = np.array(familles)
    ec = np.array(ecarts, dtype=np.float64)
    ok = ~np.isnan(ec)
    print("\n%d tuiles mesurees, %d sans image" % (ok.sum(), absents))
    print("\n%-12s %5s  %8s %8s %8s   %s"
          % ("famille", "n", "median", "moyen", "max", "au-dela de 1000"))
    for f in ("noire", "unie", "detaillee"):
        m = (fam == f) & ok
        if not m.any():
            continue
        x = ec[m]
        print("%-12s %5d  %8.0f %8.0f %8.0f   %d (%.0f %%)"
              % (f, m.sum(), np.median(x), x.mean(), x.max(),
                 (x > 1000).sum(), 100.0 * (x > 1000).mean()))
    x = ec[ok]
    print("%-12s %5d  %8.0f %8.0f %8.0f" % ("TOUTES", ok.sum(), np.median(x),
                                            x.mean(), x.max()))
    if apercu is not None:
        Image.fromarray(apercu).save(args.apercu, quality=95)
        print("\napercu reel : %s" % args.apercu)


if __name__ == "__main__":
    main()
