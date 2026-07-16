# Changelog

Toutes les évolutions notables sont documentées dans ce fichier.

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
