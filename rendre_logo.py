#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Rend un logo anime a partir du cache de tuiles. Encode la video.

Le rendu d'origine rouvrait chaque film pour chaque image de chaque tuile :
13 minutes par image, dont 2,4 secondes de calcul. Ici tous les bouts de film
sont deja sur le disque (cache_tuiles.py) : il ne reste que de la composition,
et elle est en memoire.

La geometrie du zoom est reprise telle quelle de render_mosaic_from_matches.py
-- meme centre, meme sigmoide -- pour que le mouvement soit identique a celui
des neuf clips de l'an dernier.

Une subtilite : pres du debut, la tuile de focus remplit l'ecran. Le cache est
en 160 px de large, largement insuffisant pour ca. On calcule donc, tuile par
tuile, la taille maximale qu'elle atteindra a l'ecran dans CE rendu, et on
reextrait en haute definition la poignee de tuiles concernees. Les autres ne
depassent jamais leur definition de cache.

  python rendre_logo.py --focus 364
  python rendre_logo.py --hasard              # une tuile au hasard
  python rendre_logo.py --focus 364 --son     # + le son du film de focus et le sfx
  python rendre_logo.py --focus 364 --montee 0  # sans fondu d ouverture

INTERRUPTIBLE seulement entre deux rendus : un rendu dure quelques minutes.
"""
import argparse
import io
import json
import os
import random
import shutil
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor

import cv2
import numpy as np

from config import CFG
from cache_tuiles import extraire
from geometrie import (apply_zoom_to_box_identity_at_1, box_visible_on_canvas,
                       compute_focus_params, compute_transform_origin,
                       paste_tile, zoom_factor_S)

HERE = os.path.dirname(os.path.abspath(__file__))


def lire_clip(chemin):
    """Le petit mp4 du cache -> (n, h, w, 3) uint8, en RGB.

    Par OpenCV et non par un ffmpeg : lancer un sous-processus par tuile
    coutait 49 s sur les 729, contre 15 s en processus et 6 s en parallele.
    C etait le premier poste de depense du rendu."""
    cap = cv2.VideoCapture(chemin)
    if not cap.isOpened():
        return None
    images = []
    while True:
        ok, fr = cap.read()
        if not ok:
            break
        images.append(fr[:, :, ::-1])          # BGR -> RGB
    cap.release()
    return np.array(images) if images else None


def flou_zoom(img, recul, force, n=7):
    """Flou radial (de zoom) autour du centre, avec un leger recul d echelle.

    C est l effet releve sur les clips existants au moment du pop : la mosaique
    recule et file sur une ou deux images, le logo arrive de la meme facon en
    sens inverse. On moyenne quelques copies d echelles voisines -- c est ce
    que fait un flou radial, et ca coute deux images de calcul."""
    if force <= 0 and recul == 0:
        return img
    h, w = img.shape[:2]
    c = (w * 0.5, h * 0.5)
    acc = np.zeros((h, w, 3), dtype=np.float32)
    for k in range(n):
        e = 1.0 + recul + force * (k / float(n - 1))
        M = cv2.getRotationMatrix2D(c, 0.0, e)
        acc += cv2.warpAffine(img, M, (w, h), flags=cv2.INTER_LINEAR,
                              borderMode=cv2.BORDER_CONSTANT, borderValue=(0, 0, 0))
    return np.clip(acc / n, 0, 255).astype(np.uint8)


def besoins(entrees, Px, Py, total, focus_idx, s0, raideur, W, H):
    """Largeur maximale que chaque tuile atteindra a l ecran dans ce rendu.

    Meme transformation que apply_zoom_to_box_identity_at_1, mais sur les 729
    boites a la fois : la boucle Python coutait plusieurs secondes par rendu."""
    b = np.array([e["box"] for e in entrees], dtype=np.float64)
    x0, y0, x1, y1 = b[:, 0], b[:, 1], b[:, 2], b[:, 3]
    besoin = np.zeros(len(entrees), dtype=np.int32)
    for fi in range(total):
        s = zoom_factor_S(fi, focus_idx, s0, raideur)
        ax = (x0 - Px) * s + Px
        bx = (x1 - Px) * s + Px
        ay = (y0 - Py) * s + Py
        by = (y1 - Py) * s + Py
        gx, dx = np.minimum(ax, bx), np.maximum(ax, bx)
        hy, by2 = np.minimum(ay, by), np.maximum(ay, by)
        vu = (np.minimum(W, dx) > np.maximum(0, gx)) & \
             (np.minimum(H, by2) > np.maximum(0, hy))
        besoin = np.maximum(besoin, np.where(vu, np.round(dx - gx), 0).astype(np.int32))
    return besoin


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--focus", type=int, default=None, help="numero de tuile")
    ap.add_argument("--hasard", action="store_true",
                    help="tire une tuile au hasard, en evitant les ouvertures "
                         "sur un carton de generique")
    ap.add_argument("--tout_accepter", action="store_true",
                    help="avec --hasard : ne pas ecarter les ouvertures mortes")
    ap.add_argument("--matches", default=None)
    ap.add_argument("--cache", default=None)
    ap.add_argument("--sortie", default=None)
    ap.add_argument("--raideur", type=float, default=3.0,
                    help="raideur de la sigmoide du dezoom (l'ancien --zoom_gamma)")
    ap.add_argument("--son", action="store_true",
                    help="ajoute le son du film de focus puis le sfx seul")
    ap.add_argument("--tenue", type=float, default=1.1,
                    help="duree pendant laquelle le logo propre est tenu")
    ap.add_argument("--noir", type=float, default=0.5)
    ap.add_argument("--montee", type=float, default=0.5,
                    help="fondu d ouverture, image ET son. Une seule valeur "
                         "pour les deux : ils doivent monter ensemble")
    ap.add_argument("--pop", type=int, default=2,
                    help="images de flou de zoom de part et d autre de la "
                         "revelation. 0 pour une coupe franche")
    ap.add_argument("--pop_force", type=float, default=0.11,
                    help="amplitude du flou et du recul, en fraction du cadre")
    ap.add_argument("--graine", type=int, default=None)
    ap.add_argument("--workers", type=int, default=6)
    args = ap.parse_args()

    W, H = int(CFG.get("width", "1920")), int(CFG.get("height", "1080"))
    fps = int(CFG.get("fps", "20"))
    pre_roll = int(CFG.get("pre_roll", "100"))
    post_roll = int(CFG.get("post_roll", "2"))
    out_dir = CFG.path("out_dir", doit_exister=False)
    matches = args.matches or CFG.path("matches")
    cache = args.cache or os.path.join(HERE, "data", "cache")

    entrees = json.load(io.open(matches, encoding="utf-8"))
    manif_p = os.path.join(cache, "manifeste.json")
    if not os.path.exists(manif_p):
        sys.exit("cache absent : lance d'abord\n  python cache_tuiles.py")
    manif = json.load(io.open(manif_p, encoding="utf-8"))
    largeur = manif["parametres"]["largeur"]
    ratio = manif["ratio"]
    hauteur = int(round(largeur / ratio)) // 2 * 2
    dispo = {int(k): v for k, v in manif["images"].items()}
    if manif["parametres"]["fps"] != fps or manif["parametres"]["pre_roll"] != pre_roll:
        sys.exit("le cache a ete construit avec d'autres reglages de temps :\n"
                 "  %s\nrelance cache_tuiles.py --force" % manif["parametres"])

    jouables = [i for i in range(len(entrees)) if i in dispo]
    if args.hasard:
        if args.graine is not None:
            random.seed(args.graine)
        # Le clip s ouvre sur cette tuile en plein cadre pendant plusieurs
        # secondes : c est le plan le plus vu du film. Un carton de generique
        # y est ennuyeux, alors qu il passe inapercu dans la mosaique.
        choix = jouables
        if not args.tout_accepter:
            from ouvertures import convenables, mesures
            bons = set(convenables(mesures(cache)))
            choix = [i for i in jouables if i in bons] or jouables
            print("  %d tuiles sur %d ont une ouverture convenable"
                  % (len(choix), len(jouables)))
        args.focus = random.choice(choix)
        print("tuile tiree au hasard : %d" % args.focus)
    if args.focus is None:
        sys.exit("donne --focus N, ou --hasard")

    focus_idx = pre_roll
    total = pre_roll + 1 + post_roll
    _fx, _fy, s0 = compute_focus_params(entrees, args.focus, W, H)
    Px, Py = compute_transform_origin(entrees, args.focus, W, H, s0)

    m = entrees[args.focus].get("match", {})
    print("focus  : tuile %d  <- %s" % (args.focus, (m.get("rel") or "?")))
    print("sortie : %d images, %d im/s, zoom de %.1fx a 1x" % (total, fps, s0),
          flush=True)

    # --- quelles tuiles reclament mieux que le cache ?
    print("\ncalcul des besoins de definition...", flush=True)
    besoin = besoins(entrees, Px, Py, total, focus_idx, s0, args.raideur, W, H)
    gros = [i for i in jouables if besoin[i] > largeur * 1.15]
    print("  %d tuiles visibles, dont %d a reextraire en haute definition"
          % (int((besoin > 0).sum()), len(gros)))

    hd = os.path.join(HERE, "data", "cache_hd", "tuile%04d" % args.focus)
    chemins = {i: os.path.join(cache, "%04d.mp4" % i) for i in jouables}
    tailles = {i: (largeur, hauteur) for i in jouables}
    if gros:
        os.makedirs(hd, exist_ok=True)
        corpus = CFG.path("corpus")

        class P(object):                       # les reglages qu'attend extraire()
            pass
        jobs = []
        for i in gros:
            lg = int(min(W, besoin[i])) // 2 * 2
            dst = os.path.join(hd, "%04d_%d.mp4" % (i, lg))
            chemins[i] = dst
            tailles[i] = (lg, int(round(lg / ratio)) // 2 * 2)
            if os.path.exists(dst):
                continue
            p = P()
            p.pre_roll, p.post_roll, p.fps, p.largeur = pre_roll, post_roll, fps, lg
            jobs.append((i, os.path.join(corpus, entrees[i]["match"]["rel"]),
                         float(entrees[i]["match"]["t"]), p, ratio, dst))
        if jobs:
            print("  extraction haute definition de %d tuiles..." % len(jobs),
                  flush=True)
            with ThreadPoolExecutor(max_workers=args.workers) as ex:
                for i, got, err in ex.map(extraire, jobs):
                    if err:
                        print("     ECHEC tuile %d : %s" % (i, err))
                        chemins[i] = os.path.join(cache, "%04d.mp4" % i)
                        tailles[i] = (largeur, hauteur)

    # --- geometrie precalculee : boite de chaque tuile a chaque image
    zooms = [zoom_factor_S(fi, focus_idx, s0, args.raideur) for fi in range(total)]

    # --- composition. On garde les 103 toiles en memoire et on ne lit chaque
    # clip qu'une fois : c'est l'inverse de l'ancien rendu, qui gardait une
    # toile et relisait tous les films.
    toiles = np.zeros((total, H, W, 3), dtype=np.uint8)
    print("\ncomposition (%.0f Mo de toiles en memoire)..."
          % (toiles.nbytes / 1e6), flush=True)
    etat = {"posees": 0, "vides": 0, "faites": 0}

    def coller(i, clip):
        if clip is None:
            etat["vides"] += 1
            return
        w_i = clip.shape[2]
        box = entrees[i]["box"]
        for fi in range(total):
            bx = apply_zoom_to_box_identity_at_1(box, Px, Py, zooms[fi])
            if not box_visible_on_canvas(bx, W, H):
                continue
            tw, th = max(1, bx[2] - bx[0]), max(1, bx[3] - bx[1])
            src = clip[min(fi, len(clip) - 1)]
            interp = cv2.INTER_AREA if tw < w_i else cv2.INTER_CUBIC
            paste_tile(toiles[fi], cv2.resize(src, (tw, th), interpolation=interp), bx)
            etat["posees"] += 1
        etat["faites"] += 1
        if etat["faites"] % 150 == 0:
            print("  %d/%d tuiles" % (etat["faites"], len(jouables)), flush=True)

    # Les tuiles de cache sont lues en parallele. Les tuiles haute definition,
    # elles, sont lues UNE A UNE : celle du focus fait 1920 de large, soit
    # 640 Mo de clip a elle seule -- en precharger six saturerait la memoire.
    petits = [i for i in jouables if i not in set(gros)]
    with ThreadPoolExecutor(max_workers=args.workers) as ex:
        for i, clip in zip(petits, ex.map(lambda j: lire_clip(chemins[j]), petits)):
            coller(i, clip)
    for i in gros:
        coller(i, lire_clip(chemins[i]))
    print("  %d collages, %d tuiles sans clip" % (etat["posees"], etat["vides"]))

    # --- la queue : le logo propre, puis le noir
    logo = cv2.cvtColor(cv2.imread(CFG.path("target"), cv2.IMREAD_COLOR),
                        cv2.COLOR_BGR2RGB)
    if logo.shape[:2] != (H, W):
        logo = cv2.resize(logo, (W, H), interpolation=cv2.INTER_AREA)
    n_tenue, n_noir = int(round(args.tenue * fps)), int(round(args.noir * fps))
    vide = np.zeros((H, W, 3), dtype=np.uint8)

    # --- encodage
    os.makedirs(out_dir, exist_ok=True)
    sortie = args.sortie or os.path.join(out_dir, "logo_tuile%04d.mp4" % args.focus)
    muet = sortie if not args.son else sortie + ".muet.mp4"
    n_total = total + n_tenue + n_noir
    print("\nencodage de %d images -> %s" % (n_total, os.path.basename(muet)),
          flush=True)
    p = subprocess.Popen(
        ["ffmpeg", "-v", "error", "-y", "-f", "rawvideo", "-pix_fmt", "rgb24",
         "-s", "%dx%d" % (W, H), "-r", str(fps), "-i", "-",
         "-c:v", "libx264", "-crf", "18", "-preset", "fast",
         "-pix_fmt", "yuv420p", muet], stdin=subprocess.PIPE)
    # ouverture en fondu depuis le noir, puis la mosaique recule et se floute
    # au pop, et le logo arrive de la meme facon en sens inverse
    n_fondu = int(round(args.montee * fps))
    for fi in range(total):
        img = toiles[fi]
        k = fi - (total - args.pop)
        if args.pop and k >= 0:
            f = (k + 1) / float(args.pop)
            img = flou_zoom(img, -args.pop_force * f, args.pop_force * f)
        if fi < n_fondu:
            # rampe lineaire, comme le afade du son : les deux montent ensemble
            img = (img * ((fi + 1) / float(n_fondu))).astype(np.uint8)
        p.stdin.write(np.ascontiguousarray(img).tobytes())
    for j in range(n_tenue):
        img = logo
        if args.pop and j < args.pop:
            f = 1.0 - (j + 1) / float(args.pop + 1)
            img = flou_zoom(img, -args.pop_force * f, args.pop_force * f)
        p.stdin.write(np.ascontiguousarray(img).tobytes())
    for _ in range(n_noir):
        p.stdin.write(vide.tobytes())
    p.stdin.close()
    p.wait()

    if args.son:
        from son_logo import habiller
        habiller(muet, entrees[args.focus]["match"], sortie, fps,
                 focus_idx / float(fps), montee=args.montee,
                 duree_totale=n_total / float(fps))
        os.unlink(muet)

    print("\n-> %s  (%.1f Mo)" % (sortie, os.path.getsize(sortie) / 1e6))


if __name__ == "__main__":
    main()
