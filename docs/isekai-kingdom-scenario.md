# Isekai Kingdom Grid Scenario

Working scenario design for a more complex InfoSim setup. This document records
the worldbuilding constraints and the first-pass system shape. It is not a
balance document yet.

## Core Pitch

The player rules a fantasy kingdom through a King who owns the capital and
governs a 5x5 board of noble-held regions. The map is small, but every region
has a different economic pressure, population mix, political owner, settlement
layout, and reporting chain.

The scenario should stress the core InfoSim question: can the King maintain a
kingdom when food, trade, soldiers, monster reports, taxes, prejudice, and noble
ambition all move through delayed and biased institutions?

The tone is fantasy isekai, but the isekai premise is flavor. The King does not
need special powers or an explicit system interface.

## Map

The kingdom is a 5x5 grid.

```text
      A     B     C     D     E
   +-----+-----+-----+-----+-----+
1  | A1  | B1  | C1  | D1  | E1  |  friendly empire border
   +-----+-----+-----+-----+-----+
2  | A2  | B2  | C2  | D2  | E2  |
   +-----+-----+-----+-----+-----+
3  | A3  | B3  | C3  | D3  | E3  |  C3 is always the capital
   +-----+-----+-----+-----+-----+
4  | A4  | B4  | C4  | D4  | E4  |
   +-----+-----+-----+-----+-----+
5  | A5  | B5  | C5  | D5  | E5  |  ocean coast
   +-----+-----+-----+-----+-----+
forest border                         mountain border
```

Movement and courier travel can use all eight neighboring directions, including
diagonals.

Fixed geography:

- `C3` is always the capital.
- `C1` is the major northern trade port into the friendly empire.
- `C5` is the major southern ocean trade port.
- Row `1` borders a friendly empire. It provides external trade and a reason to
  station border guards. Border guard pressure tapers west and east from `C1`.
- Column `A` borders a massive forest. Forestry and herb gathering are better
  there, but deeper forest exploitation risks conflict with isolationist forest
  elves.
- Column `E` borders mountains. Mining ore is better there.
- Row `5` borders the ocean. Agriculture and trade are stronger there, with
  trade strongest near `C5`.
- Interior regions receive cross-bleed from nearby bonuses, so most regions are
  somewhat useful rather than blank.

## Ownership

Every region is owned by a Noble. A Noble may also be a Royal. The King is both
a Noble and a Royal.

The ruler title can be neutralized in later UI and docs. This document uses
`King` because that is the current prototype's apex title, but the scenario can
present the apex as `Ruler`, or choose `King` / `Queen` per generated character.

Starting ownership rules:

- The King always owns `C3`.
- The King also starts with one random non-capital region.
- The King's second region must not be connected to `C3`.
- The King's second region must not be on row `1`.
- The King's second region must not be in column `A`.
- The King's second region should usually be mostly Agricultural, making it a
  food-tax supplement for the crown.
- Every non-King Noble owns at least one region.
- Holdings should be mostly contiguous, but fragments are allowed. A powerful
  noble might hold a mountain mining region while being based in the southwest.
- There are randomly `0-2` Royals besides the King.
- Royals are more politically powerful by default and have more pull with the
  King.
- Newly generated Nobles may be related to existing Nobles. If their relation
  reaches the ruling family, they become Royals.

If the King revokes a Noble title, the affected region returns to the King as a
vacant holding. The King should generally reassign it after a delay framed as
deliberation. A greedy King may keep revoked regions longer, but this should
increase distrust among other Nobles.

All Nobles are direct vassals of the King. The board is intentionally too small
for nested Noble hierarchies.

Actors have a small chance of random death. If the King dies, succession passes
to the strongest Royal. If no Royal exists, succession passes to the strongest
Noble. "Strongest" can be a scenario score combining held regions, army
strength, stockpiles, title prestige, and political support.

## Region Shape

Each region contains `0-3` settlements.

Settlement sizes:

- `village`
- `town`
- `city`

Settlement specializations:

- `None`
- `Agricultural`
- `Mining`
- `Military`
- `Production`
- `Trade`

