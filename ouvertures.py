#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Juge la premiere seconde et demie de chaque tuile, pour ne pas ouvrir un
logo sur un carton de generique.

Le clip commence par la tuile de focus en plein cadre pendant plusieurs
secondes : c'est le plan le plus vu de tout le film. Un carton de titre ou de
fin y est ennuyeux, alors qu'il passe inapercu dans la mosaique.

Rien a decoder de neuf : le cache contient DEJA exactement ce qui sera montre.

Trois mesures sur les premieres images :

  lum     luminance moyenne          un carton est souvent sombre
  bouge   ecart d'une image a l'autre  un carton ne bouge pas
  clair   part de pixels tres clairs    du texte blanc sur fond noir

Le critere ne porte PAS sur le mouvement seul : mesure faite, une tuile jugee
bonne a l'oeil ouvrait sur un plan quasi fixe (bouge 0,82) et aurait ete
ecartee. Ce qui trahit un carton, c'est le NOIR, et accessoirement un texte
clair sur un fond sombre qui ne bouge pas.

  1. on ecarte les ouvertures trop sombres (lum < 30) ;
  2. on ecarte les cartons : sombres, figes, avec du texte clair.

  python ouvertures.py            # rapport, du pire au meilleur
  python ouvertures.py --force    # recalcule
"""
import argparse
import io
import json
import os
import subprocess
from concurrent.futures import ThreadPoolExecutor

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
N_IMG = 30                     # 1,5 s a 20 im/s


def _mesurer(job):
    i, chemin, w, h = job
    p = subprocess.run(["ffmpeg", "-v", "error", "-i", chemin,
                        "-frames:v", str(N_IMG), "-f", "rawvideo",
                        "-pix_fmt", "rgb24", "-"], capture_output=True)
    a = np.frombuffer(p.stdout, dtype=np.uint8)
    n = a.size // (w * h * 3)
    if n < 2:
        return i, None
    v = a[:n * w * h * 3].reshape(n, h * w, 3).astype(np.float32)
    lum = 0.2126 * v[..., 0] + 0.7152 * v[..., 1] + 0.0722 * v[..., 2]
    return i, {"lum": round(float(lum.mean()), 2),
               "bouge": round(float(np.abs(np.diff(lum, axis=0)).mean()), 3),
               "clair": round(float((lum > 200).mean()), 5)}


def mesures(cache, force=False, workers=8):
    """-> {indice de tuile: {lum, bouge, clair}}, calcule une fois puis relu."""
    manif = json.load(io.open(os.path.join(cache, "manifeste.json"), encoding="utf-8"))
    largeur = manif["parametres"]["largeur"]
    h = int(round(largeur / manif["ratio"])) // 2 * 2
    dst = os.path.join(cache, "ouvertures.json")
    if not force and os.path.exists(dst):
        try:
            d = json.load(io.open(dst, encoding="utf-8"))
            if d.get("largeur") == largeur:
                return {int(k): v for k, v in d["tuiles"].items()}
        except ValueError:
            pass
    jobs = [(i, os.path.join(cache, "%04d.mp4" % i), largeur, h)
            for i in sorted(int(k) for k in manif["images"])]
    out = {}
    print("mesure de l'ouverture de %d tuiles..." % len(jobs), flush=True)
    with ThreadPoolExecutor(max_workers=workers) as ex:
        for i, m in ex.map(_mesurer, jobs):
            if m:
                out[i] = m
    json.dump({"largeur": largeur, "n_images": N_IMG,
               "tuiles": {str(k): v for k, v in out.items()}},
              io.open(dst, "w", encoding="utf-8"))
    return out


def carton(v, lum_min=30.0):
    """Cette ouverture ressemble-t-elle a un carton de generique ?"""
    if v["lum"] < lum_min:
        return True                          # noir ou presque
    # sombre + fige + du texte clair dessus
    return v["lum"] < 60.0 and v["bouge"] < 0.5 and v["clair"] > 0.0005


def convenables(m, lum_min=30.0):
    """Les tuiles dont l'ouverture n'est pas un carton. Seuils calibres sur le
    corpus : voir la sortie de `python ouvertures.py`."""
    return sorted(i for i, v in m.items() if not carton(v, lum_min))


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--cache", default=os.path.join(HERE, "data", "cache"))
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--lum_min", type=float, default=30.0)
    args = ap.parse_args()

    m = mesures(args.cache, args.force)
    lum = np.array([v["lum"] for v in m.values()])
    bou = np.array([v["bouge"] for v in m.values()])
    print("\n%d tuiles mesurees" % len(m))
    for nom, x in (("luminance", lum), ("mouvement", bou)):
        q = np.sort(x)
        print("  %-10s p5=%.2f  p25=%.2f  median=%.2f  p75=%.2f  p95=%.2f"
              % (nom, q[len(q) // 20], q[len(q) // 4], q[len(q) // 2],
                 q[3 * len(q) // 4], q[19 * len(q) // 20]))
    ok = convenables(m, args.lum_min)
    print("\nretenues (ni noires, ni cartons figes) : %d / %d" % (len(ok), len(m)))

    rel = {}
    try:
        from config import CFG
        e = json.load(io.open(CFG.path("matches"), encoding="utf-8"))
        rel = {i: (x["match"].get("rel") or "?").split("/")[-1][:44]
               for i, x in enumerate(e)}
    except Exception:
        pass
    pires = sorted((i for i in m if carton(m[i], args.lum_min)),
                   key=lambda i: (m[i]["lum"], m[i]["bouge"]))[:12]
    print("\nles 12 ouvertures les plus mortes (ecartees) :")
    print("%6s %7s %7s %8s  %s" % ("tuile", "lum", "bouge", "clair", "film"))
    for i in pires:
        print("%6d %7.1f %7.2f %8.4f  %s"
              % (i, m[i]["lum"], m[i]["bouge"], m[i]["clair"], rel.get(i, "")))
