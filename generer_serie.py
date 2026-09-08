#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Genere une serie de logos, dans un ordre aleatoire et sans remise.

  python generer_serie.py                 # toutes les tuiles convenables
  python generer_serie.py --combien 20    # seulement 20
  python generer_serie.py --graine 7      # meme tirage qu'une fois precedente

INTERRUPTIBLE A TOUT MOMENT : Ctrl-C, ou eteindre la machine. Chaque clip est
ecrit entierement avant qu'on passe au suivant, et relancer la meme commande
reprend ou on en etait -- les clips deja faits sont sautes, et le tirage se
poursuit sur ce qui reste.

Le cache haute definition est propre a chaque tuile de focus et pese 90 a
185 Mo. On le supprime donc apres chaque clip : sur 583 tuiles il occuperait
autrement une soixantaine de Go. --garder_hd si tu comptes refaire les memes
tuiles (un second rendu est alors plus rapide de ~20 s).
"""
import argparse
import io
import json
import os
import random
import shutil
import subprocess
import sys
import time

from config import CFG

HERE = os.path.dirname(os.path.abspath(__file__))


def hms(s):
    s = int(max(0, s))
    return "%dh%02d" % (s // 3600, s % 3600 // 60) if s >= 3600 else "%d min" % (s // 60)


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--combien", type=int, default=None,
                    help="nombre de clips ; par defaut, toutes les tuiles convenables")
    ap.add_argument("--graine", type=int, default=None)
    ap.add_argument("--dossier", default=None, help="defaut : out_mosaic/logos")
    ap.add_argument("--tout_accepter", action="store_true",
                    help="ne pas ecarter les ouvertures sur un carton")
    ap.add_argument("--garder_hd", action="store_true")
    ap.add_argument("--muet", action="store_true", help="sans la passe de son")
    ap.add_argument("--limite", type=int, default=420,
                    help="secondes au-dela desquelles une tuile est abandonnee. "
                         "Un rendu normal en prend 50 a 100")
    args = ap.parse_args()

    out_dir = CFG.path("out_dir", doit_exister=False)
    dossier = args.dossier or os.path.join(out_dir, "logos")
    os.makedirs(dossier, exist_ok=True)
    cache = os.path.join(HERE, "data", "cache")

    entrees = json.load(io.open(CFG.path("matches"), encoding="utf-8"))
    manif = json.load(io.open(os.path.join(cache, "manifeste.json"), encoding="utf-8"))
    jouables = sorted(int(k) for k in manif["images"])

    if args.tout_accepter:
        choix = jouables
    else:
        from ouvertures import convenables, mesures
        bons = set(convenables(mesures(cache)))
        choix = [i for i in jouables if i in bons]
    print("%d tuiles jouables, %d avec une ouverture convenable"
          % (len(jouables), len(choix)))

    # tirage sans remise
    random.seed(args.graine)
    random.shuffle(choix)
    if args.combien:
        choix = choix[: args.combien]

    faits = [i for i in choix
             if os.path.exists(os.path.join(dossier, "logo_tuile%04d.mp4" % i))]
    reste = [i for i in choix if i not in set(faits)]
    print("%d deja rendus, %d a faire" % (len(faits), len(reste)))
    if not reste:
        print("rien a faire")
        return
    print("dossier : %s\n" % dossier)

    # les .muet.mp4 d'une passe interrompue ne servent plus a rien
    for f in os.listdir(dossier):
        if f.endswith(".muet.mp4"):
            os.unlink(os.path.join(dossier, f))

    durees = []
    debut = time.time()
    try:
        for n, i in enumerate(reste, 1):
            t0 = time.time()
            sortie = os.path.join(dossier, "logo_tuile%04d.mp4" % i)
            cmd = [sys.executable, os.path.join(HERE, "rendre_logo.py"),
                   "--focus", str(i), "--sortie", sortie]
            if not args.muet:
                cmd.append("--son")
            env = dict(os.environ, PYTHONIOENCODING="utf-8")
            # Une tuile qui s emballe ne doit couter qu elle-meme. Sans cette
            # limite, un seul mux parti en vrille a gele la serie 20 minutes
            # avant qu on s en apercoive.
            depasse = False
            try:
                p = subprocess.run(cmd, capture_output=True, cwd=HERE, env=env,
                                   timeout=args.limite)
            except subprocess.TimeoutExpired as e:
                depasse, p = True, e
            ok = (not depasse) and p.returncode == 0 and os.path.exists(sortie)
            if depasse:
                for f in (sortie, sortie + ".muet.mp4"):
                    if os.path.exists(f):
                        os.unlink(f)
            d = time.time() - t0
            if ok:
                durees.append(d)
            if not args.garder_hd:
                shutil.rmtree(os.path.join(HERE, "data", "cache_hd",
                                           "tuile%04d" % i), ignore_errors=True)
            moy = sum(durees) / len(durees) if durees else d
            print("[%d/%d] tuile %-4d %-4s %5.0f s   reste ~%s"
                  % (n, len(reste), i,
                     "ok" if ok else ("DEPASSE" if depasse else "ECHEC"), d,
                     hms(moy * (len(reste) - n))), flush=True)
            if not ok and not depasse:
                err = (p.stderr or b"").decode("utf-8", "replace").strip().splitlines()
                print("        %s" % (err[-1][:150] if err else "(sans message)"))
    except KeyboardInterrupt:
        print("\ninterrompu -- relance la meme commande pour reprendre")
    finally:
        n = len([f for f in os.listdir(dossier) if f.startswith("logo_tuile")
                 and f.endswith(".mp4")])
        print("\n%d clips dans %s  (%s ecoulees)"
              % (n, dossier, hms(time.time() - debut)))


if __name__ == "__main__":
    main()
