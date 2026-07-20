# Changelog

Toutes les évolutions notables sont documentées dans ce fichier.

## [0.4.0-alpha.1] - 2026-07-17 — Build004

### Added

- Stratégie Production optionnelle **Prise de contrôle** : trois écritures temporaires `0x06` confirmées établissent une limite de départ locale sans dépendre d'une relecture `0x03`; le délai de stabilisation reste obligatoire avant toute régulation.
- Option explicite de reprise automatique après redémarrage : elle ne s'applique qu'à un mode Production précédemment enregistré, à une stratégie Prise de contrôle, et après une connexion DTU réussie.
- Diagnostics séparant connexion DTU, lisibilité et cohérence des limites temporaires, source de la limite active, stratégie de démarrage et reprise automatique.
- Mode de validation des limites temporaires : **Compatibilité** par défaut, avec conservation d'une limite locale uniquement après les trois accusés de réception `0x06`; le mode **Strict** conserve l'exigence de relectures `0x03` fraîches et cohérentes.
- Le passage explicite du sélecteur vers Production active automatiquement l'interrupteur des écritures manuelles DTU; ce verrou repasse sur arrêt au démarrage et reste indépendant de l'autorisation automatique du scheduler.

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

- Production exige trois mesures réseau valides, des limites temporaires cohérentes et l'interrupteur Build003 activé.
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
