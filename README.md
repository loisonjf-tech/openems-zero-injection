# OpenEMS Zero Injection

Intégration Home Assistant locale destinée à piloter un Hoymiles DTU Pro-S afin de minimiser les échanges réseau dans une installation monophasée, en tenant compte d'une batterie Zendure SolarFlow 800 Plus.

## État du projet

**Build004 — fondation expérimentale du contrôleur de zéro injection.** Le projet acquiert une puissance réseau locale, calcule une consigne DTU déterministe, et applique un scheduler de sécurité. Il n'intègre pas encore SolarFlow, Zendure ou une logique de batterie.

Version actuelle : **V0.4.0-alpha.1 / Build004**.

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

Le mode du contrôleur est **Disabled** après chaque démarrage. **Simulation** calcule et explique les décisions sans écrire. **Production** reste verrouillé tant que **Enable Manual DTU Writes** est désactivé. Il exige trois mesures réseau valides et trois limites temporaires identiques avant une éventuelle écriture. La consigne est limitée à 5 % par commande et espacée de 12 secondes par défaut.

> **Avertissement :** Build004 est expérimental. Le mode Production peut modifier la puissance photovoltaïque réelle. Les premiers essais doivent être réalisés sous surveillance.

## Sécurité

Le client interne utilise uniquement les fonctions Modbus TCP `0x03`, `0x04` et `0x06`. Les écritures Build004 sont exclusivement temporaires vers `0xD007`, `0xD00D` et `0xD013`, vérifiées par relecture. Il n'implémente pas `0x10`, aucune écriture permanente ou globale, aucun PID ni aucune logique batterie.

## Tests

Dans un environnement de développement Home Assistant 2026.7.2 compatible avec Python 3.14.2 ou plus récent, installez les dépendances de test puis exécutez `pytest`. La suite couvre le Config Flow, le client Modbus simulé, le coordinateur, le capteur et les diagnostics.

## Feuille de route

1. **Build004** : valider sous surveillance le mode Simulation, puis Production, sur le DTU réel.
2. **Build005** : seulement après validation réelle des comportements Build004.
