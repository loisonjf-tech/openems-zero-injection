# Changelog

Toutes les évolutions notables sont documentées dans ce fichier.

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
