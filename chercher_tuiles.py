#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Choisit l'image de chaque tuile de la mosaique, par recherche EXHAUSTIVE.

mosaic_from_videos.py tirait des images au hasard et gardait celles qui
amelioraient : glouton, sans critere d'arret, et il n'a jamais touche que 452
films sur 837. Ici on compare les 729 tuiles aux 75 000 vignettes de la banque,
d'un coup, et on prend le meilleur decoupage possible. Quelques secondes.

Trois differences de fond avec l'ancien chercheur :

  - EXHAUSTIF      toutes les vignettes de tous les films sont vues
  - OPTIMAL        l'affectation minimise la somme des ecarts sous la
                   contrainte 'au plus K tuiles par film' (Kuhn-Munkres),
                   au lieu d'accepter les ameliorations dans l'ordre du hasard
  - MEME CADRAGE   on note ce que le rendu affichera vraiment (recadrage
                   centre au format de la tuile), pas l'image entiere ecrasee

Et un depart : parmi les milliers de vignettes qui conviennent a egalite aux
514 tuiles noires du logo, on prefere celles qui viennent de BOUGER, pour que
le fond s'anime pendant le dezoom (voir --vivacite).

  python chercher_tuiles.py                          # -> out_mosaic/matches_exhaustif.json
  python chercher_tuiles.py --max_par_film 3
  python chercher_tuiles.py --vivacite 0             # depart neutre
  python chercher_tuiles.py --sortie out_mosaic/matches_pass.json --recaler

L'ancien matches_pass.json n'est PAS touche par defaut : le nouveau resultat
s'ecrit a cote, pour etre compare avant d'etre adopte.
"""
import argparse
import collections
import io
import json
import os
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor

import numpy as np
from PIL import Image

from config import CFG
from banque_vignettes import RED, VIGN, ECHANT, recadrer

HERE = os.path.dirname(os.path.abspath(__file__))


def tuiles_cible(chemin, cols, lignes):
    """Le logo decoupe en cols x lignes -> (boites, vecteurs reduits).

    Meme decoupage que mosaic_from_videos.tiles_from_target : la derniere
    colonne et la derniere ligne absorbent le reste de la division."""
    im = Image.open(chemin).convert("RGB")
    W, H = im.size
    a = np.asarray(im, dtype=np.float32)
    tw, th = W // cols, H // lignes
    boites, vecs = [], []
    for r in range(lignes):
        for c in range(cols):
            x0, y0 = c * tw, r * th
            x1 = (c + 1) * tw if c < cols - 1 else W
            y1 = (r + 1) * th if r < lignes - 1 else H
            boites.append([x0, y0, x1, y1])
            t = a[y0:y1, x0:x1]
            vecs.append(np.asarray(
                Image.fromarray(t.astype(np.uint8)).resize((RED, RED), Image.BILINEAR),
                dtype=np.float32).ravel())
    return boites, np.array(vecs, dtype=np.float32)


def distances(T, B):
    """Ecart quadratique moyen par pixel-canal, comme l'ancien ssd()."""
    d = (T * T).sum(1)[:, None] + (B * B).sum(1)[None, :] - 2.0 * (T @ B.T)
    np.maximum(d, 0.0, out=d)
    d /= T.shape[1]
    return d


def affecter(cout, n_films, k):
    """Au plus k tuiles par film, somme des couts minimale.

    On resume chaque film a ses k meilleures vignettes pour la tuile
    consideree, ce qui ramene le probleme a une affectation classique entre
    729 tuiles et n_films * k places."""
    n_t = cout.shape[0]
    c3 = cout.reshape(n_t, n_films, VIGN)
    ordre = np.argsort(c3, axis=2)[:, :, :k]                    # (n_t, n_films, k)
    meilleurs = np.take_along_axis(c3, ordre, axis=2)           # (n_t, n_films, k)
    C = meilleurs.reshape(n_t, n_films * k)
    try:
        from scipy.optimize import linear_sum_assignment
    except ImportError:
        print("  scipy absent : repli sur une affectation gloutonne", flush=True)
        return _glouton(C, ordre, n_films, k)
    lignes, cols = linear_sum_assignment(C)
    film = cols // k
    slot = cols % k
    vign = ordre[lignes, film, slot]
    return lignes, film, vign


