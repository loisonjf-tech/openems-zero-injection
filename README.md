# OpenEMS Zero Injection

Intégration Home Assistant locale destinée à piloter un Hoymiles DTU Pro-S afin de minimiser les échanges réseau dans une installation monophasée, en tenant compte d'une batterie Zendure SolarFlow 800 Plus.

## État du projet

**Build004 — fondation expérimentale du contrôleur de zéro injection.** Le projet acquiert une puissance réseau locale, calcule une consigne DTU déterministe, et applique un scheduler de sécurité. Il n'intègre pas encore SolarFlow, Zendure ou une logique de batterie.

Version actuelle : **V0.8.0-alpha.1 / Build007 Capacity Release**.

Build007-B ajoute un mode expérimental **Priorité Batterie observée —
conservateur**, désactivé par défaut. Après trois mesures fraîches de charge
SolarFlow supérieures à `50 W`, il autorise une marge contrôlée de `25 W` sur la
cible réseau. Une décharge, une donnée périmée ou toute incohérence rétablit
immédiatement Zero Injection. La SolarFlow reste strictement en lecture seule.

## Matériel de référence

- Hoymiles DTU Pro-S (Modbus TCP)
- Onduleurs Hoymiles HMS-1000 et HMS-2000
- Zendure Smart Meter
- Batterie SolarFlow 800 Plus
- Home Assistant 2026.7.2, monophasé

## Installation de développement

Copiez `custom_components/openems_zero_injection` dans le répertoire `custom_components` de votre configuration Home Assistant, redémarrez Home Assistant, puis ajoutez **OpenEMS Zero Injection** depuis *Paramètres → Appareils et services*. Renseignez l'adresse et le port Modbus TCP du DTU.

## Configuration

Dans l'assistant d'ajout de l'intégration, indiquez l'adresse IP du Hoymiles DTU Pro-S et le port TCP. Le port par défaut est `502`. Le capteur de diagnostic **OpenEMS Connection** affiche `Connected` lorsque le port TCP est joignable, sinon `Disconnected`.

## Contrôleur expérimental (Build004)

Configurez l'entité Home Assistant de puissance réseau dans les options de l'intégration. La convention par défaut est positive = consommation réseau et négative = injection. La cible par défaut est `-40 W`, avec une zone morte de `±30 W`.

Les valeurs internes restent `Disabled`, `Simulation` et `Production`, mais l’interface affiche respectivement **Manuel**, **Simulation** et **Régulation automatique**. En mode **Manuel**, le curseur **Limite temporaire manuelle DTU** est disponible lorsque le DTU est connecté et écrit une même valeur sur les trois ports temporaires. En **Simulation**, aucune écriture n’est possible. En **Régulation automatique**, le scheduler est le seul pilote du DTU et le curseur est verrouillé.

Le mode de validation des limites temporaires est **Compatibilité** par défaut. Après trois écritures temporaires réussies et leurs accusés de réception `0x06`, il conserve localement la consigne confirmée si certains DTU ne permettent pas de relire fiablement `0xD007`, `0xD00D` ou `0xD013`. Le mode **Strict** exige au contraire trois relectures `0x03` fraîches, identiques et valides. Dans les deux cas, une erreur d'écriture ou une perte de communication arrête les commandes ; aucune valeur `0`, `2` ou `100` n'est inventée.

La stratégie de démarrage Production reste par défaut **Mode sécurisé** : aucune écriture n'est envoyée sans référence de limite connue. L'option **Prise de contrôle** envoie au passage explicite vers Production la limite configurée (`100 %` par défaut, réglable de `2` à `100 %`) aux trois registres temporaires. Les trois échos `0x06` deviennent la référence locale, puis le délai de stabilisation est respecté avant la régulation normale. Elle exige le mode de validation Compatibilité et ne dépend d'aucune relecture `0x03`. L'option distincte **Reprendre automatiquement Production après redémarrage** est désactivée par défaut ; lorsqu'elle est activée, une Production précédemment enregistrée refait la même prise de contrôle uniquement après chargement réussi de l'intégration et DTU joignable. Un échec d'écriture ne déclenche aucune nouvelle tentative automatique.

La **Puissance nominale de l’installation photovoltaïque** est configurée manuellement, persistée dans les options et vaut `3000 W` par défaut pour l'installation actuelle. Le coefficient de conversion est toujours calculé par `puissance nominale / 100` : `3000 W` donne `30 W/%`, `4000 W` donne `40 W/%`. Cette donnée n'est ni lue ni déduite depuis la DTU ; une future valeur détectée par la DTU, si elle est validée, restera informative.

