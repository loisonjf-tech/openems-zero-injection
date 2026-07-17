# Changelog

Toutes les évolutions notables sont documentées dans ce fichier.

## [0.4.0-alpha.1] - 2026-07-17 — Build004

### Added

- Acquisition configurable de la puissance réseau locale et contrôleur déterministe avec cible, zone morte, estimation W/% et pas maximal.
- Modes Disabled, Simulation et Production ; scheduler central avec délai de stabilisation de 12 secondes par défaut.
- Historique borné des décisions, diagnostics de contrôleur et collecte passive des données d'apprentissage.

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
