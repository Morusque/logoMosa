#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Repointe un fichier de matches sur le corpus tel qu'il est monte aujourd'hui.

Les matches stockaient un chemin ABSOLU par tuile. Des que le disque change de
lettre ou qu'un dossier de session est renomme, tout le fichier est mort et
aucun rendu n'est possible.

Ce script fait deux choses :

  1. il retrouve chaque film, par trois strategies de plus en plus larges ;
  2. il ecrit a cote un champ 'rel', chemin RELATIF a la racine du corpus.

C'est le point 2 qui compte : une fois 'rel' present, un changement de lettre
ne se repare plus, il se declare dans config.txt. Le champ 'video' reste
renseigne avec le chemin absolu du montage courant, pour que les scripts qui
ne connaissent que lui continuent de marcher.

Strategies, de la plus sure a la plus lache :

  1. racine        <ancienne racine>/<rel> -> <corpus>/<rel>, garde si le fichier est la
  2. nom unique    ce nom de fichier n'existe qu'une fois sous le corpus
  3. suffixe       plusieurs candidats portent ce nom : on garde celui dont la
                   fin de chemin concorde le mieux avec l'original

Ce qui ne resout pas est LAISSE TEL QUEL, jamais vide : un chemin perime dit
encore quel film avait ete choisi, et le rendu se contente de sauter la tuile.

  python remap_matches.py --dry-run       # rapport seul, n'ecrit rien
  python remap_matches.py                 # reecrit, apres un .bak
  python remap_matches.py --verify 40     # decode 40 images pour prouver le seek
