# Modèle adaptatif de limite DTU

Le modèle adaptatif observe passivement la réponse réelle de l'installation à
des commandes DTU déjà confirmées. Il ne pilote pas le DTU dans cette première
version : OpenEMS continue d'utiliser le modèle nominal configuré
`puissance nominale / 100`.

## But

La valeur exprimée en pourcentage par les limites temporaires DTU n'est pas
supposée représenter une puissance AC linéaire. Le modèle mesure donc l'effet
local d'une commande confirmée :

```text
gain observé = |puissance DTU après - puissance DTU avant|
                / |limite après - limite avant|
```

Les gains sont regroupés dans les plages `2–10 %`, `11–25 %`, `26–50 %`,
`51–75 %` et `76–100 %`. Chaque profil utilise une médiane robuste, la
dispersion, le nombre d'observations et l'âge de la dernière observation.

## Critères conservateurs

Une observation est acceptée uniquement après une commande automatique
confirmée, deux mesures réseau/PV stables avant la commande, une stabilisation
terminée et deux mesures de puissance DTU après la stabilisation. Elle est
rejetée — donc indéterminée, jamais considérée comme un gain nul — si les
mesures avant ou après restent instables, si la batterie change d'état, si la
réponse est trop faible, dans le mauvais sens, hors bornes prudentes, ou si la
fenêtre d'observation expire.

## Mode passif

Les diagnostics et l'historique persistant publient le gain nominal, le gain
observé, l'estimation adaptative, la confiance, la plage et une limite
candidate. La valeur `gain_utilise_w_per_percent` reste explicitement égale au
gain nominal. Le contrôleur, le Scheduler et les commandes Modbus ne lisent pas
le profil adaptatif.

## Validation prédictive hors échantillon

Avant chaque résultat exploitable, OpenEMS fige le gain nominal et, si le
profil disposait déjà d'une confiance suffisante, le gain adaptatif existant.
Les deux variations de puissance prévues sont donc calculées **avant** la
mesure après stabilisation. La comparaison est établie seulement après la
mesure, puis l'observation peut éventuellement être ajoutée au profil.

Les métriques globales et par plage conservent le nombre de prédictions
comparables, les erreurs absolues moyenne et médiane, les erreurs signées et
le pourcentage de cas où le modèle adaptatif était meilleur. Une observation
ayant servi à apprendre n'est jamais utilisée pour valider la prédiction qui a
précédé son apprentissage.

L'erreur signée est calculée par `variation prédite − variation observée` : une
valeur positive signifie que le modèle surestime la réaction de puissance ; une
valeur négative signifie qu'il la sous-estime.

Une activation éventuelle devra être proposée et validée séparément après une
analyse de plusieurs jours de données terrain.
