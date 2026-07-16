# OpenEMS Zero Injection

Intégration Home Assistant locale destinée à piloter un Hoymiles DTU Pro-S afin de minimiser les échanges réseau dans une installation monophasée, en tenant compte d'une batterie Zendure SolarFlow 800 Plus.

## État du projet

**Build003 RC1 — lecture diagnostique et pilotage manuel temporaire par port.** Le projet lit les registres de télémétrie et les six limites de puissance documentées. Une écriture temporaire est possible uniquement après activation explicite de l'interrupteur de sécurité local.

Version actuelle : **V0.3.0-alpha.1 / Build003 RC1**.

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

## Limite de puissance manuelle (Build003 RC1)

Les capteurs diagnostiques affichent les limites temporaire et permanente des ports 1 à 3. Les entités Number ne sont créées que pour les ports dont la limite temporaire retourne une valeur valide lors du démarrage.

Avant une modification manuelle, activez **Enable Manual DTU Writes**. Il est toujours désactivé après un redémarrage. Les seules écritures possibles sont des limites **temporaires** `2–100 %` vers `0xD007`, `0xD00D` ou `0xD013`. Chaque écriture `0x06` doit être confirmée par son écho Modbus, puis par une relecture immédiate `0x03` du même registre. Une erreur conserve la dernière valeur confirmée et ne déclenche aucune nouvelle écriture.

## Sécurité

Le client interne utilise uniquement les fonctions Modbus TCP `0x03`, `0x04` et, exclusivement derrière l'interrupteur de sécurité, `0x06`. Il n'implémente pas `0x10`, aucune écriture permanente, aucune écriture globale et aucune fonction de régulation automatique.

## Tests

Dans un environnement de développement Home Assistant 2026.7.2 compatible avec Python 3.14.2 ou plus récent, installez les dépendances de test puis exécutez `pytest`. La suite couvre le Config Flow, le client Modbus simulé, le coordinateur, le capteur et les diagnostics.

## Feuille de route

1. **Build003 RC1** : valider les ports actifs et la limite temporaire sur le DTU réel.
2. **Build004** : uniquement après validation explicite du matériel et d'une spécification approuvée.
