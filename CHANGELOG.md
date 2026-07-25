# Changelog

Toutes les évolutions notables sont documentées dans ce fichier.

## [0.7.0-alpha.2] - 2026-07-25 — Build007-B conservative activation

### Added

- Mode optionnel `observed_conservative` de priorité batterie, désactivé par
  défaut : après trois mesures fraîches consécutives de charge supérieure à
  `50 W`, il transmet une cible bornée à `−65 W` au lieu de `−40 W`.
- Diagnostics de mode, marge appliquée, cibles initiale/finale, compteur de
  confirmations, puissance observée et transitions d'activation/repli.

### Safety

- Une décharge supérieure à `50 W`, une donnée batterie absente, périmée,
  incohérente ou en défaut restaure immédiatement la cible Zero Injection.
- `chargeMaxLimit` n'est toujours pas utilisé. Aucune commande batterie n'est
  créée et le Predictive Controller, le Scheduler et le client DTU restent
  inchangés.

## [0.7.0-alpha.1] - 2026-07-25 — Build007

### Added

- `BatteryPriorityStrategy` générique, pure et limitée à une comparaison en
  Simulation avec une réserve maximale de `25 W`.
- Diagnostics et historique passif Trace Recorder : cible effective, candidate,
  écart, gain théorique de stockage et motif de repli.

### Safety

- Production reste exclusivement sur `ZeroInjectionStrategy`. Build007 ne crée
  aucune écriture batterie, aucune écriture DTU, aucun polling ni tâche.

## [0.6.0-alpha.3] - 2026-07-25 — Successful-command logging

### Changed

- Les requêtes et confirmations de limites temporaires réussies sont journalisées
  au niveau `INFO`, et non plus comme avertissements.
- Une confirmation incohérente reste un `WARNING`; un échec réel de commande ou
  de transport reste un `ERROR`.

### Tests

- Ajout d'un test garantissant qu'une commande automatique confirmée ne produit
  aucun journal `ERROR`.

## [0.6.0-alpha.2] - 2026-07-25 — SolarFlow directional-power correction

### Changed

- La source directionnelle par défaut est désormais
  `sensor.solarflow_800_plus_bat_in_out` : négatif = charge, positif =
  décharge et zéro = inactive.
- `gridInputPower` est conservé comme information diagnostique facultative.
- `chargeMaxLimit` est explicitement ignoré : aucune capacité maximale ou
  restante n'est déduite de sa valeur `1000` non validée.

### Safety

- Aucune écriture batterie, aucun trafic Modbus, aucune modification du
  contrôleur, du Scheduler ou du client DTU.

## [0.6.0-alpha.1] - 2026-07-25 — Build006

### Added

- `EnergyStrategyEngine` pur et `ZeroInjectionStrategy`, avec des modèles de
  décision horodatés, identifiants de snapshot et codes de motif stables.
- Test de non-régression déterministe confirmant que l'encapsulation produit
  strictement la même cible que Build005 pour un même instantané.

### Compatibility

- `EnergyPolicyEngine`, `EnergyPolicyDecision` et `ZeroInjectionPolicy` restent
  disponibles comme alias compatibles. Le contrôleur, le Scheduler, le client
  DTU et toutes les sorties de régulation restent inchangés.

### Safety

- `BatteryPriorityStrategy` est absente et inactive. Build006 ne crée ni
  écriture batterie, ni trafic Modbus, ni tâche supplémentaire.

## [0.5.0-alpha.1] - 2026-07-25 — Build005

### Added

- Adaptateur Zendure SolarFlow strictement en lecture seule, alimenté par les états Home Assistant existants.
- `BatteryResource`, santé normalisée, motifs stables, fraîcheur et capacités de charge normalisées.
- Agrégats multi-batteries sans somme partielle trompeuse, avec couverture exposée dans les diagnostics.

### Safety

- Aucune écriture SolarFlow, aucun appel cloud, aucune lecture Modbus supplémentaire et aucun changement du contrôleur, du Scheduler ou des décisions DTU.

## [0.4.0-alpha.4] - 2026-07-25 — Build004 RC4

### Added

