#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Lecture de config.txt.

Format : 'cle = valeur', un par ligne, '#' pour commenter. Une valeur peut
proposer PLUSIEURS chemins separes par '|' : le premier qui existe gagne. C'est
ce qui rend le projet insensible a la lettre de montage du disque, sans rien
avoir a editer quand elle change.

Les chemins relatifs sont resolus depuis le dossier du projet, jamais depuis le
repertoire courant : les scripts marchent quel que soit l'endroit d'ou on les
lance.

  from config import CFG
  CFG.path("corpus")        # -> le premier chemin existant, ou erreur claire
  CFG.get("grid", "27 27")  # -> valeur brute
"""
import os
import sys
from typing import Dict, List, Optional

HERE = os.path.dirname(os.path.abspath(__file__))
FICHIER = os.path.join(HERE, "config.txt")


class Config(object):
    def __init__(self, chemin: str = FICHIER) -> None:
        self.chemin = chemin
        self.valeurs: Dict[str, str] = {}
        if os.path.isfile(chemin):
            self._lire(chemin)

    def _lire(self, chemin: str) -> None:
        with open(chemin, "r", encoding="utf-8") as f:
            for n, ligne in enumerate(f, 1):
                ligne = ligne.split("#")[0].strip()
                if not ligne:
                    continue
                if "=" not in ligne:
                    sys.exit("%s ligne %d : il manque un '=' -> %r"
                             % (os.path.basename(chemin), n, ligne))
                cle, val = ligne.split("=", 1)
                self.valeurs[cle.strip()] = val.strip()

    def get(self, cle: str, defaut: Optional[str] = None) -> Optional[str]:
        return self.valeurs.get(cle, defaut)

    def candidats(self, cle: str) -> List[str]:
        """Les chemins proposes pour cette cle, absolutises, dans l'ordre."""
        brut = self.valeurs.get(cle)
        if brut is None:
            return []
        out = []
        for p in brut.split("|"):
            p = p.strip().strip('"')
            if not p:
                continue
            out.append(p if os.path.isabs(p) else os.path.normpath(os.path.join(HERE, p)))
        return out

    def path(self, cle: str, doit_exister: bool = True) -> str:
        """Le premier candidat qui existe. Sinon, un message qui dit quoi editer."""
        cands = self.candidats(cle)
        if not cands:
            sys.exit("config.txt : la cle '%s' est absente.\n"
                     "  ajoute une ligne :  %s = <chemin>" % (cle, cle))
        for p in cands:
            if os.path.exists(p):
                return p
        if not doit_exister:
            return cands[0]
        sys.exit("config.txt : aucun des chemins de '%s' n'existe.\n%s\n"
                 "  le disque est peut-etre monte sur une autre lettre :\n"
                 "  ajoute-la dans config.txt, separee par '|'"
                 % (cle, "".join("    %s\n" % p for p in cands)))

    def ints(self, cle: str, defaut: str) -> List[int]:
        return [int(x) for x in (self.get(cle, defaut) or defaut).split()]


CFG = Config()

if __name__ == "__main__":
    print("config : %s\n" % FICHIER)
    for cle in sorted(CFG.valeurs):
        cands = CFG.candidats(cle)
        if len(cands) == 1 and not os.path.exists(cands[0]) and not os.path.isabs(
                CFG.valeurs[cle].split("|")[0].strip()):
            print("  %-14s %s" % (cle, CFG.valeurs[cle]))
            continue
        if cands:
            for p in cands:
                marque = "OK  " if os.path.exists(p) else "--  "
                print("  %-14s %s%s" % (cle, marque, p))
                cle = ""
        else:
            print("  %-14s %s" % (cle, CFG.valeurs[cle]))
