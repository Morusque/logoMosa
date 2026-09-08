# Le pipeline de 2025

Ces deux scripts ont produit les neuf premiers logos animés (`montages/logoMosaKino/`).
Ils ne servent plus, mais ils sont gardés : ils documentent comment la chose a
été faite, et `render_mosaic_from_matches.py` reste un rendu qui fonctionne.

| | remplacé par |
|---|---|
| `mosaic_from_videos.py` | `banque_vignettes.py` + `chercher_tuiles.py` |
| `render_mosaic_from_matches.py` | `cache_tuiles.py` + `rendre_logo.py` |

**Ce qui a changé, et pourquoi**

`mosaic_from_videos.py` tirait des images au hasard dans les films et gardait
celles qui amélioraient la mosaïque : glouton, sans critère d'arrêt, et il n'a
jamais touché que 452 films sur 837. La recherche actuelle compare les 729
tuiles à 72 000 vignettes d'un coup, et prend le meilleur découpage possible.

`render_mosaic_from_matches.py` rouvrait le fichier vidéo pour chaque image de
chaque tuile — 13 minutes par image, dont 2,4 secondes de calcul. Le reste
était de l'attente disque. Le rendu actuel travaille sur un cache extrait une
seule fois : 50 secondes pour un clip entier.

Deux pièges à connaître si tu relis ce code :

- `--zoom_gamma` n'est pas un gamma. Il est passé en `steepness` à
  `zoom_factor_S`, la sigmoïde du dézoom.
- `--video_out` n'encode aucune vidéo : le script n'écrit que des PNG. Le nom
  ne sert qu'à placer l'aperçu du plan de focus.

Les formules du dézoom ont été extraites dans `../geometrie.py`, à l'identique
(vérifié sur 7200 comparaisons). Ces fichiers en gardent leur propre copie pour
rester autonomes.
