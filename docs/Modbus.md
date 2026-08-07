# Hoymiles DTU Pro-S — registres Build004

Source : *Technical Note — Hoymiles Modbus Protocol for DTU-Pro / DTU-Pro-S*, REV1.2, 2024-05-09. La note est applicable à partir du logiciel **V00.00.22**. La validation sur le matériel réel `192.168.1.37:502` reste à effectuer.

Build004 utilise le même client Modbus TCP interne, Device ID `1` et timeout de cinq secondes. La télémétrie emploie **0x04 — Read Input Registers**. Les limites emploient **0x03 — Read Holding Registers**. La seule écriture automatique existante est **0x06 — Write Single Register**, strictement limitée aux trois registres de limite temporaire par port, après activation locale explicite et contrôle du scheduler.

Les mots de 16 bits et les octets sont décodés dans l'ordre big-endian documenté. Les nombres multi-mots sont assemblés du mot le plus significatif vers le moins significatif.

| Registre | Adresse | Taille | Type | Coefficient | Unité | Validation réelle |
| --- | ---: | ---: | --- | ---: | --- | --- |
| `REG_DTU_SERIAL` | `0x3000` | 3 | 3 × uint16 | 1 | — | non validé, masqué dans diagnostics |
| `REG_METER_COUNT` | `0x3003` | 1 | uint16 | 1 | — | à valider |
| `REG_INVERTER_COUNT` | `0x3004` | 1 | uint16 | 1 | — | premier registre lu |
| `REG_TOTAL_ENERGY` | `0x3100` | 4 | uint64 | 1 | Wh | à valider |
| `REG_DAILY_ENERGY` | `0x3104` | 4 | uint64 | 1 | Wh | à valider |
| `REG_TOTAL_ACTIVE_POWER` | `0x3108` | 2 | uint32 | 0,1 | W | à valider |
| `REG_TOTAL_REACTIVE_POWER` | `0x310A` | 2 | signé à confirmer | 0,1 | var | expérimental, non exposé |

La puissance réactive est lue pour validation technique mais son caractère signé n'est pas confirmé ; elle n'est donc pas exposée comme entité Build002.

## Limites de puissance Build003

La note REV1.2, section 4.4.7, définit ces registres comme des `uint16` big-endian. La valeur est présentée comme **Percentage: Temporary Limit Active Power**, sans coefficient, et la plage autorisée pour les HMS de troisième génération est de **2 à 100 %**.

> La note ne définit pas explicitement le dénominateur de ce pourcentage : elle
> ne dit pas s'il s'agit de la puissance nominale AC d'un micro-onduleur, d'un
> groupe associé à un port, de l'installation totale, ni comment la limite se
> comporte lorsque la puissance solaire disponible est plus faible. OpenEMS
> enregistre donc sa référence théorique `puissance_nominale_configurée × %`
> uniquement pour corrélation terrain ; elle ne doit pas être interprétée comme
> une sémantique firmware validée.

| Port | Registre temporaire | Registre permanent | Lecture | Écriture Build003 | Statut réel |
| --- | ---: | ---: | --- | --- | --- |
| 1 | `0xD007` | `0xD008` | `0x03` | `0x06` temporaire seulement | à valider |
| 2 | `0xD00D` | `0xD00E` | `0x03` | `0x06` temporaire seulement | à valider |
| 3 | `0xD013` | `0xD014` | `0x03` | `0x06` temporaire seulement | à valider |

Les registres globaux `0xD001` et `0xD002` ne sont ni lus ni écrits par ce build. Les registres temporaires sont lus au démarrage puis toutes les 30 secondes. En mode **Strict**, trois lectures `0x03` fraîches et identiques sont exigées avant et après une commande. En mode **Compatibilité**, les trois accusés de réception `0x06` d'une écriture commune établissent la limite locale confirmée lorsque les relectures `0x03` ne sont pas fiables. La stratégie optionnelle **Prise de contrôle** utilise exclusivement ces trois échos `0x06` pour créer la première référence locale. Les registres permanents `0xD008`, `0xD00E` et `0xD014` sont lus au démarrage puis toutes les cinq minutes uniquement à des fins de diagnostic : leur indisponibilité ne suspend jamais le contrôleur. Aucune écriture de restauration ni répétition automatique n'est tentée en cas d'erreur.

Toutes les lectures et écritures du client passent par un verrou asynchrone unique, sans temporisation artificielle entre les trames. Les journaux de debug indiquent l'adresse, le nombre de registres, l'unité Modbus, la durée, le résultat, l'exception éventuelle et le nombre de tentatives. Une réponse vide, tronquée, une erreur de socket ou un timeout ferme immédiatement la socket ; la reconnexion est ensuite éligible après 5, 10, 20 puis 30 secondes, sans bloquer Home Assistant. Après deux échecs d'un registre permanent, ce registre est suspendu 30 minutes. Chaque registre conserve indépendamment sa dernière valeur valide, son horodatage, son état frais/périmé et son nombre d'échecs consécutifs.