- Chronologie passive et explicable par commande : décision, politique, contexte, objectif, justification, trois résultats Modbus, confirmation commune, début de stabilisation, observations réseau/PV et évaluation finale.
- Schéma de trace versionné et exclusivement sérialisable, séparant les entrées pré-décision des observations post-commande pour préparer le rejeu hors ligne futur sans l’implémenter.
- Rapport de session complet : compteurs, durées Modbus, réponse énergétique, erreur, amplitudes, sur-corrections, oscillations et couverture temporelle pondérée.
- Traductions anglaises et françaises des états visibles du Trace Recorder.

### Changed

- Le buffer circulaire conserve toujours au plus 100 chronologies détaillées, mais les métriques de session ne sont plus tronquées par cette limite.
- Les compteurs, moyennes, maximums et couverture couvrent toute la session ; les médianes sont calculées sur un réservoir borné explicitement diagnostique.

### Safety

- RC4 ne crée ni requête Modbus, ni polling, ni tâche, ni écriture disque. Il n’influence ni la décision, ni le Scheduler, ni les délais de stabilisation.
- RC5, dont la stratégie d’écrêtement avec libération est gelée, n’est pas implémenté dans cette version.

### Tests

- Ajout des tests de conservation des métriques au-delà du buffer détaillé et de sérialisation/explainabilité des timelines.

## [0.4.0-alpha.3] - 2026-07-24 — Build004 RC3

### Post-release corrective diagnostics

### Fixed

- La fraîcheur du capteur réseau utilise désormais sa dernière publication Home Assistant (`last_updated`) plutôt que son seul changement de valeur. Une mesure stable mais régulièrement actualisée ne provoque plus une fausse désynchronisation.
- La synchronisation utilise l'horodatage de lecture propre à la puissance PV DTU lorsqu'il est disponible ; la tolérance reste de 25 s, sans nouveau polling.
- Sans batterie configurée, les totaux de charge Energy Manager sont désormais inconnus (`None`) et non plus artificiellement égaux à `0 W`.

### Added

- Diagnostics et capteurs de diagnostic : horodatages réseau/PV, âges, écart, tolérance de synchronisation et motif détaillé d'un instantané refusé.

### Trace Recorder Foundation

### Added

- Fondation passive `TraceRecorder` : buffer circulaire en mémoire limité aux 100 dernières commandes, sans écriture disque ni polling supplémentaire.
- Traces horodatées séparant l'horodatage source, la réception OpenEMS et le temps monotone pour les décisions, les trois écritures temporaires et les observations déjà disponibles.
- Sessions de régulation ouvertes en Production et clôturées au changement de mode, au rechargement, à l'arrêt ou après une modification majeure de configuration.
- Métriques prudentes : durée Modbus, première variation PV observée, retour dans la tolérance, erreur finale, amplitude, sur-correction, oscillation suspectée et qualité/couverture de données.
- Diagnostics et capteurs de diagnostic Trace Recorder en lecture seule.

### Safety

- Le recorder ne crée aucun client Modbus, aucune tâche, aucune temporisation, aucune écriture et ne retourne aucune décision au Scheduler.
- Une commande avec télémétrie insuffisante ou trouée est classée **indéterminée**, jamais inefficace.

### Remaining validation

- Le mode diagnostic détaillé, le polling temporairement accéléré et les exports CSV/JSON restent réservés à Build004 RC4.

## [0.4.0-alpha.2] - 2026-07-22 — Build004 RC2

### Added

- Contrôleur prédictif : lorsque la puissance PV DTU et la puissance réseau sont fraîches, il calcule directement une limite DTU à partir de la consommation estimée et de la cible réseau.
- Correction fine bornée à 2 % pour les erreurs résiduelles sous le seuil prédictif ; le scheduler conserve le délai de stabilisation de 12 secondes.
- Contrats passifs `ContextAnalyzer`, `CalibrationManager` et `EnergyPolicyEngine`, avec la politique compatible V1 `ZeroInjectionPolicy`.
- Spécification d’architecture officielle dans `docs/Architecture-Specification.md`.

### Safety

