# OpenEMS Zero Injection

Intégration Home Assistant locale destinée à piloter un Hoymiles DTU Pro-S afin de minimiser les échanges réseau dans une installation monophasée, en tenant compte d'une batterie Zendure SolarFlow 800 Plus.

## État du projet

**Build002 — télémétrie Modbus en lecture seule.** Le projet lit un ensemble limité de registres documentés du DTU Pro-S et expose les premières mesures. Il ne contient aucune logique de régulation ni aucune écriture Modbus.

Version actuelle : **V0.2.0-alpha.1 / Build002**.

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

## Sécurité

Le Build002 utilise `pymodbus==3.11.4` uniquement avec la fonction Modbus `0x04` (lecture de registres d'entrée), avec un délai maximal de cinq secondes. Il ne contient aucune méthode d'écriture et ne pilote aucun onduleur. Consultez `docs/Modbus.md` avant toute validation réelle.

## Tests

Dans un environnement de développement Home Assistant 2026.7.2 compatible avec Python 3.14.2 ou plus récent, installez les dépendances de test puis exécutez `pytest`. La suite couvre le Config Flow, le client Modbus simulé, le coordinateur, le capteur et les diagnostics.

## Feuille de route

1. **Build002** : lecture seule des registres DTU documentés (en validation réelle).
2. **Build003** : diagnostic enrichi et tests d'intégration après validation réelle.