New settlements start as `None` and empty. They do not consume existing pops to
create. Migration fills them over time, and empty settlements should have high
migration pull.

Changing broad specialization requires passing through `None`. Resource focus
inside a broad specialization can change directly.

Examples:

- Agricultural focus can switch between `food`, `lumber`, and `herbs`.
- Production focus can switch between `luxury goods`, `wares`, and `weapons`.
- Trade focus can switch between `money`, `luxury goods`, or a balance of both.

Agricultural settlements cannot exist in a region with two Mining settlements.
The lore reason is mining pollution.

## Resources

Agricultural resources:

- `food`
- `lumber`
- `herbs`

Mining resource:

- `ore`

Production resources:

- `luxury goods`
- `wares`
- `weapons`

Trade resource:

- `money`

Military resources:

- `soldiers`
- `warriors`

Population and military resources are race-split. For example, a region may
have `human pops`, `dwarf pops`, `orc soldiers`, and `elf warriors`.

## Population

All pops are adults for scenario purposes. Pops do not interbreed.

Pop races:

- `human`
- `elf`
- `orc`
- `beast-man`
- `dwarf`
- `demon`

Humans are the middle-of-the-line baseline. Other races should be broadly
balanced by having different strengths, weaknesses, and settlement preferences.
A future balance pass can tune the exact values, but the intended first-pass
shape is:

| Race | Economic Lean | Military Lean | Preferences | Notes |
| --- | --- | --- | --- | --- |
| human | balanced | balanced | moderate everywhere | Default reliability baseline. |
| elf | herbs, lumber, scouting | accurate scouts, weaker heavy troops | forests, low pollution | Forest elves may treat kingdom elves more gently. |
| orc | food, weapons labor | strong soldiers, high warrior chance | space, military settlements | May suffer under cramped cities. |
| beast-man | food, scouting, local travel | fast response, good guards | rural and border regions | Useful against monsters. |
| dwarf | mining, wares, weapons | strong defenders | mountains, production | Dislike poor ore access and forest overreach. |
| demon | luxury goods, magic-adjacent crafts | disciplined elite potential | cities, trade, production | Not inherently evil. Social suspicion may be common. |

Actors can be any race. Mayors, guards, Nobles, Royals, and the King can all be
from any pop kind. Some actors may be racist to varying degrees against some or
all other races. Prejudice can affect both decisions and direct population
pressure: migration, unrest, hiring, tax exemptions, report interpretation, and
appointments.

Actors may also have positive race preferences. A human Noble might strongly
favor dwarfs, an elf Mayor might prefer beast-men as guards, or a demon trader
might trust humans more than other demons. These preferences should be
asymmetric and personal rather than purely race-wide. Positive preference can
affect appointments, aid, settlement focus, tax exemptions, report trust, and
migration pull just as prejudice affects those systems in the other direction.

## Settlement Capacity And Migration

Each settlement size has a population capacity.

- Over-capacity creates penalties and migration push.
- Migration is only one over-capacity consequence.
- Under-population creates a smaller efficiency penalty because the settlement
  cannot fully use its infrastructure.
- New empty settlements have strong migration pull.

Each settlement should have a migration pull value and migration push value.
Inputs may include:

- free capacity
- overcrowding
- shortages of food, herbs, or wares
- monster threat
- border safety
- race preference match
- local prejudice
- settlement size
- specialization
- tax level
- nearby trade access
- recent attacks
- whether the mayor is trusted

Migration should create delayed feedback. A Noble may overbuild, mismanage
taxes, or ignore monster warnings, then later wonder why a city has hollowed out
or why a new village filled with the "wrong" race according to that Noble's
prejudice.

## Production

Agricultural settlements produce their focused resource for free based on:

- population
- settlement size
- regional geography
- race effectiveness
- same-specialization clustering bonuses
- local penalties such as monsters, unrest, or pollution

Mining settlements produce `ore`.

Production settlements consume `lumber` and `ore` to produce one focused
resource:

- `luxury goods`
- `wares`
- `weapons`

Trade settlements can focus on:

- producing or accumulating `money`
- producing or distributing `luxury goods`
- keeping a balance of `money` and `luxury goods`

All settlements consume:

