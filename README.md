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

Le mode du contrôleur est **Désactivé** après chaque démarrage. **Simulation** calcule et explique les décisions sans écrire ni utiliser le délai de stabilisation de Production. La limite DTU réelle reste exclusivement celle lue dans les registres Modbus ; la limite simulée est une recommandation distincte, recalculée uniquement lors d'une mesure significativement différente. Lors d'un passage explicite vers **Production**, **Autoriser les écritures manuelles DTU** est activé automatiquement pour rendre les commandes manuelles disponibles ; il repasse volontairement sur arrêt après un redémarrage. L'autorisation automatique du scheduler est distincte de cet interrupteur.

Le mode de validation des limites temporaires est **Compatibilité** par défaut. Après trois écritures temporaires réussies et leurs accusés de réception `0x06`, il conserve localement la consigne confirmée si certains DTU ne permettent pas de relire fiablement `0xD007`, `0xD00D` ou `0xD013`. Le mode **Strict** exige au contraire trois relectures `0x03` fraîches, identiques et valides. Dans les deux cas, une erreur d'écriture ou une perte de communication arrête les commandes ; aucune valeur `0`, `2` ou `100` n'est inventée.

La **Puissance nominale de l’installation photovoltaïque** est configurée manuellement, persistée dans les options et vaut `3000 W` par défaut pour l'installation actuelle. Le coefficient de conversion est toujours calculé par `puissance nominale / 100` : `3000 W` donne `30 W/%`, `4000 W` donne `40 W/%`. Cette donnée n'est ni lue ni déduite depuis la DTU ; une future valeur détectée par la DTU, si elle est validée, restera informative.

> **Avertissement :** Build004 est expérimental. Le mode Production peut modifier la puissance photovoltaïque réelle. Les premiers essais doivent être réalisés sous surveillance.

## Sécurité

Le client interne utilise uniquement les fonctions Modbus TCP `0x03`, `0x04` et `0x06`. Les écritures Build004 sont exclusivement temporaires vers `0xD007`, `0xD00D` et `0xD013`, vérifiées par relecture. Les registres permanents (`0xD008`, `0xD00E`, `0xD014`) sont seulement diagnostiques et lus toutes les cinq minutes, jamais écrits. Il n'implémente pas `0x10`, aucune écriture permanente ou globale, aucun PID ni aucune logique batterie.

Les lectures Modbus sont strictement sérialisées, sans temporisation artificielle entre les trames, sur une connexion TCP persistante. Le capteur **Temps de réponse DTU** représente la dernière transaction Modbus, tandis que les diagnostics détaillent chaque phase et la durée totale du cycle. Une erreur ponctuelle conserve la dernière valeur connue, signalée comme périmée avec sa date et son compteur d'échecs ; elle ne devient jamais `0` artificiellement. Les erreurs de socket, timeout ou réponse incomplète ferment la connexion TCP. Les nouvelles tentatives respectent un backoff non bloquant de 5, 10, 20 puis 30 secondes.

Le contrôleur vérifie son tick toutes les trois secondes, mais n'évalue qu'un seul snapshot cohérent par nouvelle génération de mesures. La puissance DTU est lue toutes les 10 secondes, l'énergie et les limites temporaires toutes les 30 secondes, et les informations générales ainsi que les limites permanentes toutes les cinq minutes. Les limites temporaires restent utilisables 65 secondes ; les limites permanentes sont diagnostiques et ne suspendent jamais le contrôleur.

En **Simulation**, l’état du planificateur indique explicitement qu’il attend de nouvelles mesures après une proposition. La capteur **Prochaine limite commandée** affiche alors cette proposition avec les attributs `execution_mode: Simulation` et `is_simulation: true` : aucune écriture DTU n’est effectuée. Le nombre de compteurs déclaré par le DTU est seulement diagnostique ; la régulation utilise exclusivement le capteur de puissance réseau configuré dans Home Assistant.

Le mode sélectionné du contrôleur est enregistré dans les options de l’intégration et restauré après un redémarrage ou un rechargement. Le journal indique le mode restauré et sa source. En mode **Désactivé**, la puissance réseau reste visible lorsqu’elle est lisible : cela distingue explicitement une désactivation volontaire d’un capteur réseau indisponible.

Une limite permanente hors de la plage documentée est traitée comme une donnée diagnostique indisponible. Sa valeur brute est journalisée une fois, puis le registre optionnel est temporairement suspendu ; elle ne modifie ni l’état de connexion ni les limites temporaires utilisées par le contrôleur.

Les trois `number` de limites temporaires sont des **commandes manuelles** par port. Les trois `sensor` portant le terme **réelle** sont des lectures du dernier snapshot du coordinator, donc la valeur lue ou mise en cache après vérification DTU. Ils conservent leur `entity_id` existant lors du renommage. Le scheduler automatique appelle directement le coordinator et ne lit jamais ces entités `number`.

L’interrupteur **Autoriser les écritures manuelles DTU** ne déverrouille que les commandes `number` manuelles. En Production, le scheduler utilise une autorisation distincte : mode Production, connexion DTU valide et limites temporaires fraîches et identiques (**Strict**) ou dernière consigne confirmée par les trois échos d’écriture (**Compatibilité**), puis valeur de `2` à `100 %`. En Simulation, aucune autorisation ne permet d’envoyer une écriture Modbus réelle.

Les entités de configuration et du moteur local (mode, interrupteur de sécurité, paramètres, compteurs et dernier état) restent disponibles lors d'une indisponibilité DTU. Seules les entités dont la valeur provient directement du Modbus peuvent devenir indisponibles.

## Préparation EMS passive

Une couche `EnergyManager` indépendante du scheduler DTU centralise dès maintenant un inventaire passif de batteries autonomes. Elle publie seulement des diagnostics (nombre de batteries, puissances de charge maximale et actuelle, capacité de charge restante, état). Aucun adaptateur Zendure n'est encore présent, aucune batterie n'est lue, et ces calculs ne participent à aucune décision ni commande du contrôleur.

## Tests

Dans un environnement de développement Home Assistant 2026.7.2 compatible avec Python 3.14.2 ou plus récent, installez les dépendances de test puis exécutez `pytest`. La suite couvre le Config Flow, le client Modbus simulé, le coordinateur, le capteur et les diagnostics.

## Feuille de route

1. **Build004** : valider sous surveillance le mode Simulation, puis Production, sur le DTU réel.
2. **V1.1** : adaptateurs de batterie derrière la couche EMS passive, avec une éventuelle politique Priorité Batterie validée séparément.
3. **Build005** : seulement après validation réelle des comportements Build004 et V1.1.