- Les écritures, registres temporaires, confirmations sur les trois ports, modes Manuel/Simulation/Production et pauses de sécurité restent inchangés.
- Les nouveaux contrats Context, Calibration et Policy n’émettent aucune écriture et ne modifient pas encore le comportement de sécurité.

### Tests

- Ajout de tests unitaires pour le calcul prédictif, la correction fine et les contrats passifs Build004 RC2.

### Remaining validation

- Validation réelle en mode Simulation puis en Régulation automatique avant activation sur l’installation.
- Analyse de contexte avancée, calibration active et SolarFlow restent hors périmètre de Build004 RC2.

## [0.4.0-alpha.1] - 2026-07-17 — Build004

### Added

- Interface V1 simplifiée : modes affichés **Manuel**, **Simulation** et **Régulation automatique**, sans modifier les valeurs internes historiques.
- Curseur unique de limite temporaire manuelle, limité de 2 à 100 %, appliqué et confirmé sur les trois ports temporaires.
- Migration non destructive : les trois anciennes commandes manuelles par port sont conservées dans le registre Home Assistant, mais désactivées automatiquement par l’intégration.

- Stratégie Production optionnelle **Prise de contrôle** : trois écritures temporaires `0x06` confirmées établissent une limite de départ locale sans dépendre d'une relecture `0x03`; le délai de stabilisation reste obligatoire avant toute régulation.
- Option explicite de reprise automatique après redémarrage : elle ne s'applique qu'à un mode Production précédemment enregistré, à une stratégie Prise de contrôle, et après une connexion DTU réussie.
- Diagnostics séparant connexion DTU, lisibilité et cohérence des limites temporaires, source de la limite active, stratégie de démarrage et reprise automatique.
- Mode de validation des limites temporaires : **Compatibilité** par défaut, avec conservation d'une limite locale uniquement après les trois accusés de réception `0x06`; le mode **Strict** conserve l'exigence de relectures `0x03` fraîches et cohérentes.

- Acquisition configurable de la puissance réseau locale et contrôleur déterministe avec cible, zone morte, estimation W/% et pas maximal.
- Modes Disabled, Simulation et Production ; scheduler central avec délai de stabilisation de 12 secondes par défaut.
- Historique borné des décisions, diagnostics de contrôleur et collecte passive des données d'apprentissage.
- Abstraction `BatteryManager` neutre vis-à-vis du constructeur, réservée à V1.1 ; elle ne lit aucune batterie et n'influence pas la V1.
- Couche `EnergyManager` passive, indépendante du scheduler DTU, avec modèle multi-batteries et agrégats diagnostics de capacité de charge ; aucun adaptateur ni calcul EMS n'influence la régulation.
- Le mode du contrôleur est désormais persistant dans les options de l’intégration et restauré explicitement au démarrage ou au rechargement ; un repli invalide vers Désactivé est journalisé.
- En mode Désactivé, la puissance réseau locale reste publiée lorsqu’elle est disponible et le motif d’inactivité du planificateur est exposé.
- Les limites permanentes hors plage documentée journalisent leur valeur brute, deviennent uniquement indisponibles et sont supprimées temporairement des lectures répétées sans affecter le contrôle.
- L’interface Simulation expose désormais un état de planificateur cohérent et affiche la prochaine proposition de limite avec une indication explicite qu’aucune commande DTU ne sera envoyée.
- Les commandes manuelles et les lectures réelles de limites temporaires portent désormais des noms distincts. Les lectures connues restent visibles avec leur état de fraîcheur lors d’un échec ponctuel du coordinator.
- Les autorisations d’écriture manuelle et automatique sont désormais distinctes : l’interrupteur manuel ne bloque plus le scheduler Production, tandis que Simulation interdit toute écriture réelle.

### Safety