> **Avertissement :** Build004 est expérimental. Le mode Production peut modifier la puissance photovoltaïque réelle. Les premiers essais doivent être réalisés sous surveillance.

## Sécurité

Le client interne utilise uniquement les fonctions Modbus TCP `0x03`, `0x04` et `0x06`. Les écritures Build004 sont exclusivement temporaires vers `0xD007`, `0xD00D` et `0xD013`, vérifiées par relecture. Les registres permanents (`0xD008`, `0xD00E`, `0xD014`) sont seulement diagnostiques et lus toutes les cinq minutes, jamais écrits. Il n'implémente pas `0x10`, aucune écriture permanente ou globale, aucun PID ni aucune logique batterie.

Les lectures Modbus sont strictement sérialisées, sans temporisation artificielle entre les trames, sur une connexion TCP persistante. Le capteur **Temps de réponse DTU** représente la dernière transaction Modbus, tandis que les diagnostics détaillent chaque phase et la durée totale du cycle. Une erreur ponctuelle conserve la dernière valeur connue, signalée comme périmée avec sa date et son compteur d'échecs ; elle ne devient jamais `0` artificiellement. Les erreurs de socket, timeout ou réponse incomplète ferment la connexion TCP. Les nouvelles tentatives respectent un backoff non bloquant de 5, 10, 20 puis 30 secondes.

Le contrôleur vérifie son tick toutes les trois secondes, mais n'évalue qu'un seul snapshot cohérent par nouvelle génération de mesures. La puissance DTU est lue toutes les 10 secondes, l'énergie et les limites temporaires toutes les 30 secondes, et les informations générales ainsi que les limites permanentes toutes les cinq minutes. Les limites temporaires restent utilisables 65 secondes ; les limites permanentes sont diagnostiques et ne suspendent jamais le contrôleur.

## Contrôleur prédictif — Build004 RC2

Lorsque la puissance PV DTU, la puissance réseau et les limites temporaires sont valides et synchronisées, la régulation estime directement la consommation : `puissance PV + puissance réseau`. Elle en déduit une limite DTU cible bornée entre `2 %` et `100 %`. Une erreur importante (au moins `250 W` par défaut) utilise cette limite prédictive directement ; après stabilisation, une erreur plus faible utilise une correction fine limitée à `2 %`.

Les protections existantes restent obligatoires : aucune commande pendant la stabilisation, aucune écriture en Simulation, aucune écriture si les limites temporaires sont incertaines et aucune répétition automatique après un échec. Si la puissance PV ne permet pas une prédiction fiable, le contrôleur utilise seulement la correction fine prudente.

Build004 RC2 prépare aussi les contrats passifs **Context Analyzer**, **Calibration Manager** et **Energy Policy Engine**. La seule politique active est **Zero Injection**, qui transmet exactement la cible réseau configurée. Aucune logique SolarFlow ou batterie ne participe encore à la régulation. L’architecture de référence est [docs/Architecture-Specification.md](docs/Architecture-Specification.md).

En **Simulation**, l’état du planificateur indique explicitement qu’il attend de nouvelles mesures après une proposition. La capteur **Prochaine limite commandée** affiche alors cette proposition avec les attributs `execution_mode: Simulation` et `is_simulation: true` : aucune écriture DTU n’est effectuée. Le nombre de compteurs déclaré par le DTU est seulement diagnostique ; la régulation utilise exclusivement le capteur de puissance réseau configuré dans Home Assistant.

Le mode sélectionné du contrôleur est enregistré dans les options de l’intégration et restauré après un redémarrage ou un rechargement. Le journal indique le mode restauré et sa source. En mode **Manuel**, la puissance réseau reste visible lorsqu’elle est lisible : cela distingue explicitement une absence de régulation automatique d’un capteur réseau indisponible.

Une limite permanente hors de la plage documentée est traitée comme une donnée diagnostique indisponible. Sa valeur brute est journalisée une fois, puis le registre optionnel est temporairement suspendu ; elle ne modifie ni l’état de connexion ni les limites temporaires utilisées par le contrôleur.

Le curseur unique écrit `0xD007`, `0xD00D` et `0xD013`, avec une plage de `2` à `100 %` et un pas de `1 %`. Les trois capteurs réels restent diagnostiques. Les trois anciennes commandes par port restent dans le registre Home Assistant mais sont automatiquement désactivées par l’intégration : elles ne sont donc ni supprimées brutalement ni actives. Un échec partiel marque les ports **Incertains**, suspend la régulation automatique et exige une nouvelle commande explicite en mode Manuel pour les resynchroniser.

Les diagnostics indiquent aussi si les ports sont synchronisés et la source de la limite courante : relecture Modbus, prise de contrôle confirmée, correction automatique confirmée, commande manuelle confirmée ou inconnue.

