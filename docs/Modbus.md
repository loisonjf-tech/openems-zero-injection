# Hoymiles DTU Pro-S — registres Build003

Source : *Technical Note — Hoymiles Modbus Protocol for DTU-Pro / DTU-Pro-S*, REV1.2, 2024-05-09. La note est applicable à partir du logiciel **V00.00.22**. La validation sur le matériel réel `192.168.1.37:502` reste à effectuer.

Build003 utilise un client Modbus TCP interne basé uniquement sur la bibliothèque standard Python, Device ID `1` et timeout de cinq secondes. La télémétrie emploie **0x04 — Read Input Registers**. La découverte des limites emploie **0x03 — Read Holding Registers**. La seule écriture existante est **0x06 — Write Single Register**, strictement limitée aux trois registres de limite temporaire par port, après activation locale explicite.

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

La note REV1.2, section 4.4.7, définit ces registres comme des `uint16` big-endian. La valeur est directement un pourcentage, sans coefficient. Pour les HMS de troisième génération, la plage autorisée est de **2 à 100 %**.

| Port | Registre temporaire | Registre permanent | Lecture | Écriture Build003 | Statut réel |
| --- | ---: | ---: | --- | --- | --- |
| 1 | `0xD007` | `0xD008` | `0x03` | `0x06` temporaire seulement | à valider |
| 2 | `0xD00D` | `0xD00E` | `0x03` | `0x06` temporaire seulement | à valider |
| 3 | `0xD013` | `0xD014` | `0x03` | `0x06` temporaire seulement | à valider |

Les registres globaux `0xD001` et `0xD002` ne sont ni lus ni écrits par ce build. Les registres permanents `0xD008`, `0xD00E` et `0xD014` sont lus uniquement. Après toute écriture temporaire autorisée, la réponse `0x06` doit répéter l'adresse et la valeur, puis le même registre est relu avec `0x03` et comparé. Aucune écriture de restauration n'est tentée en cas d'erreur.