- La régulation automatique est suspendue après une écriture manuelle partielle ; aucune correction automatique n’est tentée avant une resynchronisation explicite réussie.
- Les seules écritures automatiques sont les limites temporaires des trois ports, suivies d'une relecture complète.
- Aucune intégration Zendure/SolarFlow, aucune écriture permanente, aucun PID ni retry automatique.
- Une erreur isolée d'une limite temporaire conserve la dernière valeur avec un état périmé et suspend les commandes Production jusqu'à trois lectures temporaires fraîches et cohérentes.
- Les limites permanentes sont strictement diagnostiques, lues au démarrage puis toutes les cinq minutes ; leur indisponibilité n'interrompt pas le contrôleur.
- Les lectures standard de télémétrie conservent désormais leur dernière valeur valide et leur état de fraîcheur individuellement ; une panne ponctuelle ne rend plus tout le coordinateur indisponible.
- Le client Modbus sérialise les requêtes, espace les trames de 150 ms, ferme la socket après une réponse vide, tronquée ou expirée, et applique un backoff asynchrone borné après plusieurs échecs globaux.
- Le mode Simulation dispose d'une limite virtuelle, respecte le scheduler et ne compte qu'une commande théorique réellement admissible ; il n'émet aucune écriture Modbus.
- Les noms d'entités et les libellés visibles du contrôleur sont francisés et les motifs de décision internes sont présentés avec leur libellé français.
- La puissance nominale photovoltaïque est maintenant un paramètre utilisateur persistant (3000 W par défaut pour l'installation actuelle). Le coefficient W/% est dérivé exclusivement de cette valeur et n'est plus réglable indépendamment.
- Simulation sépare strictement la limite DTU réelle, la limite calculée et la recommandation virtuelle. Elle attend désormais une variation physique supérieure à 30 W avant d'autoriser une nouvelle commande virtuelle.
- Les compteurs de décisions et de commandes sont maintenant explicitement comptés depuis le démarrage, indépendamment de l'historique borné à 200 enregistrements.
- Les entités de configuration et de contrôleur ne dépendent plus de la disponibilité globale du coordinateur Modbus ; elles restent visibles pendant une panne DTU.
- Le coordinateur sérialise désormais ses propres rafraîchissements, conserve le client TCP entre les lectures et sépare les cadences : puissance 10 s, énergie et limites temporaires 30 s, informations et limites permanentes 5 min.
- Après une erreur de transport, les dernières données valides restent publiées comme périmées pendant deux échecs globaux ; le client applique ensuite un backoff non bloquant de 5, 10, 20 puis 30 s.

## [0.3.0-alpha.1] - 2026-07-16 — Build003 RC1

### Added

- Lecture diagnostique `0x03` des limites de puissance temporaire et permanente des ports 1 à 3.
- Interrupteur local **Enable Manual DTU Writes**, désactivé à chaque démarrage.
- Entités Number seulement pour les ports temporaires dont la valeur est valide.

### Safety

- La seule écriture est `0x06` vers `0xD007`, `0xD00D` ou `0xD013`, avec une valeur entière de 2 à 100 %.
- Chaque écriture est suivie d'un contrôle de l'écho puis d'une relecture `0x03` identique.
- Les registres globaux et permanents ne peuvent pas être écrits. Aucune récupération par écriture automatique n'est effectuée après un échec.

### Changed
- Remplacement de pymodbus par un client Modbus TCP interne, limité à la fonction 0x04.

## [0.2.0-alpha.1] - 2026-07-16 — Build002

### Added

- Télémétrie Modbus TCP asynchrone exclusivement en lecture (fonction `0x04`).
- Mesures agrégées DTU, capteurs Home Assistant, diagnostics et décodage explicite des registres.

### Safety

- Aucune fonction ou méthode d'écriture Modbus n'est présente.

## [0.1.0] - 2026-07-16 — Build001 RC1

### Changed

- Remplacement de la dépendance `pymodbus` par une simple ouverture du port TCP du DTU avec un délai de cinq secondes.
- Aucune trame Modbus, lecture de registre ou écriture de registre n'est effectuée.

## [0.1.0] - 2026-07-14 — Build001

### Added

- Initialisation de l'intégration personnalisée `openems_zero_injection`.
- Configuration via l'interface Home Assistant du DTU Pro-S en Modbus TCP.
- DataUpdateCoordinator de connexion et reconnexion au DTU.
- Capteur de diagnostic de l'état de connexion.
- Tests du Config Flow, du client Modbus simulé, du coordinateur, du capteur et des diagnostics.
- Documentation d'installation et de sécurité.

### Safety

- Aucune lecture ou commande Modbus n'est émise dans ce build.
