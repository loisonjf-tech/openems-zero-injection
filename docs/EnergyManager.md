# Energy Manager — préparation EMS passive

`EnergyManager` est une couche indépendante du scheduler DTU. En V1, elle ne contient aucune source de données active et ne modifie aucune décision de régulation.

`BatteryResource` représente une batterie autonome avec son identifiant, son nom, son SOC, ses puissances de charge/décharge courantes et maximales, son état, sa disponibilité et son caractère autonome.

Le calculateur publie uniquement : nombre de batteries, puissance maximale de charge, puissance de charge actuelle et capacité de charge restante. Pour chaque batterie disponible :

`remaining_charge_power_w = max(0, max_charge_power_w - current_charge_power_w)`

La capacité totale est la somme de ces valeurs. Les valeurs inconnues n'ajoutent aucune capacité. Une future V1.1 pourra connecter des adaptateurs fabricants à cette couche, puis seulement après validation ajouter une politique EMS séparée.
