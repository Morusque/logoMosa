# logoMosa — le logo Kino Montpellier en mosaïque de films

Le logo est reconstitué en grille **27 × 27 = 729 tuiles**, chaque tuile étant
une image tirée d'un film du corpus. Le clip part d'une tuile en plein cadre,
dézoome jusqu'à révéler le logo entier — et pendant tout le dézoom, chaque
tuile **joue** son film.

```
generer_serie.bat            une série de clips, tuiles tirées au hasard
generer_logo.bat 364         un seul clip, sur la tuile 364
python config.py             vérifier les chemins que voient les scripts
```

## Le disque bouge, la config suit

Tout est dans `config.txt`, au format `clé = valeur`. Une valeur peut proposer
**plusieurs chemins séparés par `|`** : le premier qui existe gagne.

```
corpus = F:/Kino/montpellier | G:/Kino/montpellier | D:/Kino/montpellier
```

Quand le disque du corpus change de lettre, il n'y a rien à éditer si la lettre
est déjà dans la liste. Aucun script ne contient de chemin en dur, les `.bat`
compris.

Les matches portent en plus un champ `rel`, chemin **relatif** au corpus : c'est
lui qui est utilisé au rendu. Un déménagement du corpus ne demande donc plus de
réparation, seulement une ligne de config.

## Le pipeline, dans l'ordre

| | ce que ça fait | coût | quand |
|---|---|---|---|
| `banque_vignettes.py` | 72 000 vignettes candidates, tirées des planches contact de `visionnages01` | 2 min | une fois, ou quand des films arrivent |
| `chercher_tuiles.py` | choisit l'image de chacune des 729 tuiles | 3 min | une fois par mosaïque |
| `cache_tuiles.py` | extrait les ~5 s que chaque tuile va jouer | 2 min, 45 Mo | une fois, sert à **tous** les clips |
| `ouvertures.py` | note la première seconde et demie de chaque tuile | 10 s | automatique |
| `rendre_logo.py` | compose et encode un clip | 40 à 60 s | par clip |
| `son_logo.py` | pose le son sur un clip déjà rendu | 2 s | par clip |
| `generer_serie.py` | enchaîne le tout sur N tuiles | | |

`geometrie.py` tient les formules du dézoom, partagées et inchangées depuis
2025 : le mouvement des nouveaux clips est identique à celui des neuf premiers.

## Ce qui fait la vitesse

Le rendu de 2025 rouvrait le fichier vidéo pour **chaque image de chaque
tuile** : 75 000 accès dispersés dans 441 Go, soit 13 minutes par image dont
2,4 secondes de calcul. Tout le reste était de l'attente disque.

Or chaque tuile n'a besoin que d'un segment **contigu** (de t−5 s à t+0,1 s), et
ce segment **ne dépend pas de la tuile de focus** — seule la géométrie du zoom
en dépend. D'où `cache_tuiles.py` : on l'extrait une fois, tous les clips le
réutilisent.

Reste que près du début, la tuile de focus remplit l'écran. Le cache est en
160 px ; `rendre_logo.py` calcule donc, tuile par tuile, la taille maximale
qu'elle atteindra **dans ce rendu-là**, et ne réextrait en haute définition que
la centaine de tuiles concernées.

| | 2025 | aujourd'hui |
|---|---|---|
| une image | 13 min | — |
| un clip complet | ~8 h | **50 s** |

## Deux conventions à ne pas casser

**Le cadrage.** `geometrie.crop_resize_fill` (au rendu) et
`banque_vignettes.recadrer` (à la recherche) appliquent le même recadrage
centré au format de la tuile. C'est ce qui fait que la recherche **note ce que
le rendu affichera**. Si l'un change, l'autre doit changer avec lui.
L'ancien chercheur écrasait l'image entière dans un carré : il jugeait un
cadrage et en montrait un autre, d'où des `dist` trop optimistes.

**La durée du clip.** Elle est **transmise** par `rendre_logo.py` à
`son_logo.py`, jamais sondée sur le fichier. Le `apad` du mixage remplit de
silence sans fin ; une sonde qui répond de travers lui retire sa borne, et le
mux écrit des minutes d'audio pour un clip de 7 secondes. C'est arrivé.

## Le son

Relevé sur les clips de 2025, puis ajusté :

```
0 → 0,5 s      montée, image ET son ensemble (--montee, une seule option)
0,5 s → pop    le son du film, à volume constant
50 ms avant    une descente courte, qui dégage la place
le pop         l'accent du sfx, sur la révélation
après          le logo propre, puis le noir, en silence
```

L'instant de l'accent n'est pas codé en dur : il est **détecté** dans le fichier
sfx et calé sur la révélation. Changer de sfx ne demande rien d'autre que de
changer le fichier.

C'est un défaut raisonnable, pas une doctrine : les neuf clips de 2025 avaient
chacun un son décidé à la main. `--descente`, `--montee`, `--gain_film`,
`--gain_sfx` sont là pour ça, et `rendre_logo.py` sans `--son` sort un clip muet
à habiller ailleurs. Comme `son_logo.py` recopie le flux vidéo sans le
réencoder, réhabiller un clip coûte 2 secondes.

## Éviter d'ouvrir sur un générique

Le clip s'ouvre sur la tuile de focus en plein cadre pendant plusieurs
secondes : c'est le plan le plus vu du film. `ouvertures.py` écarte les
ouvertures noires et les cartons figés — **583 tuiles sur 729** restent
éligibles.

Le critère ne porte pas sur le mouvement : mesuré, une tuile jugée bonne à
l'œil ouvrait sur un plan quasi fixe et aurait été écartée. Ce qui trahit un
carton, c'est le noir.

## Les dossiers

```
config.txt config.py      les chemins, et rien qu'ici
logo.png                  la cible de la mosaïque
geometrie.py              les formules du dézoom
*.py *.bat                le pipeline
outils/                   evaluer_matches, remap_matches — ponctuels
ancien/                   le pipeline 2025, gardé pour mémoire
pointTile01/              sketch Processing : cliquer une tuile, lire son numéro
data/                     banque, cache, cache_hd — tout est reconstructible
out_mosaic/               matches_exhaustif.json, et logos/ = les clips
montages/sfx/             le sfx, source du montage
backups/                  archives — on n'y enlève rien
```

`data/` et `out_mosaic/` sont hors dépôt : plusieurs centaines de Mo, tous
reconstructibles par les commandes ci-dessus.

## Ce qui reste ouvert

- **Les quasi-doublons sémantiques.** Deux roses roses en gros plan, dans deux
  films différents : écart mesuré 3719, donc très loin — le calcul voit deux
  images distinctes, l'œil voit « encore une rose ». Il faudrait des
  descripteurs sémantiques (CLIP, que `visionnages01` sait déjà produire) et
  non une différence de pixels.
- **Le son sans dialogue coupé.** `visionnages01` a les segments Whisper
  horodatés : on pourrait *proposer* les fenêtres où le film de focus ne parle
  pas, plutôt qu'imposer une courbe.
- **Les ouvertures qui tombent au noir.** Le filtre juge la moyenne des 30
  premières images ; un beau plan qui coupe au noir quatre images plus tard lui
  échappe. Un critère de stabilité le rattraperait.
