# Build005 — SolarFlow Read-only Battery Adapter

## Objectif

Build005 ajoute une lecture locale et passive de la batterie Zendure SolarFlow
via des entités déjà publiées dans Home Assistant. Il normalise ces données vers
`BatteryResource` et les agrège dans `EnergyManager`.

Ce build ne modifie pas `controller.py`, `scheduler.py`, `decision.py` ou
`modbus.py`. Il n’émet aucune écriture vers la batterie, aucun appel cloud,
aucune commande DTU supplémentaire et aucune décision énergétique.

## Sources SolarFlow initiales

| Donnée candidate | Entité source | Statut | Précondition |
| --- | --- | --- | --- |
| SOC | `sensor.solarflow_800_plus_electric_level` | facultative, état | nombre fini de 0 à 100, unité `%` si fournie ; jamais nécessaire pour observer la charge |
| Puissance directionnelle | `sensor.solarflow_800_plus_bat_in_out` | obligatoire | nombre fini, unité `W` ou `kW`, négatif = charge, positif = décharge |
| Puissance `gridInputPower` | `sensor.solarflow_800_plus_grid_input_power` | facultative, diagnostic | comparaison de cohérence uniquement ; n'affecte jamais la santé principale |
| Limite de charge | `sensor.solarflow_800_plus_charge_max_limit` | ignorée | la valeur `1000` ne correspond pas au curseur de charge ni à une limite exploitable |

Les identifiants peuvent être remplacés dans les options de l’intégration. Une
source facultative absente ne rend jamais la batterie indisponible ; elle rend
uniquement la capacité correspondante inconnue.

L’adaptateur SolarFlow est désactivé par défaut. Tant qu’il n’est pas activé,
l’Energy Manager conserve l’état « aucune batterie configurée » pour préserver
le comportement des installations existantes.

## Modèle normalisé

`BatteryResource` contient l’identifiant et la version de l’adaptateur,
`last_updated`, `data_age_seconds`, `BatteryHealth`, les capacités normalisées,
les sources employées et toutes les anomalies détectées. Les valeurs inconnues
restent `None`, jamais `0`.

Les capacités fonctionnelles sont indépendantes de la santé générale : une
batterie peut être `healthy` avec `max_charge_power_w` ou
`remaining_charge_power_w` inconnus si les sources facultatives nécessaires ne
sont pas validées.

## Fraîcheur

`last_updated` est l'horodatage de la puissance directionnelle, seule source
opérationnelle nécessaire à l'observation de charge/décharge. L’âge est calculé
à chaque cycle normal du `DataUpdateCoordinator`, sans minuteur, listener ou
polling supplémentaire.

Les seuils sont volontairement distincts : puissance directionnelle et
`gridInputPower` utilisent un seuil court fixe de `30 s` ; le SOC utilise un
seuil long fixe de `10 min`. Le diagnostic expose, pour chaque source, son horodatage, son âge,
son seuil et son état (`fresh`, `stale`, `not_refreshed`, `unavailable` ou
`invalid`).

Après un redémarrage ou rechargement de l’intégration, l’adaptateur exige une
nouvelle publication valide de la puissance directionnelle. Un état Home
Assistant déjà restauré ne peut pas être considéré frais dans cette session.
Le SOC est diagnostiqué séparément et son absence ou son ancienneté ne bloque
pas une observation de puissance directionnelle fraîche.

## Santé et anomalies

La santé prioritaire est calculée par `EnergyManager` selon cet ordre :

1. `fault` : défaut explicite connu par un adaptateur futur ;
2. `unavailable` : puissance directionnelle manquante ou
   `unknown`/`unavailable` ;
3. `stale` : puissance directionnelle valide mais trop ancienne ou non
   republiée depuis le démarrage courant ;
4. `inconsistent` : puissance directionnelle fraîche mais incompatible (valeur
   impossible ou unité incompatible) ;
5. `healthy` : puissance directionnelle présente, fraîche et cohérente.

Le SOC et `gridInputPower` sont facultatifs : leurs anomalies restent exposées
dans les diagnostics, sans dégrader cette santé opérationnelle. Une future
stratégie qui nécessiterait explicitement le SOC devra contrôler sa fraîcheur
par source plutôt que déduire sa disponibilité de `BatteryHealth`.

Avec `bat_in_out`, la convention validée est appliquée directement : une valeur
négative devient `charge_power_w = abs(value)`, une valeur positive devient
`discharge_power_w = value` et zéro donne les deux puissances à `0 W`.
`power_sign_unknown` n'est donc jamais publié pour cette source valide. Il reste
réservé à un autre capteur directionnel sans convention confirmée.

Toutes les anomalies sont conservées dans les diagnostics, même lorsqu’une seule
santé prioritaire est affichée.

## Capacités et agrégats

`charge_max_limit` est ignoré dans cette révision : ses unités et sa valeur
observée (`1000`) ne représentent pas une limite de charge utile. En conséquence
`max_charge_power_w` et `remaining_charge_power_w` restent `None`.

La formule de capacité restante est :

```text
remaining_charge_power_w = max_charge_power_w - charge_power_w
```

Elle sera calculée uniquement dans une évolution future, après identification
d'une limite maximale fiable. Dans cette version, elle vaut toujours `None`.

Pour plusieurs batteries, un agrégat est publié uniquement si toutes les
batteries fonctionnellement éligibles fournissent la valeur concernée. Les
diagnostics publient `coverage` (`complete`, `partial`, `none`) et les identifiants
manquants. Une somme partielle n’est jamais présentée comme exhaustive.

## Codes stables

`BatteryReasonCode` est un `StrEnum` centralisé. Les codes restent stables,
sérialisables et indépendants de la langue. Leur libellé visible passe par les
fichiers de traduction.

## Tests obligatoires

- sources obligatoires et facultatives ;
- SOC limites, valeurs non numériques, `NaN` et infinies ;
- convention de signe inconnue ;
- unités et limite de charge non validées ;
- timestamps hétérogènes, fraîcheur et redémarrage ;
- anomalies multiples conservées ;
- agrégats complets, partiels et absents ;
- preuve que l’adaptateur ne crée aucune écriture batterie, lecture Modbus,
  tâche ou modification du contrôleur/Scheduler.
