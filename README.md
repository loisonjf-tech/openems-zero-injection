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

Le mode du contrôleur est **Désactivé** après chaque démarrage. **Simulation** calcule et explique les décisions sans écrire. La limite DTU réelle reste exclusivement celle lue dans les registres Modbus ; la limite simulée est une recommandation distincte. Après une commande virtuelle, Simulation attend une variation physique significative de la puissance réseau ou DTU avant toute nouvelle commande virtuelle : l'expiration du délai de 12 secondes ne suffit pas. **Production** reste verrouillé tant que **Autoriser les écritures manuelles DTU** est désactivé. Il exige trois mesures réseau valides et trois limites temporaires identiques, fraîches et cohérentes avant une éventuelle écriture.

La **Puissance nominale de l’installation photovoltaïque** est configurée manuellement, persistée dans les options et vaut `3000 W` par défaut pour l'installation actuelle. Le coefficient de conversion est toujours calculé par `puissance nominale / 100` : `3000 W` donne `30 W/%`, `4000 W` donne `40 W/%`. Cette donnée n'est ni lue ni déduite depuis la DTU ; une future valeur détectée par la DTU, si elle est validée, restera informative.

> **Avertissement :** Build004 est expérimental. Le mode Production peut modifier la puissance photovoltaïque réelle. Les premiers essais doivent être réalisés sous surveillance.

## Sécurité

Le client interne utilise uniquement les fonctions Modbus TCP `0x03`, `0x04` et `0x06`. Les écritures Build004 sont exclusivement temporaires vers `0xD007`, `0xD00D` et `0xD013`, vérifiées par relecture. Les registres permanents (`0xD008`, `0xD00E`, `0xD014`) sont seulement diagnostiques et lus toutes les cinq minutes, jamais écrits. Il n'implémente pas `0x10`, aucune écriture permanente ou globale, aucun PID ni aucune logique batterie.

Les lectures Modbus sont strictement sérialisées et espacées de 150 ms. Une erreur ponctuelle conserve la dernière valeur connue, signalée comme périmée avec sa date et son compteur d'échecs ; elle ne devient jamais `0` artificiellement. Les erreurs de socket, timeout ou réponse incomplète ferment la connexion TCP afin que le cycle normal suivant la recrée. Après plusieurs échecs globaux, la reconnexion applique un délai asynchrone borné.

Le contrôleur vérifie son tick toutes les trois secondes, mais n'évalue qu'un seul snapshot cohérent par nouvelle génération de mesures. La mesure réseau est valable 10 secondes ; la télémétrie DTU et les limites temporaires restent utilisables 25 secondes. Les limites permanentes sont diagnostiques, lues au démarrage puis toutes les cinq minutes, et ne suspendent jamais le contrôleur.

## Tests

Dans un environnement de développement Home Assistant 2026.7.2 compatible avec Python 3.14.2 ou plus récent, installez les dépendances de test puis exécutez `pytest`. La suite couvre le Config Flow, le client Modbus simulé, le coordinateur, le capteur et les diagnostics.

## Feuille de route

1. **Build004** : valider sous surveillance le mode Simulation, puis Production, sur le DTU réel.
2. **Build005** : seulement après validation réelle des comportements Build004.
