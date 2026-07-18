# BatteryManager — préparation V1.1

La V1 ne lit aucune donnée de batterie et ne modifie jamais son comportement selon une batterie. Le module `battery.py` définit uniquement une interface indépendante du constructeur.

Une future intégration devra fournir un `BatteryManager` en lecture seule, retournant un `BatteryState` contenant :

- `is_charging` ;
- `can_charge` ;
- `soc` ;
- `charge_power_w` ;
- `max_charge_power_w`.

Les valeurs inconnues sont représentées par `None`. `NullBatteryManager` est l'implémentation V1 : elle ne fait aucun appel réseau, ne crée aucune entité et ne participe pas à l'algorithme de zéro injection.

Une V1.1 pourra ajouter un adaptateur Zendure SolarFlow, puis appliquer une politique « Priorité Batterie » au-dessus de cette interface. Aucun adaptateur, aucune logique de priorité et aucune commande de batterie ne sont inclus dans cette version.
