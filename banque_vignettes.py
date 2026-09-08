#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Construit la banque de vignettes candidates, a partir des planches contact
deja produites par visionnages01.

visionnages01 a decode une fois les 441 Go du corpus et en a tire, par film,
une planche contact de 90 vignettes (data/frames/<id>.jpg). Ca fait environ
75 000 images deja sur le disque. Les relire coute quelques minutes, la ou
retourner chercher des images au hasard dans les films coute des heures.

Cette banque remplace l'echantillonnage aleatoire de mosaic_from_videos.py par
une recherche EXHAUSTIVE : au lieu d'esperer tomber sur une bonne image, on les
a toutes.

Trois fichiers sont ecrits dans data/ :

  banque.npy        (N, 768) float32   la vignette reduite en 16x16 RGB
  banque_vivacite.npy  (N,)  float32   de combien l'image CHANGE juste avant
  banque_meta.json                     les films, dans l'ordre des vignettes

Le cadrage reproduit celui du rendu : chaque vignette est recadree au centre
au format de la tuile de mosaique, puis reduite -- exactement ce que fera
crop_resize_fill(). L'ancien chercheur, lui, ecrasait l'image entiere dans un
carre de 16x16, si bien qu'il notait un cadrage et en affichait un autre.

'vivacite' sert a departager : 514 des 729 tuiles du logo sont noires, donc des
milliers de vignettes leur conviennent a egalite. Autant prendre, parmi elles,
celles qui viennent de bouger -- un fondu, une coupe, une sortie de plan. Le
fond du logo s'anime alors pendant le dezoom au lieu d'etre un aplat mort, et
se referme au noir pile sur la revelation.

  python banque_vignettes.py
  python banque_vignettes.py --force        # reconstruit meme si a jour
