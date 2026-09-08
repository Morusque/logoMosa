#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""La geometrie du dezoom : c'est elle qui definit le MOUVEMENT du logo.

Ces fonctions viennent telles quelles de render_mosaic_from_matches.py, le
rendu de 2025 (desormais dans ancien/). Elles etaient melees a un script en
ligne de commande, si bien que le nouveau rendu devait importer un outil
entier pour quatre calculs. Les voici a part, sans rien changer aux formules :
le mouvement des nouveaux clips est identique a celui des neuf premiers.

Le principe du dezoom
---------------------
On cherche une transformation d'echelle qui soit l'IDENTITE quand s = 1 (la
mosaique est alors a sa place exacte) et qui, quand s = s0, remplisse l'ecran
avec la seule tuile de focus. Il suffit pour cela de zoomer autour d'un point
fixe P bien choisi, et non autour du centre de l'ecran :

    ecran = (mosaique - P) * s + P

compute_transform_origin resout P pour ces deux contraintes. s0 vaut 27 sur
une grille 27x27 : la tuile de focus fait 1/27 de l'ecran.

L'echelle descend de s0 a 1 en suivant une sigmoide (zoom_factor_S) : depart
lent sur le film de focus, acceleration au milieu, arrivee douce sur la
mosaique. Le parametre 'steepness' est ce que la ligne de commande de 2025
appelait --zoom_gamma, un nom trompeur : ce n'est pas un gamma.
"""
import cv2


def box_visible_on_canvas(box, W, H):
    """La boite deborde-t-elle encore sur l'ecran ?"""
    x0, y0, x1, y1 = box
    dx0, dy0 = max(0, x0), max(0, y0)
    dx1, dy1 = min(W, x1), min(H, y1)
    return (dx1 > dx0) and (dy1 > dy0)


def compute_focus_params(entries, focus_tile, W, H):
    """-> centre de la tuile de focus, et echelle s0 qui la met plein cadre."""
    focus_tile = max(0, min(len(entries) - 1, int(focus_tile)))
    x0, y0, x1, y1 = [int(v) for v in entries[focus_tile]["box"]]
    fx = 0.5 * (x0 + x1)
    fy = 0.5 * (y0 + y1)
    tw = max(1, x1 - x0)
    th = max(1, y1 - y0)
    s0 = max(W / float(tw), H / float(th))
    return fx, fy, float(s0)


def compute_transform_origin(entries, focus_tile, W, H, s0):
    """Le point fixe P du zoom.

    On veut  ecran = (mosaique - P) * s + P  tel que :
      - s = 1  donne l'identite (vrai pour tout P) ;
      - s = s0 amene le centre de la tuile de focus au centre de l'ecran.
    La seconde condition determine P."""
    focus_tile = max(0, min(len(entries) - 1, int(focus_tile)))
    x0, y0, x1, y1 = [int(v) for v in entries[focus_tile]["box"]]
    fx = 0.5 * (x0 + x1)
    fy = 0.5 * (y0 + y1)
    Cx = W * 0.5
    Cy = H * 0.5
    if abs(s0 - 1.0) < 1e-9:
        return 0.0, 0.0
    Px = (Cx - fx * s0) / (1.0 - s0)
    Py = (Cy - fy * s0) / (1.0 - s0)
    return float(Px), float(Py)


def apply_zoom_to_box_identity_at_1(box, Px, Py, s):
    """La boite d'une tuile, vue a l'echelle s. Identite quand s = 1."""
    x0, y0, x1, y1 = [float(v) for v in box]
    x0p = (x0 - Px) * s + Px
    y0p = (y0 - Py) * s + Py
    x1p = (x1 - Px) * s + Px
    y1p = (y1 - Py) * s + Py
    xa, xb = sorted((x0p, x1p))
    ya, yb = sorted((y0p, y1p))
    return [int(round(xa)), int(round(ya)), int(round(xb)), int(round(yb))]


def zoom_factor_S(fi, focus_idx, s0, steepness=2.0):
    """L'echelle a l'image fi : de s0 au depart a 1 sur la revelation.

    Sigmoide symetrique, exacte aux deux bouts. steepness = 1 donne une rampe
    lineaire ; au-dela, le milieu s'accelere et les extremites s'adoucissent."""
    if fi >= focus_idx or focus_idx <= 0:
        return 1.0
    t = max(0.0, min(1.0, fi / float(focus_idx)))
    a = max(1.0, float(steepness))
    if t == 0.0:
        eased = 0.0
    elif t == 1.0:
        eased = 1.0
    else:
        ta = t ** a
        ua = (1.0 - t) ** a
        eased = ta / (ta + ua)
    return 1.0 + (s0 - 1.0) * (1.0 - eased)


def paste_tile(canvas, patch, box):
    """Colle une imagette dans la toile, en la rognant sur les bords."""
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
    sx0 = max(0, min(pw, sx0))
    sx1 = max(0, min(pw, sx1))
    sy0 = max(0, min(ph, sy0))
    sy1 = max(0, min(ph, sy1))
    if sx1 <= sx0 or sy1 <= sy0:
        return
    canvas[dy0:dy1, dx0:dx1] = patch[sy0:sy1, sx0:sx1]


def crop_resize_fill(img, tw, th, variant="center"):
    """Recadre au format de la tuile, puis redimensionne. Sans deformation.

    C'est LA convention de cadrage du projet : banque_vignettes.recadrer en
    applique exactement la meme, pour que la recherche note ce que le rendu
    affichera. Si l'une change, l'autre doit changer avec elle."""
    sh, sw = img.shape[:2]
    tgt_aspect = max(1, tw) / float(max(1, th))
    src_aspect = sw / float(sh) if sh else 1.0
    if src_aspect > tgt_aspect:
        new_w = max(1, min(sw, int(round(sh * tgt_aspect))))
        if variant == "x0":
            x0 = 0
        elif variant == "x2":
            x0 = sw - new_w
        else:
            x0 = (sw - new_w) // 2
        x0 = max(0, min(sw - new_w, x0))
        img = img[:, x0:x0 + new_w]
    else:
        new_h = int(round(sw / tgt_aspect)) if tgt_aspect > 0 else sh
        new_h = max(1, min(sh, new_h))
        if variant == "y0":
            y0 = 0
        elif variant == "y2":
            y0 = sh - new_h
        else:
            y0 = (sh - new_h) // 2
        y0 = max(0, min(sh - new_h, y0))
        img = img[y0:y0 + new_h, :]
    return cv2.resize(img, (max(1, tw), max(1, th)), interpolation=cv2.INTER_AREA)
