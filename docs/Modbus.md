# Hoymiles DTU Pro-S — registres Build002

Source : *Technical Note — Hoymiles Modbus Protocol for DTU-Pro / DTU-Pro-S*, REV1.2, 2024-05-09. La note indique un firmware DTU Pro-S minimal **V2.22**. La validation sur le matériel réel `192.168.1.37:502` reste à effectuer.

Build002 utilise uniquement Modbus TCP fonction **0x04 — Read Input Registers**, Device ID `1`, timeout de cinq secondes. Aucune fonction d'écriture n'est implémentée.

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