"""
import argparse
import io
import json
import os
import sys
from concurrent.futures import ThreadPoolExecutor

import numpy as np
from PIL import Image

from config import CFG

COLS, LIGNES = 10, 9
VIGN = COLS * LIGNES
RED = 16                    # cote de la vignette reduite (16x16x3 = 768 dims)
ECHANT = VIGN + 5           # 06_proxys.py echantillonne a (90+5)/duree images/s
LEAD_S = 5.0                # duree du dezoom : ce qui joue AVANT l'image retenue
LEAD_MAX = 20               # plafond, en vignettes


def dossier_data():
    d = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
    os.makedirs(d, exist_ok=True)
    return d


def films():
    """Les films de visionnages01 qui ont une planche ET sont dans le corpus.

    Les COPIES sont ecartees. Un meme film est souvent range dans plusieurs
    sessions -- la projection d'origine, une retrospective, un dossier
    '(a trier)'. Ce sont des fichiers differents, mais un seul film : les
    laisser entrer donnerait a chacun son quota de tuiles, et la mosaique
    repeterait la meme image. visionnages01 les a deja reperes et designe une
    copie de reference (colonne 'doublon_de', cf. son 18_doublons.py)."""
    v = CFG.path("visionnages")
    corpus = CFG.path("corpus")
    frames = os.path.join(v, "data", "frames")
    out, copies = [], 0
    for ligne in io.open(os.path.join(v, "index.jsonl"), encoding="utf-8"):
        ligne = ligne.strip()
        if not ligne:
            continue
        r = json.loads(ligne)
        if not r.get("duree_s") or not r.get("rel"):
            continue
        planche = os.path.join(frames, r["id"] + ".jpg")
        if not os.path.isfile(planche) or not os.path.isfile(os.path.join(corpus, r["rel"])):
            continue
        if r.get("doublon_de"):
            copies += 1
            continue
        out.append({"id": r["id"], "rel": r["rel"], "duree_s": r["duree_s"],
                    "fps": r.get("fps"), "planche": planche,
                    "titre": r.get("titre") or r.get("filename")})
    if copies:
        print("%d copies surnumeraires ecartees (meme film range dans plusieurs "
              "sessions)" % copies)
    return out


def recadrer(v, ratio):
    """Recadrage centre au format demande, comme le fera crop_resize_fill()."""
    h, w = v.shape[:2]
    if w / float(h) > ratio:
        nw = max(1, min(w, int(round(h * ratio))))
        x = (w - nw) // 2
        return v[:, x:x + nw]
    nh = max(1, min(h, int(round(w / ratio))))
    y = (h - nh) // 2
    return v[y:y + nh, :]


def traiter(f, ratio):
    """-> (90, 768) float32 reduit, (90,) float32 vivacite"""
    im = Image.open(f["planche"]).convert("RGB")
    a = np.asarray(im, dtype=np.uint8)
    H, W = a.shape[0] // LIGNES, a.shape[1] // COLS

    red = np.empty((VIGN, RED, RED, 3), dtype=np.float32)
    for i in range(VIGN):
        r, c = divmod(i, COLS)
        v = a[r * H:(r + 1) * H, c * W:(c + 1) * W]
        v = recadrer(v, ratio)
        red[i] = np.asarray(
            Image.fromarray(v).resize((RED, RED), Image.BILINEAR), dtype=np.float32)

    # De combien l'image change-t-elle pendant les LEAD_S secondes qui precedent ?
    # L'ecart des vignettes est en pixels reduits : c'est grossier, mais on ne
    # cherche qu'a classer, pas a mesurer.
    pas = f["duree_s"] / float(ECHANT)                 # secondes par vignette
    nb = int(max(1, min(LEAD_MAX, round(LEAD_S / pas))))
    viv = np.zeros(VIGN, dtype=np.float32)
    for i in range(VIGN):
        j0 = max(0, i - nb)
        if j0 == i:
            continue
        d = red[j0:i] - red[i]
        viv[i] = float(np.sqrt((d * d).mean()))
    return red.reshape(VIGN, -1), viv


def signatures(banque, n_films):
    """Un resume compact par film : ses 90 vignettes en 4x4.

    Deux fichiers du meme film ont des vignettes qui S'ALIGNENT : l'echantillon
    i est au meme endroit relatif du film dans les deux cas. Comparer les
    sequences terme a terme est donc un test tres sur, la ou comparer des
    moyennes confondrait deux films sombres."""
    a = banque.reshape(n_films, VIGN, RED, RED, 3)
    # 16x16 -> 4x4 par moyenne de blocs : assez pour reconnaitre, trop grossier
    # pour se laisser abuser par un reencodage
    a = a.reshape(n_films, VIGN, 4, RED // 4, 4, RED // 4, 3).mean(axis=(3, 5))
    return a.reshape(n_films, -1)


def jumeaux(banque, fs, seuil):
    """Groupes de films visuellement identiques -> indices a ecarter.

    visionnages01 repere les copies par la taille, la duree et la transcription.
    Ca laisse passer les REENCODAGES : meme film, autre resolution, autre poids,
    duree a la seconde pres. Ils se voient en revanche tout de suite ici."""
    S = signatures(banque, len(fs))
    n2 = (S * S).sum(1)
    D = (n2[:, None] + n2[None, :] - 2.0 * (S @ S.T)) / S.shape[1]
    np.maximum(D, 0.0, out=D)
    np.fill_diagonal(D, np.inf)
    x = np.sort(D[np.triu(np.ones(D.shape, dtype=bool), 1)])
    print("\necarts entre films : les 12 plus faibles  %s"
          % "  ".join("%.0f" % v for v in x[:12]))
    print("                     p1 %.0f   p10 %.0f   median %.0f"
          % (x[len(x) // 100], x[len(x) // 10], x[len(x) // 2]))
    parent = list(range(len(fs)))

    def trouve(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    # np.triu METTRAIT A ZERO le triangle inferieur, donc sous n'importe quel
    # seuil : il faut un masque booleen, pas une mise a zero.
    haut = np.triu(np.ones(D.shape, dtype=bool), 1)
    paires = np.argwhere((D < seuil) & haut)
    for i, j in paires:
        a, b = trouve(int(i)), trouve(int(j))
        if a != b:
            parent[a] = b
    groupes = {}
    for i in range(len(fs)):
        groupes.setdefault(trouve(i), []).append(i)
    ecarter = []
    for g in groupes.values():
        if len(g) < 2:
            continue
        # l'index de visionnages01 est trie par date : le premier est la
        # projection d'origine, c'est lui qu'on garde
        for i in sorted(g)[1:]:
            ecarter.append(i)
    return sorted(ecarter), [g for g in groupes.values() if len(g) > 1], D


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument("--seuil_jumeaux", type=float, default=150.0,
                    help="en deca de cet ecart entre leurs 90 vignettes, deux "
                         "fichiers sont juges etre le meme film")
    args = ap.parse_args()

    data = dossier_data()
    f_npy = os.path.join(data, "banque.npy")
    f_viv = os.path.join(data, "banque_vivacite.npy")
    f_meta = os.path.join(data, "banque_meta.json")
    if not args.force and all(os.path.exists(p) for p in (f_npy, f_viv, f_meta)):
        m = json.load(io.open(f_meta, encoding="utf-8"))
        sys.exit("banque deja construite : %d films, %d vignettes\n"
                 "  --force pour la reconstruire"
                 % (len(m["films"]), len(m["films"]) * VIGN))

    gw, gh = CFG.ints("grid", "27 27")
    W, H = int(CFG.get("width", "1920")), int(CFG.get("height", "1080"))
    ratio = (W // gw) / float(H // gh)
    fs = films()
    if not fs:
        sys.exit("aucun film exploitable : verifie les cles 'visionnages' et "
                 "'corpus' de config.txt")
    print("planches : %d films  ->  %d vignettes candidates" % (len(fs), len(fs) * VIGN))
    print("cadrage  : centre, au format de la tuile %d x %d (ratio %.3f)\n"
          % (W // gw, H // gh, ratio), flush=True)

    banque = np.empty((len(fs) * VIGN, RED * RED * 3), dtype=np.float32)
    vivac = np.empty(len(fs) * VIGN, dtype=np.float32)
    with ThreadPoolExecutor(max_workers=args.workers) as ex:
        for n, (f, (red, viv)) in enumerate(
                zip(fs, ex.map(lambda f: traiter(f, ratio), fs))):
            banque[n * VIGN:(n + 1) * VIGN] = red
            vivac[n * VIGN:(n + 1) * VIGN] = viv
            if (n + 1) % 100 == 0:
                print("  %d/%d" % (n + 1, len(fs)), flush=True)

    ecarter, groupes, D = jumeaux(banque, fs, args.seuil_jumeaux)
    if groupes:
        print("\n%d films jumeaux reperes (reencodages que visionnages01 ne "
              "voyait pas), %d fichiers ecartes :" % (len(groupes), len(ecarter)))
        for g in sorted(groupes, key=len, reverse=True)[:12]:
            g = sorted(g)
            print("   garde   %s" % fs[g[0]]["rel"][:78])
            for i in g[1:]:
                print("   ecarte  %s   (ecart %.0f)"
                      % (fs[i]["rel"][:78], D[g[0], i]))
    if ecarter:
        garde = np.ones(len(fs), dtype=bool)
        garde[ecarter] = False
        masque = np.repeat(garde, VIGN)
        banque = banque[masque]
        vivac = vivac[masque]
        fs = [f for f, k in zip(fs, garde) if k]
        print("\nbanque ramenee a %d films" % len(fs))

    np.save(f_npy, banque)
    np.save(f_viv, vivac)
    json.dump({"vignettes_par_film": VIGN, "echantillonnage": ECHANT,
               "reduction": RED, "ratio_tuile": ratio,
               "films": [{k: f[k] for k in ("id", "rel", "duree_s", "fps", "titre")}
                         for f in fs]},
              io.open(f_meta, "w", encoding="utf-8"), ensure_ascii=False)
    print("\nok : %s  %s  (%.0f Mo)"
          % (os.path.basename(f_npy), banque.shape, banque.nbytes / 1e6))
    print("     vivacite mediane %.1f, max %.1f"
          % (float(np.median(vivac)), float(vivac.max())))


if __name__ == "__main__":
    main()
