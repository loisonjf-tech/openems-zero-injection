# OpenEMS Zero Injection — Build002

**Projet :** OpenEMS Zero Injection  
**Version cible :** `0.2.0-alpha.1`  
**Build :** `002`  
**Statut :** approuvée  
**Cible :** Hoymiles DTU Pro-S, Home Assistant 2026.7.2, monophasé

## Objectif

Build002 fait évoluer Build001 vers une communication Modbus TCP asynchrone en lecture seule. Il établit une connexion au DTU, lit exclusivement les registres documentés, décode les valeurs, expose les premières mesures et gère les pertes de communication. Il ne met en oeuvre aucune logique de zéro injection.

## Référence et limites

La référence est *Technical Note — Hoymiles Modbus Protocol for DTU-Pro / DTU-Pro-S — REV1.2 — 2024-05-09*. Les registres, tailles, coefficients et état de validation sont centralisés dans `docs/Modbus.md` et `registers.py`. Les seules lectures autorisées utilisent Modbus fonction `0x04`, Device ID `1`, délai de cinq secondes et intervalle de dix secondes.

Le premier registre lu est `REG_INVERTER_COUNT` (`0x3004`). Après réponse valide, Build002 lit uniquement les informations DTU et les blocs agrégés listés dans `docs/Modbus.md`. Les valeurs brutes sont journalisées en debug. La puissance réactive reste expérimentale et n'est pas exposée.

## Données et entités

Le coordinateur retourne `DtuMeasurements`, modèle immuable indépendant des entités. Les capteurs sont : connexion, compteurs, micro-onduleurs, puissance active, énergie quotidienne, énergie totale, temps de réponse et dernière communication. Ils sont rattachés à un seul appareil Hoymiles DTU Pro-S. Une valeur non décodée devient indisponible sans supprimer son entité.

## Sécurité

Il n'existe aucune écriture Modbus, fonction `0x06` ou `0x10`, limitation de puissance, commande d'onduleur, zéro injection, PID, Smart Meter, SolarFlow, batterie, prévision, service de commande, ni entité de pilotage. Aucun tag ni release ne doit être créé avant validation réelle sur `192.168.1.37:502`.

## Validation obligatoire

La CI emploie Python 3.14.2, valide JSON et syntaxe, puis exécute tous les tests sans contacter la DTU réelle. La validation sur l'installation doit confirmer la plausibilité des mesures et l'absence totale d'écriture Modbus.