- `food`
- `herbs`
- `wares`

Consumption scales by population and settlement size. Exact costs are deferred.

## Trade

All internal and external trade uses `money`.

Neighboring regions can trade without Trade settlements. Trade settlements allow
external trade:

- northern external trade through the friendly empire, strongest at `C1`
- southern external trade through the ocean, strongest at `C5`

Trade potential tapers away from `C1` and `C5`. Other regions are more rural by
default, though they may still become important if they hold resources, routes,
or population.

Trade reports are valuable but politically vulnerable. A Noble may exaggerate
trade hardship to request tax relief, hide luxury flows, or claim monsters have
made a route unsafe.

## Taxes And Stockpiles

Taxes flow upward:

```text
Settlement -> Mayor -> Noble -> King
```

The King sets regional taxes. Nobles set settlement taxes within their regions.
Nobles normally apply one settlement tax value across all settlements they
control, except when granting tax exemptions.

Taxes may be paid in:

- `food`
- `money`
- a mix of both

Food is the most important tax resource and is usually taxed more heavily.

Nobles and Royals maintain stockpiles outside individual region stockpiles.
These are the resources they can use to offset shortages, pay upkeep, trade,
send aid, and buffer bad seasons. The King also has crown stockpiles.

This means the King is not only an order issuer. The King may need to:

- send aid downward
- lower taxes
- lend troops
- lend resources
- forgive arrears
- replace incompetent or dishonest actors
- decide whether to keep or reassign revoked regions

A region may be productive but still unable to survive alone if it lacks food,
herbs, or wares. This should create routine logistical dependence rather than
only disaster-driven aid.

## Military And Security

`weapons` are used to convert pops into race-split `soldiers`.

`warriors` emerge slowly and probabilistically from existing `soldiers`.
Warriors are expert troops; training and weapons alone cannot mass-produce
them.

Military resources:

- race-split `soldiers`
- race-split `warriors`
- `weapons`

The King maintains:

- a `kingsguard`, protecting Royals under the King's command
- a national standing army, which can be lent or assigned to Nobles

Nobles may maintain private armies. They can also employ scouts to detect
monsters. Armies and scouts cost upkeep, likely including food, herbs, weapons,
wares, and money. Exact costs are deferred.

Settlement guard layer:

- villages have a Mayor only
- towns have a Mayor and a Guard Captain
- cities have a Mayor and a Guard Captain, likely with stronger guard capacity

Guard Captains report to Mayors. They command local `guard` forces, which are
functionally the same kind of race-split fighting resource as `soldiers` but
tracked as settlement security rather than a Noble field army.

Guard Captains can:

- detect nearby monster buildup with lower reliability than dedicated scouts
- suppress local unrest
- report safety, guard strength, and threat sightings
- become the first point where monster misinformation or prejudice enters the
  reporting chain

Settlement defenses modify guard effectiveness:

- villages have little or no fixed defense
- towns may have palisades at best
- cities may have walls

Defense quality is rolled when a settlement is upgraded. The roll can receive
bonuses from:

- more dwarf pops
- nearby Production settlements
- the settlement itself being a Production settlement
- available `lumber`, `ore`, `wares`, and `money`
- competent Mayors or Guard Captains

This creates long-lived local variation: two cities of the same size may have
very different wall quality because one had better builders, nearby workshops,
or enough dwarfs during the upgrade.

## Monsters

Monsters are an abstract threat that can appear anywhere.

They should build up over time. If not handled, they eventually attack a
settlement. Monsters can move from settlement to settlement and across region
borders. Settlement positions inside a region are abstract, so movement does not
need exact local coordinates.

Detection rules:

- dedicated scouts are the primary early-warning tool
- town and city guards may detect nearby monsters as a weaker scout substitute
- village-only regions are more vulnerable to undetected buildup
- monsters near unused settlement slots require scouts for reliable detection

Monster reports are an important source of uncertainty. A mayor may underreport
to avoid blame, overreport to get aid, or misidentify race conflict as monster
activity.

## Forest Elves

The forest west of column `A` is occupied by isolationist forest elves. They are
an external faction, distinct from normal elf pops inside the kingdom.