def _glouton(C, ordre, n_films, k):
    n_t = C.shape[0]
    plat = np.argsort(C, axis=None)
    pris_t = np.zeros(n_t, dtype=bool)
    reste = np.full(n_films, k, dtype=np.int32)
    lt, lf, lv = [], [], []
    for p in plat:
        t, col = divmod(int(p), C.shape[1])
        f, s = divmod(col, k)
        if pris_t[t] or reste[f] <= 0:
            continue
        pris_t[t] = True
        reste[f] -= 1
        lt.append(t)
        lf.append(f)
        lv.append(int(ordre[t, f, s]))
        if pris_t.all():
            break
    return np.array(lt), np.array(lf), np.array(lv)


def recaler(film, corpus, i_vign, vec_cible, ratio, largeur=160, n=9, etendue=1.5):
    """Affine l'instant retenu, en decodant vraiment le film autour de lui.

    Deux problemes d'un coup :

      - la banque ne connait que 90 instants par film, alors que l'ancien
        chercheur pouvait tomber n'importe ou. On recupere ici la finesse
        temporelle que la banque n'a pas.
      - t = i * duree / 95 n'est juste qu'a une vignette pres (mesure : 72 %
        a +/-1 vignette). Le recalage rend l'horodatage exact, ce dont le rendu
        a besoin pour afficher l'image qui a ete notee.

    On compare a la TUILE CIBLE, pas a la vignette : on ne cherche pas a
    retrouver la vignette, on cherche la meilleure image du voisinage.

    -> (t, ecart, imagette) ; (t predit, None, None) si l'extraction echoue.
    """
    dur = film["duree_s"]
    pas = dur / float(ECHANT)
    t0 = i_vign * pas
    a, b = max(0.0, t0 - etendue * pas), min(dur, t0 + etendue * pas)
    if b <= a:
        return t0, None, None
    chemin = os.path.join(corpus, film["rel"])
    p = subprocess.run(
        ["ffmpeg", "-v", "error", "-ss", "%.4f" % a, "-i", chemin,
         "-t", "%.4f" % (b - a), "-vf", "fps=%.4f,scale=%d:-2" % (n / (b - a), largeur),
         "-frames:v", str(n), "-f", "image2pipe", "-vcodec", "png", "-"],
        capture_output=True)
    if not p.stdout:
        return t0, None, None
    # les PNG sont concatenes dans le flux : on les separe sur leur signature
    sig = b"\x89PNG\r\n\x1a\n"
    morceaux = [sig + m for m in p.stdout.split(sig) if m]
    best = best_d = best_img = None
    for j, m in enumerate(morceaux):
        try:
            brut = np.asarray(Image.open(io.BytesIO(m)).convert("RGB"), dtype=np.uint8)
        except Exception:
            continue
        coupe = recadrer(brut, ratio)
        v = np.asarray(Image.fromarray(coupe).resize((RED, RED), Image.BILINEAR),
                       dtype=np.float32).ravel()
        d = float(((v - vec_cible) ** 2).mean())
        if best_d is None or d < best_d:
            best_d, best, best_img = d, j, coupe
    if best is None:
        return t0, None, None
    return a + (best + 0.5) * (b - a) / len(morceaux), best_d, best_img


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--cible", default=None, help="defaut : cle 'target' de config.txt")
    ap.add_argument("--sortie", default=None,
                    help="defaut : out_mosaic/matches_exhaustif.json")
    ap.add_argument("--max_par_film", type=int, default=2,
                    help="tuiles par film. Mettre 1 serre trop : il faudrait 729 "
                         "films distincts sur 801, l'affectation n'a plus de jeu "
                         "et case des generiques dans le fond noir. C'est "
                         "--seuil_doublon qui empeche les repetitions, pas ce quota")
    ap.add_argument("--seuil_doublon", type=float, default=250.0,
                    help="en deca de cet ecart, deux tuiles VISIBLES sont jugees "
                         "identiques et l'une repart. 0 desactive le controle. "
                         "Mesure : 1,7 %% des paires visibles sont sous 800")
    ap.add_argument("--facteur_voisin", type=float, default=2.0,
                    help="exigence renforcee entre tuiles adjacentes : c'est cote "
                         "a cote qu'une repetition se voit")
    ap.add_argument("--seuil_relief", type=float, default=15.0,
                    help="en deca, une tuile est un aplat : elle peut se repeter "
                         "sans que ca se voie. Ne dispense PAS de la regle "
                         "'un film ne sert qu'une fois en zone visible'")
    ap.add_argument("--vivacite", type=float, default=30.0,
                    help="depart des ex aequo : ecart tolere (en ecart quadratique) "
                         "pour prendre une image qui vient de bouger. 0 = neutre")
    ap.add_argument("--recaler", action="store_true", default=True)
    ap.add_argument("--no-recaler", dest="recaler", action="store_false")
    ap.add_argument("--essais", type=int, default=24,
                    help="reprises par tuile : une tuile dont le recalage decoit "
                         "repart sur le candidat suivant, elle seule")
    ap.add_argument("--seuil_echec", type=float, default=300.0,
                    help="au-dela de cet ecart avec ce que la banque promettait, "
                         "le recalage est juge rate")
    ap.add_argument("--apercu", nargs="?", const="AUTO", default=None,
                    help="ecrit la mosaique statique, gratuitement : le recalage "
                         "decode deja les images qu'il faudrait")
    ap.add_argument("--workers", type=int, default=6)
    args = ap.parse_args()

    corpus = CFG.path("corpus")
    cible = args.cible or CFG.path("target")
    out_dir = CFG.path("out_dir", doit_exister=False)
    sortie = args.sortie or os.path.join(out_dir, "matches_exhaustif.json")
    if args.apercu == "AUTO":
        args.apercu = os.path.splitext(sortie)[0] + "_apercu.jpg"
    cols, lignes = CFG.ints("grid", "27 27")

    data = os.path.join(HERE, "data")
    try:
        B = np.load(os.path.join(data, "banque.npy"))
        viv = np.load(os.path.join(data, "banque_vivacite.npy"))
        meta = json.load(io.open(os.path.join(data, "banque_meta.json"), encoding="utf-8"))
    except (OSError, ValueError):
        sys.exit("banque absente : lance d'abord\n  python banque_vignettes.py")
    films = meta["films"]
    print("banque : %d films, %d vignettes" % (len(films), B.shape[0]))
    print("cible  : %s  ->  %d x %d tuiles" % (os.path.basename(cible), cols, lignes),
          flush=True)

    boites, T = tuiles_cible(cible, cols, lignes)
    print("\ncalcul des %d x %d ecarts..." % (len(boites), B.shape[0]), flush=True)
    D = distances(T, B)

    Tt = T.reshape(len(boites), RED * RED, 3)
    # le fond noir du logo : la seule zone ou une repetition ne se voit pas
    sombre = (Tt.std(axis=(1, 2)) < 3.0) & (Tt.mean(axis=(1, 2)) < 8.0)
    plates = int((Tt.std(axis=(1, 2)) < 3.0).sum())
    print("  %d tuiles sur %d sont quasi uniformes (le logo est noir a %.0f %%)"
          % (plates, len(boites), 100.0 * plates / len(boites)))

    contenu_banque = (B.reshape(B.shape[0], RED * RED, 3).std(axis=(1, 2))
                      > args.seuil_relief)

    # copie : 'cout' recevra des np.inf pour bannir les candidats decevants,
    # alors que D doit rester la mesure de reference
    cout = D.copy()
    if args.vivacite > 0:
        vmax = float(viv.max()) or 1.0
        cout += args.vivacite * (1.0 - viv / vmax)[None, :]
        print("  depart des ex aequo : +%.0f max pour une image immobile"
              % args.vivacite)

    ratio = meta["ratio_tuile"]
    # cache des recalages deja payes : (tuile, candidat) -> (t, ecart reel, image)
    vus = {}

    def refiner(paires):
        """paires = [(tuile, film, vignette)] -> remplit 'vus'."""
        def tache(p):
            return recaler(films[p[1]], corpus, p[2], T[p[0]], ratio)
        with ThreadPoolExecutor(max_workers=args.workers) as ex:
            for n, (p, r) in enumerate(zip(paires, ex.map(tache, paires)), 1):
                vus[(p[0], p[1] * VIGN + p[2])] = r
                if n % 100 == 0:
                    print("    %d/%d" % (n, len(paires)), flush=True)

    print("\naffectation (au plus %d tuiles par film)..." % args.max_par_film,
          flush=True)
    i_t, i_f, i_v = affecter(cout, len(films), args.max_par_film)
    print("  %d tuiles affectees, %d films distincts"
          % (len(i_t), len(set(i_f.tolist()))))
    d_banque = D[i_t, i_f * VIGN + i_v]
    print("  ecart promis par la banque : median %.0f, moyen %.0f"
          % (np.median(d_banque), d_banque.mean()))

    attrib = {int(i_t[n]): (int(i_f[n]), int(i_v[n])) for n in range(len(i_t))}
    usage = collections.Counter(f for f, _ in attrib.values())

    def juge(tuile, f, v):
        """-> (retenu ?, t, ecart reel, image)"""
        r = vus.get((tuile, f * VIGN + v))
        if r is None or r[1] is None:
            return False, None, None, None
        t, d, img = r
        return (d <= D[tuile, f * VIGN + v] + args.seuil_echec), t, d, img

    def reduire(img):
        return np.asarray(Image.fromarray(img).resize((RED, RED), Image.BILINEAR),
                          dtype=np.float32).ravel()

    def vecteur(t, f, v):
        """Ce que la tuile affiche VRAIMENT : l'image decodee si on l'a payee,
        sinon la vignette de la banque."""
        r = vus.get((t, f * VIGN + v))
        if r is not None and r[2] is not None:
            return reduire(r[2])
        return B[f * VIGN + v]

    def sosies(attrib):
        """Tuiles a refaire parce qu'une AUTRE tuile leur ressemble trop.

        Deux films peuvent partager un carton, un generique, un plan de meme
        composition : la mosaique montre alors deux fois la meme chose, et l'oeil
        ne voit que ca. On compare les images REELLEMENT retenues, pas les
        vignettes -- c'est ce qui sera affiche qui compte.

        L'exemption porte sur la CIBLE, pas sur le contenu de la tuile : seul
        le fond noir du logo a le droit de se repeter. Juger sur le contenu
        exemptait aussi le rouge uni du lobe et le blanc uni du centre -- des
        zones bien visibles, ou les repetitions sautent aux yeux.

        Deux tuiles VISIBLES tirees du meme film sont refusees quel que soit
        leur ecart : mesure faite, quand un film sert deux fois c'est presque
        toujours le meme plan (32 paires sur 56 sous 2000, contre 3 % des
        paires en general). Le quota de 2 reste utile pour le fond, ou il
        donne a l'affectation le jeu dont elle a besoin."""
        if args.seuil_doublon <= 0:
            return set()
        ids, vecs, fits, sources = [], [], [], []
        for t in sorted(attrib):
            f, v = attrib[t]
            sources.append(f)
            r = vus.get((t, f * VIGN + v))
            ids.append(t)
            vecs.append(vecteur(t, f, v))
            fits.append(r[1] if (r is not None and r[1] is not None)
                        else float(D[t, f * VIGN + v]))
        if len(ids) < 2:
            return set()
        V = np.array(vecs)
        vu = ~sombre[np.array(ids)]              # la cible n'est pas le fond noir
        src = np.array(sources)
        n2 = (V * V).sum(1)
        E = (n2[:, None] + n2[None, :] - 2.0 * V @ V.T) / V.shape[1]
        np.maximum(E, 0.0, out=E)
        # cout d'une tuile = son propre ecart a la cible : en cas de conflit,
        # c'est la moins bien servie qui cede sa place
        fit = np.array(fits, dtype=np.float64)
        lig = np.array([t // cols for t in ids])
        col = np.array([t % cols for t in ids])
        voisin = (np.abs(lig[:, None] - lig[None, :]) <= 1) & \
                 (np.abs(col[:, None] - col[None, :]) <= 1)
        seuil = np.where(voisin, args.seuil_doublon * args.facteur_voisin,
                         args.seuil_doublon)
        # Deux regles, pour deux problemes differents :
        #
        #  - MEME FILM, deux tuiles visibles : refus quel que soit l'ecart.
        #    C'est de la que venaient la plupart des repetitions reperees a
        #    l'oeil (un plan revu deux fois dans le lobe rouge).
        #  - films differents : refus seulement si les deux tuiles ont du
        #    CONTENU et se ressemblent. Deux aplats blancs du centre sont
        #    identiques par construction -- c'est ce que le logo demande, pas
        #    un doublon. Les forcer a differer remplacait le blanc par du gris.
        contenu = V.reshape(len(ids), RED * RED, 3).std(axis=(1, 2)) > args.seuil_relief
        conflit = (E < seuil) & (contenu & vu)[:, None] & (contenu & vu)[None, :]
        conflit |= (src[:, None] == src[None, :]) & vu[:, None] & vu[None, :]
        np.fill_diagonal(conflit, False)
        a_refaire = set()
        for i, j in zip(*np.where(np.triu(conflit, 1))):
            gi, gj = ids[int(i)], ids[int(j)]
            if gi in a_refaire or gj in a_refaire:
                continue
            a_refaire.add(gj if fit[int(j)] >= fit[int(i)] else gi)
        return a_refaire

    if args.recaler:
        paires = [(t, f, v) for t, (f, v) in sorted(attrib.items())]
        print("  recalage sur les vraies images : %d a decoder (seul moment ou "
              "on touche aux films)" % len(paires), flush=True)
        refiner(paires)

        # POINT FIXE. A chaque tour on rejuge TOUT le monde sur deux criteres :
        # le recalage a-t-il abouti, et la tuile fait-elle doublon avec une
        # autre. Deplacer une tuile peut en abimer une troisieme, donc rien ne
        # sert de verifier une fois au depart : il faut boucler jusqu'a ce que
        # plus rien ne bouge. Chaque tuile n'essaie chaque candidat qu'une fois
        # (le cache 'vus' fait office de banni), ce qui garantit l'arret.
        for essai in range(1, args.essais + 1):
            rates = {t for t, (f, v) in attrib.items() if not juge(t, f, v)[0]}
            doubles = sosies(attrib)
            mauvais = sorted(rates | doubles)
            print("\n  tour %d : %d recalages rates, %d doublons visuels"
                  % (essai, len(rates), len(doubles - rates)), flush=True)
            if not mauvais:
                print("    plus rien a reprendre")
                break
            for t in mauvais:
                f, v = attrib.pop(t)
                usage[f] -= 1
            # Ne proposer a une tuile VISIBLE que des candidats qui ne
            # ressemblent pas a ce qui est deja pose, et qui viennent d'un film
            # pas encore employe en zone visible. Proposer a l'aveugle faisait
            # tourner la boucle en rond : on ne decouvrait le nouveau conflit
            # qu'au tour suivant, et on en creait un autre en le reparant.
            posees = [t for t in attrib if not sombre[t]]
            films_vus = {attrib[t][0] for t in posees}
            # seules les tuiles AVEC CONTENU bloquent par ressemblance : un
            # aplat blanc n'a pas a interdire les autres aplats blancs
            avec_contenu = [t for t in posees
                            if vecteur(t, *attrib[t]).reshape(-1, 3).std() > args.seuil_relief]
            bloque = None
            if avec_contenu:
                P = np.array([vecteur(t, *attrib[t]) for t in avec_contenu])
                dmin = ((B * B).sum(1)[:, None] + (P * P).sum(1)[None, :]
                        - 2.0 * B @ P.T).min(1) / B.shape[1]
                bloque = (dmin < args.seuil_doublon) & contenu_banque

            demandes, suivant, poses_du_tour = [], {}, []
            for t in mauvais:
                for c in np.argsort(cout[t]):
                    c = int(c)
                    f, v = divmod(c, VIGN)
                    if (t, c) in vus or usage[f] >= args.max_par_film:
                        continue
                    if not sombre[t]:
                        if f in films_vus or (bloque is not None and bloque[c]):
                            continue
                        # ... et pas non plus comme ce qu'on vient de poser
                        # dans CE tour, que le pre-filtrage ne connait pas
                        if contenu_banque[c] and any(
                                float(((B[c] - q) ** 2).mean()) < args.seuil_doublon
                                for q in poses_du_tour):
                            continue
                        if contenu_banque[c]:
                            poses_du_tour.append(B[c])
                        films_vus.add(f)
                    suivant[t] = (f, v)
                    demandes.append((t, f, v))
                    # Reserver la place TOUT DE SUITE. Sans ca, les tuiles
                    # fautives d'un meme tour -- souvent toutes des tuiles de
                    # fond -- designent le meme film le moins cher et sont
                    # toutes acceptees : un seul fichier finissait sur 28 tuiles.
                    usage[f] += 1
                    break
            print("    %d candidats suivants a decoder" % len(demandes), flush=True)
            refiner(demandes)
            for t, (f, v) in suivant.items():
                attrib[t] = (f, v)      # provisoire : le tour suivant rejuge

        # Le budget de tours peut s'epuiser avant la convergence. Les tuiles
        # encore fautives tiennent alors leur DERNIER essai, qui n'est pas le
        # meilleur : on leur rend le meilleur qu'elles ont deja paye.
        repli = 0
        for t in sorted(attrib):
            f, v = attrib[t]
            if juge(t, f, v)[0]:
                continue
            for _, c in sorted((r[1], c) for (tt, c), r in vus.items()
                               if tt == t and r[1] is not None):
                nf, nv = divmod(c, VIGN)
                if (nf, nv) == (f, v):
                    break                      # le courant est deja le meilleur
                if usage[nf] < args.max_par_film:
                    usage[f] -= 1
                    attrib[t] = (nf, nv)
                    usage[nf] += 1
                    repli += 1
                    break
        if repli:
            print("  %d tuiles ramenees a leur meilleur essai" % repli)

        # Filet : une tuile peut sortir de la boucle sans affectation si tous
        # ses candidats essayes sont pris. On lui rend son meilleur essai
        # disponible, sinon le meilleur film libre. Mieux vaut une tuile
        # approximative qu'un trou noir dans la mosaique.
        orphelines = [t for t in range(len(boites)) if t not in attrib]
        for t in orphelines:
            cands = sorted((r[1], c) for (tt, c), r in vus.items()
                           if tt == t and r[1] is not None)
            for _, c in cands:
                f, v = divmod(c, VIGN)
                if usage[f] < args.max_par_film:
                    attrib[t] = (f, v)
                    usage[f] += 1
                    break
            if t not in attrib:
                for c in np.argsort(cout[t]):
                    f, v = divmod(int(c), VIGN)
                    if usage[f] < args.max_par_film:
                        attrib[t] = (f, v)
                        usage[f] += 1
                        break
        if orphelines:
            print("  %d tuiles recasees par defaut" % len(orphelines))

    entrees = [{"box": b, "match": {"video": None, "rel": None, "t": None,
                                    "frame_idx": None, "variant": "center",
                                    "dist": 1e12}} for b in boites]
    apercu = None
    if args.apercu:
        apercu = np.zeros((int(CFG.get("height", "1080")),
                           int(CFG.get("width", "1920")), 3), dtype=np.uint8)

    for t_i, (f_i, v_i) in sorted(attrib.items()):
        film = films[f_i]
        d_banque = float(D[t_i, f_i * VIGN + v_i])
        if args.recaler:
            _, t, d_reel, img = juge(t_i, f_i, v_i)
            if t is None:
                t, d_reel, img = v_i * film["duree_s"] / float(ECHANT), None, None
        else:
            t, d_reel, img = v_i * film["duree_s"] / float(ECHANT), None, None
        m = entrees[t_i]["match"]
        m["rel"] = film["rel"]
        m["video"] = os.path.normpath(os.path.join(corpus, film["rel"]))
        m["t"] = float(t)
        m["dist"] = float(d_reel) if d_reel is not None else d_banque
        if film.get("fps"):
            m["frame_idx"] = int(round(t * film["fps"]))
        if apercu is not None and img is not None:
            x0, y0, x1, y1 = boites[t_i]
            apercu[y0:y1, x0:x1] = np.asarray(
                Image.fromarray(img).resize((x1 - x0, y1 - y0), Image.LANCZOS))

    if apercu is not None:
        Image.fromarray(apercu).save(args.apercu, quality=95)
        print("\napercu : %s" % args.apercu)

    d2 = np.array([e["match"]["dist"] for e in entrees if e["match"]["rel"]])
    print("ecart final : median %.0f, moyen %.0f, max %.0f"
          % (np.median(d2), d2.mean(), d2.max()))

    os.makedirs(os.path.dirname(sortie) or ".", exist_ok=True)
    tmp = sortie + ".tmp"
    with io.open(tmp, "w", encoding="utf-8") as f:
        json.dump(entrees, f, ensure_ascii=False, indent=2)
    os.replace(tmp, sortie)
    print("\n-> %s  (%d tuiles)" % (sortie, sum(1 for e in entrees if e["match"]["rel"])))


if __name__ == "__main__":
    main()