## Trace Recorder — Build004 RC4

Le Trace Recorder est la boîte noire passive d’OpenEMS. En mode normal, il conserve les 100 dernières chronologies détaillées en mémoire. Il ne déclenche ni lecture Modbus supplémentaire, ni écriture, ni tâche périodique, et ne peut pas modifier une décision ou le Scheduler.

Pour chaque commande déjà décidée, il relie la décision, la politique, le contexte, l’écriture Modbus sur les trois ports, la confirmation, la stabilisation et les observations réseau/PV suivantes. Chaque trace distingue les données connues avant la décision des observations obtenues après la commande. Son schéma est versionné et ne contient que des données primitives sérialisables, afin de préparer un futur rejeu hors ligne sans le développer maintenant.

Les traces et diagnostics conservent aussi une observation DTU/limite corrélée : puissance nominale configurée, limite demandée, puissance maximale théorique, puissance active réellement lue, limites temporaires des trois ports, âge de leur confirmation et état du Scheduler. Cette instrumentation réutilise exclusivement le cycle existant : elle n’ajoute ni lecture Modbus, ni écriture, ni temporisation.

Les statistiques de session sont agrégées pendant toute la session, indépendamment du buffer des 100 chronologies : elles ne sont donc pas tronquées lorsqu’une session comporte davantage de commandes. Les médianes utilisent un échantillon borné ; les compteurs, moyennes, maximums et couverture pondérée restent complets. Une absence de mesures ou une télémétrie trop espacée ne peut jamais conclure à une commande inefficace : le résultat est alors **indéterminé**.

Le mode diagnostic détaillé, le polling accéléré et les exports CSV/JSON restent volontairement hors périmètre. Les identifiants enregistrés (`policy_id`, stratégie, contexte et résultats) sont stables et indépendants de la langue ; l’interface Home Assistant les présente via ses traductions.

## SolarFlow lecture seule — Build005

L’adaptateur SolarFlow lit uniquement des entités déjà disponibles dans Home
Assistant. Il normalise le SOC et la puissance directionnelle
`sensor.solarflow_800_plus_bat_in_out` : négatif = charge, positif = décharge
et zéro = inactive. `gridInputPower` reste un repère diagnostique facultatif.
Il n’écrit jamais dans SolarFlow,
ne contacte aucun cloud et ne modifie ni la régulation DTU ni le Scheduler.

Lorsque l’option de validation est activée, `chargeMaxLimit` est lu depuis
`sensor.solarflow_800_plus_charge_max_limit`, exclusivement en `W` ou `kW`.
Les valeurs sont normalisées sans facteur implicite puis utilisées pour exposer
la capacité maximale et restante. Une valeur absente, restaurée avant le
démarrage, périmée, non validée ou d’unité inconnue reste indisponible.

## Energy Strategy Engine — Build006

Build006 sépare formellement le choix de la cible énergétique de son application
au DTU. `ZeroInjectionStrategy` est la seule stratégie active et transmet
strictement la cible réseau actuelle : le comportement de régulation reste donc
identique à Build005. Le moteur prédictif, le Scheduler et le client DTU ne
sont pas modifiés. Les décisions reçoivent un identifiant de snapshot, un
horodatage et un code de motif stable afin de préparer une comparaison future,
en Simulation, avec une stratégie batterie. Aucune stratégie batterie n'est
présente ni activée dans ce build.

## Battery Priority Simulation — Build007

Build007 compare passivement une cible `BatteryPriorityStrategy` à la cible
Zero Injection, uniquement en mode Simulation. Si une capacité de charge
complète et fraîche est disponible, la candidate peut conserver jusqu'à `25 W`
de marge d'injection supplémentaire. Ce gain est théorique : il ne garantit pas
une charge batterie. En Production, OpenEMS conserve strictement la stratégie
Zero Injection ; aucune écriture batterie, DTU, requête Modbus supplémentaire,
tâche ou polling n'est créé.

## Tests

Dans un environnement de développement Home Assistant 2026.7.2 compatible avec Python 3.14.2 ou plus récent, installez les dépendances de test puis exécutez `pytest`. La suite couvre le Config Flow, le client Modbus simulé, le coordinateur, le capteur et les diagnostics.

## Feuille de route

1. **Build004** : valider sous surveillance le mode Simulation, puis Production, sur le DTU réel.
2. **V1.1** : adaptateurs de batterie derrière la couche EMS passive, avec une éventuelle politique Priorité Batterie validée séparément.
3. **Build005** : seulement après validation réelle des comportements Build004 et V1.1.