They are not simply monsters. They are a neighboring people with their own
territory and threat logic.

Possible first-pass behavior:

- forest exploitation increases risk
- herb and lumber focus near column `A` increase economic reward and diplomatic
  danger
- forest elves may be less hostile toward kingdom elf pops or elf-led offices
- racist Nobles may misread forest elf warnings as raids
- ambitious Nobles may provoke incidents and report them as unprovoked attacks

## Actor Hierarchy

At maximum depth, a report path might look like:

```text
Guard Captain -> Mayor -> Noble -> King
```

Villages skip the guard layer:

```text
Mayor -> Noble -> King
```

For region-level matters:

```text
Noble -> King
```

The important design difference from the current Frontier scenario is that the
King receives many reports about overlapping problems:

- a Noble reports tax hardship
- a Mayor reports food shortage
- a Guard Captain reports monster signs
- neighboring Nobles report migration spillover
- trade regions report price shifts
- border regions report guard needs

The King should often face plausible but incompatible explanations.

## Random Generation

Most scenario details should be randomized from curated pools.

Randomized elements:

- Noble identities
- Royal count and identities
- Noble family ties
- actor races
- actor traits
- actor prejudice profiles
- actor positive race preferences
- region ownership
- settlement count per region
- settlement sizes
- settlement specializations
- settlement resource focus
- settlement defense quality
- settlement population mix
- regional stockpiles
- noble stockpiles
- initial armies
- initial guard forces
- scout coverage
- monster buildup
- random death timing / risk
- mayor and guard competence

Fixed constraints should still make the generated kingdom legible:

- `C3` is always the capital.
- `C1` and `C5` are the main trade anchors.
- row `1`, column `A`, column `E`, and row `5` always matter.
- the King's second region should help supply food taxes.
- every Noble has at least one region.
- Royal Nobles are stronger by default.

Names do not need special fantasy construction. Common English names are fine,
and gender does not need to matter mechanically.

## Expected Emergent Failures

This scenario should produce failures that are economic, political, and
informational at the same time.

Examples:

- A mountain Noble overbuilds mining, loses agriculture to pollution, then hides
  food dependence until a tax push creates famine.
- A coastal trade city reports high money income while quietly draining food
  from inland neighbors.
- A forest-border Noble blames elves for monster attacks caused by poor scout
  coverage.
- A racist Mayor drives out dwarf pops, then reports ore decline as bad luck.
- A Royal receives repeated crown aid because of family pull while a more
  competent non-Royal Noble is reviewed harshly.
- A Noble requests the national army for monsters, but the actual problem is
  guard underfunding after excessive food taxation.
- A Guard Captain detects monster buildup, but the Mayor delays the report
  because panic would trigger migration.
- A greedy King keeps revoked regions too long, improving crown food stockpiles
  while increasing Noble distrust.
- Warriors slowly accumulate in a private army, making a Noble politically
  dangerous even if tax reports look compliant.

## Scenario Purpose

The scenario is meant to be more complex than the current Frontier setup, not
just wider. It adds several overlapping systems that produce different kinds of
partial truth:

- geography creates uneven economic dependence
- population race mix affects productivity and politics
- settlement size creates capacity and migration problems
- taxes move survival resources upward
- stockpiles make aid and withholding visible decisions
- monsters create uncertain security reports
- mayors and guards add local reporting layers
- Royals create unequal political trust
- prejudice creates both bad decisions and bad interpretation

The success criterion is a log where the King cannot solve problems by asking
"what is the true value?" The interesting play should be in deciding which
institutions to trust, which reports to audit, when to send scarce aid, when to
move soldiers, and when to replace people who may be unlucky rather than
incompetent.

## Deferred Balance Questions

The following are intentionally left for later:

- exact resource production rates
- settlement capacities by size
- migration formula
- upkeep costs for scouts, guards, armies, and kingsguard
- soldier training costs
- warrior emergence chance
- monster spawn and attack rates
- tax defaults
- stockpile sizes
- report cadences
- courier travel times
- exact race effectiveness numbers
- exact prejudice representation
- exact positive race preference representation
- death and succession scoring
- defense-quality roll formula