"""

# ce script vit dans outils/ : config.py est un cran au-dessus
import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))

import argparse
import json
import os
import shutil
import sys
from collections import defaultdict
from typing import Dict, List, Optional, Tuple

from config import CFG

VIDEO_EXTS = {".mp4", ".mov", ".m4v", ".avi", ".mpg", ".mpeg", ".wmv", ".mkv", ".webm"}
# racines connues des anciens fichiers de matches, essayees dans l'ordre
ANCIENNES = ["G:\\Kino\\mtp", "G:/Kino/mtp", "D:\\project\\current\\logoMosa"]


def index_par_nom(root: str) -> Dict[str, List[str]]:
    """-> {nom de fichier en minuscules: [chemins complets]}"""
    out: Dict[str, List[str]] = defaultdict(list)
    for dirpath, _, filenames in os.walk(root):
        for fn in filenames:
            if os.path.splitext(fn)[1].lower() in VIDEO_EXTS:
                out[fn.lower()].append(os.path.join(dirpath, fn))
    return out


def composants(p: str) -> List[str]:
    return [c for c in p.replace("\\", "/").lower().split("/") if c]


def suffixe_commun(a: str, b: str) -> int:
    """Nombre de composants de chemin communs en partant de la fin."""
    pa, pb = composants(a), composants(b)
    n = 0
    while n < min(len(pa), len(pb)) and pa[-1 - n] == pb[-1 - n]:
        n += 1
    return n


def sous_corpus(chemin: str, corpus: str) -> Optional[str]:
    """Chemin relatif au corpus, en '/', ou None si le chemin est ailleurs."""
    try:
        rel = os.path.relpath(chemin, corpus)
    except ValueError:          # autre disque
        return None
    return None if rel.startswith("..") else rel.replace("\\", "/")


def resoudre(ancien: str, corpus: str,
             par_nom: Dict[str, List[str]]) -> Tuple[Optional[str], str]:
    """-> (chemin absolu sous le corpus ou None, strategie qui a repondu)"""
    for racine in ANCIENNES + [corpus]:
        pref = racine.rstrip("\\/") + os.sep
        if ancien.lower().replace("/", os.sep).startswith(pref.lower()):
            reste = ancien.replace("/", os.sep)[len(pref):]
            cand = os.path.join(corpus, reste)
            if os.path.isfile(cand):
                return cand, "racine"
            break
    if os.path.isfile(ancien) and sous_corpus(ancien, corpus):
        return ancien, "deja bon"

    cands = par_nom.get(os.path.basename(ancien.replace("\\", "/")).lower(), [])
    if len(cands) == 1:
        return cands[0], "nom unique"
    if len(cands) > 1:
        return max(cands, key=lambda c: suffixe_commun(ancien, c)), "suffixe"
    return None, "introuvable"


def lisible(chemin: str, frame_idx: Optional[int]) -> bool:
    import cv2
    cap = cv2.VideoCapture(chemin)
    if not cap.isOpened():
        return False
    if isinstance(frame_idx, int):
        cap.set(cv2.CAP_PROP_POS_FRAMES, max(0, frame_idx))
    ok, fr = cap.read()
    cap.release()
    return bool(ok and fr is not None)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--matches", default=None, help="defaut : la cle 'matches' de config.txt")
    ap.add_argument("--dry-run", action="store_true", dest="dry_run")
    ap.add_argument("--verify", type=int, default=0,
                    help="decode ce nombre d'images pour prouver que le seek tombe juste")
    args = ap.parse_args()

    corpus = CFG.path("corpus")
    matches = args.matches or CFG.path("matches")
    print("corpus  : %s" % corpus)
    print("matches : %s\n" % matches)

    with open(matches, "r", encoding="utf-8") as f:
        entries = json.load(f)

    print("indexation du corpus...", flush=True)
    par_nom = index_par_nom(corpus)
    print("  %d noms de fichiers video\n" % len(par_nom))

    # Un film occupe souvent plusieurs tuiles : on ne resout chaque chemin qu'une fois.
    anciens = sorted({e["match"]["video"] for e in entries
                      if e.get("match", {}).get("video")})
    table: Dict[str, Optional[str]] = {}
    strat: Dict[str, str] = {}
    for a in anciens:
        table[a], strat[a] = resoudre(a, corpus, par_nom)

    stats: Dict[str, int] = defaultdict(int)
    for a in anciens:
        stats[strat[a]] += 1
    print("%d films distincts references" % len(anciens))
    for k in ("deja bon", "racine", "nom unique", "suffixe", "introuvable"):
        if stats[k]:
            print("  %-11s %4d" % (k, stats[k]))

    for label in ("suffixe", "introuvable"):
        montre = [a for a in anciens if strat[a] == label]
        if montre:
            print("\n%s :" % label.upper())
            for a in montre:
                print("   %s" % a.replace("\\", "/").split("/", 3)[-1])
                if table[a]:
                    print("      -> %s" % sous_corpus(table[a], corpus))

    n_tuiles = sum(1 for e in entries
                   if table.get(e.get("match", {}).get("video")) is not None)
    print("\ntuiles rejouables : %d / %d" % (n_tuiles, len(entries)))

    if args.verify:
        import random
        ok = [a for a in anciens if table[a]]
        random.shuffle(ok)
        idx_par_film: Dict[str, int] = {}
        for e in entries:
            m = e.get("match", {})
            v = m.get("video")
            if v and v not in idx_par_film and isinstance(m.get("frame_idx"), int):
                idx_par_film[v] = m["frame_idx"]
        bons = mauvais = 0
        print("\nverification par decodage de %d films..." % min(args.verify, len(ok)),
              flush=True)
        for a in ok[: args.verify]:
            if lisible(table[a], idx_par_film.get(a)):
                bons += 1
            else:
                mauvais += 1
                print("   ILLISIBLE %s" % sous_corpus(table[a], corpus))
        print("  %d lisibles, %d en echec" % (bons, mauvais))

    if args.dry_run:
        print("\n--dry-run : rien n'a ete ecrit")
        return

    bak = matches + ".bak"
    if not os.path.exists(bak):
        shutil.copy2(matches, bak)
        print("\nsauvegarde : %s" % os.path.basename(bak))
    n = n_rel = 0
    for e in entries:
        m = e.get("match", {})
        v = m.get("video")
        if not v:
            continue
        neuf = table.get(v)
        if neuf:
            m["video"] = os.path.normpath(neuf)
            n += 1
        rel = sous_corpus(m["video"], corpus)
        if rel:
            m["rel"] = rel
            n_rel += 1
    tmp = matches + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(entries, f, ensure_ascii=False, indent=2)
    os.replace(tmp, matches)
    print("%s : %d tuiles repointees, %d avec un chemin relatif"
          % (os.path.basename(matches), n, n_rel))


if __name__ == "__main__":
    main()
