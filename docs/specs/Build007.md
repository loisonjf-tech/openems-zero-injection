# Build007 — Battery Priority

## Build007-B — activation conservatrice observée

Le mode `observed_conservative` est optionnel et désactivé par défaut. Il ne
pilote jamais la SolarFlow : il ajuste seulement la cible lue par le contrôleur
prédictif de `−40 W` à `−65 W` après trois mesures fraîches consécutives de
charge strictement supérieure à `50 W`. La marge est configurable et bornée à
`0…100 W`, avec `25 W` par défaut.

Une décharge supérieure à `50 W` sur une mesure fraîche, ou toute donnée
absente, stale, incohérente ou en défaut, annule immédiatement la confirmation
et restaure exactement la cible Zero Injection. `chargeMaxLimit` et le SOC ne
servent pas au calcul de puissance disponible dans cet incrément.

## Capacity release

Le mode optionnel `capacity_release` est distinct : avec un `chargeMaxLimit`
explicitement vérifié, frais et normalisé en W, il demande une libération DTU à
`100 %` tant que la batterie n’est pas pleine et reste sous sa saturation. Un
instantané cohérent à `< max - 100 W` suffit à libérer le DTU, y compris si la
puissance directionnelle reste à `0 W` sans nouvelle publication. La décharge
n’est pas un motif de repli. Trois publications directionnelles fraîches et
distinctes à `>= max - 50 W` font revenir à Zero Injection ; entre les deux
seuils, l’état précédent est conservé. Le SOC est considéré plein seulement à
`>= 100 %` dans ce premier incrément. `chargeMaxLimit` est une capacité de
configuration : après une première publication valide et vérifiée postérieure
au démarrage, elle est conservée en mémoire jusqu'à une publication explicitement
invalide ou indisponible ; elle n'est jamais restaurée après redémarrage.

## Alpha.3 — observabilité cohérente

Les diagnostics de dernière commande sont extraits d'une unique `CommandTrace`.
Ils ne fusionnent jamais une limite DTU relue plus tard avec une décision plus
ancienne. Lorsqu'aucune commande n'a de trace, ce fait est explicite.

La SolarFlow expose aussi la fraîcheur indépendante de ses sources obligatoires
SOC et puissance directionnelle. Cette observation n'assouplit pas encore les
règles de santé ni les conditions de priorité batterie.

## Objective

Build007 compares a generic `BatteryPriorityStrategy` with the established
`ZeroInjectionStrategy` without changing Production control.

## Build007-A safety boundary

- Production used `ZeroInjectionStrategy` exclusively in Build007-A.
- `BatteryPriorityStrategy` is evaluated only in Simulation.
- It issues no battery command, DTU command, Modbus request, task or polling.
- The Predictive Controller receives the unchanged Zero Injection target.

Build007-B is the sole exception: its explicit, disabled-by-default
`observed_conservative` mode may supply the bounded candidate target described
above only after its charge confirmations have succeeded.

## Candidate calculation

With `T = target_grid_power_w`, `R = remaining_charge_power_w`, and both
configured bounds equal to `25 W`:

```text
reserve_w = min(R, 25 W, 25 W)
candidate_target_grid_power_w = T - reserve_w
T - 25 W <= candidate_target_grid_power_w <= T
```

Negative grid power represents injection. The candidate is a bounded policy
target only: `R` is a potential local battery absorption capacity, not an
observed charge and not a guaranteed reduction of injection. The Trace Recorder
stores `candidate_expected_storage_gain_w = reserve_w` as a theoretical value.

## Strict fallback

The candidate exactly equals `T` with a stable fallback code when no battery is
present; data is unavailable, stale, inconsistent or faulted; capacity is
unknown or partial; the battery is full from a reliable capacity or explicit
state; or the configured target is not export-oriented.

## Diagnostics and trace

Les diagnostics et chaque trace de commande doivent associer, dans un même
instantané acquis par le cycle existant, la puissance nominale configurée, la
limite demandée, sa puissance maximale théorique, la puissance active DTU, les
trois limites temporaires, l'âge de leur dernière confirmation et l'état de
stabilisation du Scheduler. Cette instrumentation ne doit provoquer ni lecture
Modbus supplémentaire, ni écriture, ni changement de cadence.

Diagnostics expose the effective target, candidate target, delta, expected
storage gain, eligible resources and fallback reason. Trace Recorder keeps a
bounded passive comparison history. No historical Scheduler or controller field
is changed.
