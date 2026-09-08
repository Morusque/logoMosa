#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Habille un rendu muet : son du film de focus, sfx, queue sur le logo.

La recette n'est pas inventee, elle est relevee sur les neuf clips existants
(enveloppe RMS par tranche de 0,25 s de logoMosa_01) :

    0 -> 0,5 s    une courte montee, pour ne pas demarrer sur un a-coup
    0,5 s -> pop  le son du film, a VOLUME CONSTANT
    juste avant   une descente tres courte (50 ms), qui degage la place
    le pop        l'accent du sfx tombe sur la revelation
    apres         le logo propre, puis le noir, en silence

Le son du film ne monte PAS pendant le clip : il tient son niveau et se retire
au dernier moment, pour que l'accent tombe dans le vide. C'est le retrait qui
fait l'effet, pas un crescendo -- et plus il est tardif, plus il claque.

L'instant de l'accent du sfx n'est pas code en dur : on le detecte dans le
fichier (maximum de l'enveloppe) et on le cale sur la revelation. Changer de
sfx ne demande donc rien d'autre que de changer le fichier.

Ce n'est qu'un DEFAUT raisonnable : tes neuf clips avaient chacun un son
decide a la main. Les reglages sont la pour etre bouscules.

  python son_logo.py out_mosaic/logo_tuile0364.mp4 --focus 364
"""
import argparse
import io
import json
import os
import subprocess
import sys

import numpy as np

from config import CFG

HERE = os.path.dirname(os.path.abspath(__file__))


def a_du_son(chemin):
    p = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "a:0",
                        "-show_entries", "stream=codec_type", "-of",
                        "default=nw=1:nk=1", chemin], capture_output=True)
    return b"audio" in (p.stdout or b"")


def instant_accent(chemin, sr=8000, fenetre=0.02):
    """Ou tombe l'accent du sfx ? -> secondes depuis le debut du fichier."""
    p = subprocess.run(["ffmpeg", "-v", "error", "-i", chemin, "-ac", "1",
                        "-ar", str(sr), "-f", "f32le", "-"], capture_output=True)
    a = np.frombuffer(p.stdout, dtype=np.float32)
    if a.size == 0:
        return None
    n = max(1, int(fenetre * sr))
    m = a.size // n
    if m == 0:
        return 0.0
    rms = np.sqrt((a[:m * n].astype(np.float64) ** 2).reshape(m, n).mean(1))
    return float(np.argmax(rms) * n) / sr


def duree(chemin):
    p = subprocess.run(["ffprobe", "-v", "error", "-show_entries",
                        "format=duration", "-of", "default=nw=1:nk=1", chemin],
                       capture_output=True)
    try:
        return float((p.stdout or b"0").decode().strip())
    except ValueError:
        return 0.0


def habiller(muet, match, sortie, fps, revelation, montee=0.5, descente=0.05,
             marge=0.03, gain_film=1.0, gain_sfx=1.0, sfx=None, corpus=None,
             duree_totale=None, limite=300):
    """Pose le son sur une video DEJA complete (dezoom, pop, logo, noir).

    Toute l image est faite par rendre_logo.py. Ici on ne touche qu au son :
    le flux video est recopie tel quel, sans reencodage."""
    corpus = corpus or CFG.path("corpus")
    sfx = sfx or CFG.path("sfx")
    # La duree est fournie par l appelant, qui sait combien d images il a
    # ecrites. On ne la sonde qu en dernier recours (usage en ligne de
    # commande) : une sonde qui repond de travers laisse 'apad' padder du
    # silence sans fin, et le mux ecrit des minutes d audio pour rien.
    duree_video = duree_totale if duree_totale else duree(muet)
    if not duree_video or duree_video <= 0 or duree_video > 600:
        sys.exit("duree du clip inexploitable (%r) : refus de muxer" % duree_video)

    pic = instant_accent(sfx)
    if pic is None:
        sys.exit("sfx illisible : %s" % sfx)
    # caler l'accent sur la revelation
    retard = revelation - pic

    film = os.path.join(corpus, match["rel"]) if match.get("rel") else match.get("video")
    # le son du film part au meme endroit que l'image
    t_film = float(match.get("t") or 0.0) - revelation
    avec_film = bool(film and os.path.isfile(film) and a_du_son(film))

    entrees = ["-i", muet, "-i", sfx]
    idx_sfx = 1
    if avec_film:
        # borner la lecture : seules les premieres secondes servent
        entrees += ["-ss", "%.4f" % max(0.0, t_film),
                    "-t", "%.4f" % (revelation + 1.0), "-i", film]
        idx_film = 2

    # L'image est deja entierement faite par rendre_logo.py, pop compris :
    # ici on n'ecrit que des filtres audio, et le flux video est recopie.
    fc = []
    pistes = []
    if avec_film:
        d = revelation
        # une courte montee pour ne pas demarrer sur un a-coup, puis le niveau
        # tenu, puis une descente serree qui s'acheve juste AVANT le pop
        debut_descente = max(0.0, d - marge - descente)
        fc.append("[%d:a]aformat=sample_fmts=fltp:sample_rates=48000:"
                  "channel_layouts=stereo,atrim=duration=%.4f,asetpts=N/SR/TB,"
                  "afade=t=in:st=0:d=%.4f,afade=t=out:st=%.4f:d=%.4f,"
                  "volume=%.3f[af]"
                  % (idx_film, d, min(montee, debut_descente), debut_descente,
                     descente, gain_film))
        pistes.append("[af]")
    # l'accent, cale sur la revelation
    if retard >= 0:
        fc.append("[%d:a]aformat=sample_fmts=fltp:sample_rates=48000:"
                  "channel_layouts=stereo,adelay=%d|%d,volume=%.3f[ax]"
                  % (idx_sfx, int(retard * 1000), int(retard * 1000), gain_sfx))
    else:
        fc.append("[%d:a]aformat=sample_fmts=fltp:sample_rates=48000:"
                  "channel_layouts=stereo,atrim=start=%.4f,asetpts=N/SR/TB,"
                  "volume=%.3f[ax]" % (idx_sfx, -retard, gain_sfx))
    pistes.append("[ax]")
    duree_totale = duree_video
    if len(pistes) == 2:
        fc.append("%s%samix=inputs=2:normalize=0:dropout_transition=0,"
                  "apad,atrim=duration=%.4f[a]" % (pistes[0], pistes[1], duree_totale))
    else:
        fc.append("%sapad,atrim=duration=%.4f[a]" % (pistes[0], duree_totale))

    cmd = (["ffmpeg", "-v", "error", "-y"] + entrees +
           ["-filter_complex", ";".join(fc), "-map", "0:v", "-map", "[a]",
            "-c:v", "copy", "-c:a", "aac", "-b:a", "192k",
            "-t", "%.4f" % duree_totale, sortie])
    try:
        p = subprocess.run(cmd, capture_output=True, timeout=limite)
    except subprocess.TimeoutExpired:
        if os.path.exists(sortie):
            os.unlink(sortie)
        sys.exit("le mux a depasse %d s : abandon de cette tuile" % limite)
    if p.returncode != 0:
        sys.exit("ffmpeg :\n%s" % p.stderr.decode("utf-8", "replace")[-1500:])
    print("  son : %s, accent du sfx a %.2f s cale sur la revelation (%.2f s)"
          % ("film + sfx" if avec_film else "sfx seul (film muet)", pic, revelation))
    if avec_film:
        print("        film : montee %.2f s, niveau tenu, descente %.2f s "
              "achevee a %.2f s" % (montee, descente, revelation - marge))
    print("  duree : %.2f s" % duree_totale)
    return sortie


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("muet", help="le rendu sans son")
    ap.add_argument("--focus", type=int, required=True)
    ap.add_argument("--matches", default=None)
    ap.add_argument("--sortie", default=None)
    ap.add_argument("--montee", type=float, default=0.5,
                    help="fondu d entree du son du film, au tout debut")
    ap.add_argument("--descente", type=float, default=0.05,
                    help="duree du retrait du son du film, juste avant le pop")
    ap.add_argument("--marge", type=float, default=0.03,
                    help="silence menage entre la fin de la descente et le pop")
    ap.add_argument("--gain_film", type=float, default=1.0)
    ap.add_argument("--gain_sfx", type=float, default=1.0)
    args = ap.parse_args()

    fps = int(CFG.get("fps", "20"))
    pre_roll = int(CFG.get("pre_roll", "100"))
    entrees = json.load(io.open(args.matches or CFG.path("matches"), encoding="utf-8"))
    sortie = args.sortie or os.path.splitext(args.muet)[0] + "_son.mp4"
    habiller(args.muet, entrees[args.focus]["match"], sortie, fps,
             pre_roll / float(fps), montee=args.montee,
             descente=args.descente, marge=args.marge,
             gain_film=args.gain_film, gain_sfx=args.gain_sfx)
    print("-> %s" % sortie)


if __name__ == "__main__":
    main()
