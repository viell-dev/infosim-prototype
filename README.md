# InfoSim — Distributed Information Strategy Simulation (Prototype)

This is the prototype sandbox for the design described in [`docs/blueprint.md`](docs/blueprint.md).
Its goal is not to be a game — it is to find out whether the **True / Known / Reported state**
separation produces interesting emergent narratives when read as logs. If reading the logs feels
like reading a believable little history of misinformation and delay, the concept is worth investing
in. If not, it isn't.

This repository currently implements **Milestones 1–3** of the blueprint: Information Sandbox,
Hierarchical Decisions, and Political Pressure. Information flows up through delayed and
biased reports; orders flow down through couriers; actions execute over time and feed
consequences back into true state; disloyal actors forge reports and skim resources; the
King reviews subordinates and replaces them from a candidate pool. No graphics yet — the
human log is the product.

The simulation runs on a **discrete-event scheduler** (see `src/infosim/scheduler.py`),
not a fixed tick loop. Each actor has its own cadences for observing, reporting, and
deciding; the engine drains a global priority queue of events in logical-time order.
Idle actors consume zero cycles, and the design ports cleanly to an async / multi-process
runtime when we want real parallelism (Python's GIL means we don't get it for free).

---

## Tech stack

- **Python 3.12+**, stdlib only. No third-party runtime deps.
- Plain `@dataclass` data model — easy to reshape as the design evolves.
- Single seeded `random.Random` threaded through the simulation for determinism.
- Tests run via a small stdlib-only runner at `tests/_runner.py` (no pytest required).
- Output: JSONL event stream + a human-readable `.log` per run, under `runs/`.

### Why Python (and not Rust/Go)

The blueprint suggests Rust, C#, Go, or Python. At Milestone 1 the binding constraint is
*iteration speed on data shapes* — what fields belong on a `Report`, what knobs an `Actor`'s
traits expose, how a relay transformation should compose. Python lets that reshape happen with
zero friction. The simulation is intentionally deterministic and data-oriented, so porting the
validated model to Rust later is straightforward if the concept holds.

---

## Run it

From the repo root:

```bash
# list available recipes
just

# tests
just test

# default frontier scenario, seed 1, 200 ticks
just frontier

# any supported scenario
just run deep_chain 1 400

# space-miner scenario, seed 1, 500 ticks by default
just space-miner

# inspect a run
just inspect-kind runs/frontier-seed1-20260602-220543.jsonl dispatch
just inspect-region runs/frontier-seed1-20260602-220543.jsonl Frontier

# generate a plain HTML debug map for the latest run
just map

# or map a specific run
just map runs/frontier-seed1-20260602-220543.jsonl

# aggregate experiments
just sweep 100 300
just stress 50 300
```

Outputs land in `runs/<scenario>-seed<N>-<timestamp>.{jsonl,log}`.
`just run`, `just frontier`, `just deep-chain`, and `just space-miner` print the generated JSONL
and log filenames as full paths. `just map` writes a sibling `*-map.html` file
for the latest `runs/*.jsonl` by default and prints the full HTML path. Pass a
JSONL path to map a specific run.

---

## Code layout

- `src/infosim/sim.py` is the discrete-event engine: scheduling, actor cadences,
  message arrival handling, observations, and pushed reports. It is
  genre-agnostic — it holds no stat names, only a `Ruleset`.
- `src/infosim/ruleset.py` defines the scenario-owned configuration: the stat
  schema (with polarity), the defense / supply / threat stat-role mapping, and a
  `RoleSpec` per actor title declaring that role's ordered behaviors plus its
  production / decay (usage) / tax (upward transfer) specs and thresholds. The
  core ships no concrete ruleset; each scenario builds its own.
- `src/infosim/policies/` holds decision and political behavior:
  `roles.py` is the generic behavior registry (`BEHAVIORS` + `run_policy`) — one
  decide pipeline driven by the actor's `RoleSpec`, no per-title functions;
  `orders.py` routes and executes downward orders, `info_requests.py` owns the
  pull-based request / response path, `review.py` handles strikes and
  replacement, `corruption.py` handles skimming, and `constants.py` keeps only
  genre-neutral institution tuning (the genre numbers live in each scenario's
  ruleset).
- `src/infosim/policy.py` is a compatibility facade for older experiments that
  imported policy helpers directly.
- `src/infosim/actions.py`, `messages.py`, `reports.py`, `requests.py`,
  `orders.py`, `scheduler.py`, `world.py` (topology only), and `personnel.py`
  are focused data / mechanics modules used by the engine and policies.
- `src/infosim/scenarios/` wires concrete worlds, actors, and a `RULESET`;
  `tools/` contains
  analysis helpers. `tools/inspect_run.py` filters raw JSONL events, and
  `tools/map_run.py` replays a run into a plain HTML debug map sampled at
  start / 25% / 50% / 75% / end. `tests/` mirrors the purpose-specific
  behavior under test.

---

## What the scenario does (M1 + M2 + M3)

`scenarios/frontier.py` wires a **wide frontier hierarchy** under the same King:

```
Capital  ──→ Province (Mira)   ──→ Frontier    (Aldric)   corrupt cluster
         │                    ├─→ Harbor      (Brenn)
         │                    └─→ Highlands   (Kyra)
         ├→ Marches  (Cassia)  ──→ Borderlands (Talen)    honest chain
         └→ Lowlands (Neria)   ──→ Rivergate   (Soren)    mixed chain
                              └─→ Old Road    (Mael)
```

Ten named actors form the hierarchy:

- **King Halric III** (Capital): high education, honest, low fear. Reports to no one.
- **Governor Mira of Halen** (Province): moderate competence, somewhat dishonest, fearful, ambitious.
- **Commander Aldric Vale** (Frontier): competent observer, but fearful of looking weak, *disloyal and ambitious* — the corruption engine.
- **Commander Brenn of Karth** (Harbor): capable and pragmatic, with enough pressure to bend bad news.
- **Commander Kyra Stane** (Highlands): loyal enough not to forge, but fear-shaped under pressure.
- **Governor Cassia of Reach** (Marches): loyal, honest, modest ambition — the foil to Mira.
- **Commander Talen Voss** (Borderlands): loyal, honest, moderately competent — the foil to Aldric.
- **Governor Neria of Vale** (Lowlands): moderate middle case with two commanders below her.
- **Commander Soren Deepwell** (Rivergate): steady and loyal, but less competent than Talen.
- **Commander Mael Rusk** (Old Road): ambitious and less loyal, the weak point in Neria's branch.

The three governors have one, two, and three direct commanders. Their regions face
comparable raid/unrest/supply shocks at staggered times so the King's final belief
can compare *reporter integrity* across branches with different widths.

Each region tracks three true variables: `garrison_strength`, `food_stores`, and `unrest`. Each
variable carries a **polarity** — for garrison and food, low values are bad news; for unrest,
high values are bad news. Bias terms respect polarity, so a fearful or dishonest actor
distorts every variable in the *politically convenient* direction. Each tick:

1. Scripted true-state events fire if scheduled (raid, reinforcements, levy drain, supply loss…).
2. On its own observation cadence, the senior local actor samples every variable in its region
   with competence-scaled noise. **Perception is honest** — fear and corruption don't enter here.
3. On reporting cadence, each subordinate dispatches a courier upward carrying *every* belief
   they hold. Couriers have travel time, jitter, and a small loss probability.
4. On arrival, the recipient runs the report through its own transformation
   (`interpretation_bias + corruption_bias + fear_bias`, polarity-aware; confidence degraded),
   then stores it. That stored belief is what gets re-relayed further up next cadence — so the
   chain `Commander → Governor → King` shows three layers of compounding distortion and delay.

A final snapshot at the end of the run prints truth vs. the King's current belief per region,
with the chain of actors the King's belief flowed through.

**M3 adds politics:**

- **Loyalty-driven forgery.** When an actor's `loyalty` is below `0.4` and the
  variable they're about to report is bad news (low garrison/food or high
  unrest), the outgoing report value is *replaced* with a politically convenient
  lie before dispatch. The actor's own belief stays honest. Forgery severity
  scales with disloyalty.
- **Skimming.** A disloyal *and* ambitious actor (loyalty < 0.4, ambition ≥ 0.5)
  quietly extracts food from their own region on every decide cycle. The region's
  true food drops. If the same actor is also forging, the loss is hidden.
- **Performance review and dismissal.** The King runs a review of each direct
  subordinate every decide cycle. A region with believed unrest above 60 or
  believed garrison below 800 earns a strike. Three consecutive strikes →
  dismissal. A replacement is chosen from `Simulation.candidate_pool` using
  scoring weights derived from the King's own traits: a scholar king (high
  `education`) prioritises competence; a paranoid king (high `fear`)
  prioritises loyalty.

**M2 adds the downward half of the loop:**

5. On a slower **decide cadence** each actor runs its policy (`src/infosim/policies/`). The King
   issues `REINFORCE`, `SUPPRESS_UNREST`, and `SEND_SUPPLIES` orders to subordinates based on
   his belief about regions further down the chain. The Governor translates received orders
   into concrete actions (`transfer_garrison`, `send_supplies`) or sub-orders down to the
   Commander. The Commander executes suppression orders and autonomously sends **urgent
   reports** upward when his honest local belief about food or garrison crosses critical
   thresholds.
6. **Orders travel on the same courier bus as reports** — they're delayed, jittered, and can
   be lost. Forgery and alteration are deferred to M3.
7. **Actions in flight** (`src/infosim/actions.py`) represent physical work-in-progress: a
   marching column or a suppression campaign with its own duration. They resolve into the
   true state when their completion tick arrives, closing the feedback loop.

---

## What "success" looks like at this milestone

A specific kind of moment in the human log. Example from `seed=1`:

```
t=0036  [Province] Governor Mira dispatches courier #11 → Capital
        (eta t=41, subject=Frontier.garrison_strength, value≈1664)
t=0040  [Frontier] RAID — garrison 1500 → 800
t=0041  [Capital] King receives courier #11: Frontier.garrison_strength ≈ 1676
        (conf 0.76, chain: cmd_aldric → gov_mira → king)
```

The Frontier garrison has just been gutted. The King is reading an inflated, pre-raid number
relayed by his fear-biased commander and his somewhat-dishonest governor, and won't see the
true picture for another full Province→Capital cadence cycle. **That is the entire pitch of
the design in three log lines.** If the prototype keeps producing moments like this, the
concept is real.

---

## Validation experiments queued (pre-port)

Before committing to a Rust/Tokio port — which would lock in whatever dynamics
the prototype currently has — we want to pressure-test whether the *pattern*
matches intent. Hand-picked single-seed narratives are misleading. Items below
are ordered by expected information per hour of work.

1. **Multi-seed sweep (50–100 seeds).** Aggregate divergence stats across many
   seeds of the Frontier scenario: how often does the King's end-of-run belief
   meaningfully diverge from truth? How often does forgery / skimming go
   undetected? How often does an unlucky seed produce *no* interesting
   institutional failure? Establishes whether the dramatic moments we've
   been reading are typical or rare.
2. **Wider topology (siblings).** Two governors under the King, or two
   commanders under one governor. Right now divergence is a single thread;
   with siblings the King can *compare* reports, which is where political
   reasoning actually starts ("Aldric's numbers look different from
   Brennar's"). Engine supports it; only the scenario needs widening.
3. ~~**Pull-based `INFO_REQUEST`.** Third `MessageKind` so superiors can spend
   a courier to ask "what's actually going on?" rather than passively waiting
   for ambient pushes.~~
   **Done 2026-06-02** as part of the engine refactor. Two kinds
   (`INFO_REQUEST` + `INFO_RESPONSE`) over the same bus, plus per-actor
   `request_inbox` / `pending_requests` and a `REQUEST_TIMEOUT` event.
   The King initiates audits on peer-suspicion strikes; each hop is a
   fresh decision point (forward / cache / fabricate / refuse). See
   obs entry.
4. ~~**Stress dial.** Crank misinformation / corruption / loss parameters to
   extremes and watch whether the system degrades gracefully or collapses
   into noise — and crank them to zero to confirm divergence vanishes. Tells
   us whether the dynamics are tuned in a sensitive range.~~
   **Done 2026-06-02.** `tools/stress.py`. System degrades gracefully;
   pristine bottoms out at observation noise; default sits mid-curve, not
   on a cliff. See obs entry. Surfaced a threshold-cliff at the forgery
   gate and a counter-intuitive "lies protect the governor from review"
   dynamic that wants comparison-based review on top of siblings.

These run on the existing engine. None require structural changes before
they can be answered.

---

## Observations log

Append-only. Add notes as the design evolves.

### 2026-06-03 — Before/after run diff: exact cleanup footprint (Claude Opus 4.8 via Claude Code)

Sanity check on whether the ruleset cleanup quietly changed behavior the
(qualitative) tests would miss. Generated matched runs from the pre-cleanup
commit (`a3b6eda`, via a throwaway worktree) and current `main`, then diffed
the JSONL event by event.

- **Frontier (seed 7, 200t): behavior-identical.** All 3512 events match; the
  only difference is the additive `"stat": "unrest"` field now on `defense`
  events. No value, ordering, or RNG change. So the medieval path is preserved
  across versions, not merely same-code reproducible.
- **Space_miner (seed 2): three differences, isolated by reverting them.**
  Reverting the two intended-ish changes made the new code byte-identical to the
  old (6568 events, zero non-additive divergence). The complete footprint is:
  (1) additive `stat`/`driver_stat` keys; (2) `behavior_consume` now skips
  zero-amount `consumption` events (`if consumed <= 0: continue`) — the old
  `_consume_ore` logged them; this is log-only (consuming 0 changes no state and
  draws no RNG) and was an *unintended* side effect of the rewrite, kept because
  it only removes noise; (3) the documented info-request forgery threshold swap
  (literal 1000/20 → per-stat `bad_news_thresholds`), which shifts the RNG
  stream and accounts for the bulk of the divergence.

Test-completeness read: the suite is qualitative (event-kind presence,
capability checks, one seeded narrative). It did **not** catch difference (2) and
caught (3) only incidentally (it broke seed 1's recall-courier outcome). Per the
project's "close enough is fine" stance for stochastic runs, no exact-value
golden regression was added; this note records the precise footprint instead so
the divergence is reconstructable.

### 2026-06-03 — Scenario-owned rulesets: resources & roles as data (Claude Opus 4.8 via Claude Code)

Cleanup pass before M4, resolving the "generic-genre claim is aspirational"
caveat from the 2026-06-02 structure review. The engine no longer hard-codes any
genre. A scenario now hands the `Simulation` a `Ruleset` (`src/infosim/ruleset.py`)
that declares its stat schema (polarity), the defense/supply/threat stat roles,
per-stat bad-news thresholds, and a `RoleSpec` per title. Each `RoleSpec` lists
that role's ordered generic behaviors plus its production / decay (usage) /
tax (upward) specs and decision thresholds — all data, no code per genre.

Four commits, each green:

1. **Ruleset + schema relocation.** Stat schema moved off `world.py`; `sim.py`
   reads polarity/thresholds from the ruleset; `reports.forge_value`/`relay` take
   the schema as an argument. Pure relocation — run output byte-identical
   (determinism + full sweep aggregate unchanged).
2. **Generic behavior registry.** `decide_king/governor/commander/captain/
   manager/ceo` and `POLICY_BY_TITLE` are gone. `run_policy` runs the actor's
   `RoleSpec.behaviors` from a `BEHAVIORS` table: skim, produce, consume, tax,
   execute_orders, issue_orders, apex_defense_orders, autonomous_suppress,
   local_defense_orders, defend, urgent_reports. `defend_location` moved to
   `actions.py`; leaf order execution unified through `_handle_middle_order`
   (now handles DEFEND-to-self). One deliberate behavior change: info-request
   forgery now uses the ruleset's per-stat bad-news thresholds instead of literal
   1000/20 — frontier unaffected, space_miner shifts slightly. Frontier
   determinism and the entire sweep aggregate stayed byte-identical, confirming
   the medieval path was preserved exactly.
3. **Removed back-compat shims.** `actor.region`/`reports_to`, `world.regions`/
   `add_region`/`Region()`, `world.VARIABLES`/`STATS`. `world.py` is now pure
   topology.
4. **Genre-agnostic map replay.** Economy events (mining/consumption/defense/
   skim/transfers/suppression) all carry a `stat` field; `tools/map_run.py`
   applies them generically and renders the union of stats actually present, so
   a frontier map shows garrison/food/unrest and a space map shows
   ore/ships/population/alien_presence with no cross-genre rows.

Validation: `python3 tests/_runner.py` → 37/37 (added `tests/test_ruleset.py`:
captain mines+taxes from role data; genre isolation). `tools/sweep.py` aggregate
identical to the pre-cleanup baseline (report_forged 64.1, skim 42.4,
order_dispatched 44.2, action_completed 28.4, 100/100). Both genre maps render
cleanly. Adding a new genre is now a config-only change: define a `Ruleset` and
build actors — no core edits.

### 2026-06-02 — Space-miner map replay fix (GPT-5 via Codex)

Fixed `just map` for `space_miner` runs. The default `just map` recipe selects
the latest JSONL file, so once the latest run was `space_miner-...jsonl`, map
generation failed because `tools/map_run.py` only inferred `frontier` and
`deep_chain` filenames. The mapper now infers `space_miner`, builds the
space-miner initial state, and replays the new event kinds: mining, ore
consumption, ore taxes, alien contact, station defence, and mobile Commander
arrival/reassignment.

Validation:

- `just map` generated `runs/space_miner-seed1-20260602-232417-map.html`.
- `just map runs/space_miner-seed1-20260602-232220.jsonl` generated the
  explicit map path successfully.
- `just check` passes all 35 tests, including a regression test that verifies
  `cmd_orion` returns to Homeworld under the CEO in the replayed map state.

### 2026-06-02 — Space-miner scenario and free-agent commanders (GPT-5 via Codex)

Added `scenarios/space_miner.py`, a setting swap that keeps the same delayed
information and delegated authority model but renames the hierarchy to
CEO → Manager → Captain, with Commanders as mobile military free agents.
Scenario-specific stat roles let `ships`, `ore`, and `alien_presence` exercise
the same policy machinery that frontier uses for garrison, food, and unrest.

New mechanics:

- `MOVE_TO_LOCATION` and `DEFEND_LOCATION` orders let Commanders move between
  stations and change superior on arrival.
- Captains mine ore from infinite sources; their `ships` stat scales mining
  output.
- Captains pay ore tax upward to Managers, Managers pay a smaller tax upward
  to the CEO, and Managers consume ore based on local population.
- Periodic alien contacts create warning windows before larger swarms, giving
  the order-delay system time to shuffle Commanders for defence.

Validation:

- `just check` passes all 34 tests.
- `just space-miner 1 500 runs` wrote
  `runs/space_miner-seed1-20260602-232220.{jsonl,log}`.
- In that sample, Commander Orion moves Homeworld → Ceres under `mgr_ceres`
  at t=101, Ceres → Europa under `mgr_europa` at t=182, then Europa →
  Homeworld under the CEO at t=208. Defence events reduce Ceres and Europa
  alien pressure to zero after the warning / swarm contacts.

### 2026-06-02 — Map vacant-office replay fix (GPT-5 via Codex)

Fixed the HTML map replay for runs where a governor is dismissed after the
candidate pool is exhausted. The simulator logs `appointment_failed` and leaves
the office vacant; the map previously marked the dismissed governor inactive
but had no visible vacant-office node, so active commanders under that office
were orphaned and disappeared from the rendered End checkpoint.

`tools/map_run.py` now creates a replay-only `Vacant` office node on
`appointment_failed`, preserves the office lineage, and nests the still-active
subordinates under that vacant office. Regenerated
`runs/frontier-seed1-20260602-225242-map.html`; its End block now shows Vanek
in Lowlands plus vacant Governor nodes for Marches and Province with their
commanders beneath them.

Validation:

- `just map runs/frontier-seed1-20260602-225242.jsonl` regenerated the affected
  HTML map.
- `just check` -> all 33 tests passed, including a vacant-office regression.

### 2026-06-02 — Just command wrapper (GPT-5 via Codex)

Added a repo-level `justfile` so common workflows use short, stable commands:
`just frontier`, `just run <scenario>`, `just map <run.jsonl>`, `just test`,
`just check`, `just inspect-*`, `just sweep`, and `just stress`. The README's
run examples now point at those recipes instead of spelling out `PYTHONPATH`
and script paths directly. The run and map recipes print their generated output
filenames as full paths so the next artifact to open is unambiguous. `just map`
now defaults to the newest JSONL file in `runs/`, while still accepting an
explicit path.

Validation:

- `just --list` showed the expected recipes.
- `just test` -> all 32 tests passed.
- `just frontier 1 10 /tmp/infosim-just-check-paths` printed full JSONL/log paths.
- `just map /tmp/infosim-just-check-paths/frontier-seed1-20260602-224741.jsonl`
  printed the full HTML map path.
- `just map` mapped the latest JSONL file in `runs/` and printed the full HTML
  path.
- `just deep-chain 1 10 /tmp/infosim-just-check-paths` printed full JSONL/log paths.

### 2026-06-02 — Wide frontier topology: 1/2/3 commanders (GPT-5 via Codex)

`scenarios/frontier.py` now has three governors with distinct direct-command
widths:

- Cassia keeps one commander: Talen at Borderlands.
- New governor Neria has two commanders: Soren at Rivergate and Mael at Old Road.
- Mira now has three commanders: Aldric at Frontier, Brenn at Harbor, and Kyra
  at Highlands.

The world graph adds Harbor, Highlands, Lowlands, Rivergate, and Old Road,
with staggered shocks on the new commander posts so they generate reports,
orders, and review pressure during ordinary runs instead of existing only as
static map nodes. This widens the original sibling comparison while keeping
the same King/Governor/Commander policy stack.

Validation:

- `just test` -> all 32 tests passed.
- `just frontier 1 80 /tmp/infosim-check`
  wrote a frontier JSONL/log pair successfully.

### 2026-06-02 — M4-lite run map debug view (GPT-5 via Codex)

Built a deliberately simple HTML debug map generator:
`just map <run.jsonl>`. It writes `<run>-map.html` next to the
JSONL file and samples the run at five fixed checkpoints: start, 25%,
50%, 75%, and end. Each checkpoint renders the active hierarchy as a
nested tree, using the current `commander` links so subordinates remain
visually under the office holder they report to at that time.

Each actor block shows one row per stat from `world.STATS`:

- **Real**: the replayed authoritative stat value on that actor.
- **Self known**: that actor's current belief about their own stat, from
  observation events.
- **King known**: the King's current belief about that actor's stat,
  including confidence, last update time, and the belief source chain.

The map is a replay of the JSONL stream, not a live simulator view. It
reconstructs state from the scenario's initial `build()` output plus
structured events: `observation`, `receive`, `true_state_change`,
`response_integrated`, `skim`, `action_started`, `action_completed`,
`dismissed`, and `appointed`. It currently auto-detects the `frontier`
and `deep_chain` scenarios from run filenames, with `--scenario` as an
override.

Office changes are tracked explicitly. `dismissed` and `appointed`
events now include structured `display_name`, `title`, `commander`, and
`stats` fields, so the map can show lineage such as
`Mira of Halen -> Iselle Marn` without parsing human log prose. On
appointment, the replay rewires the dismissed actor's active
subordinates to the replacement, matching `review._dismiss_and_replace`.
`response_integrated` events also now include the returned answer values
and confidences, so audit responses are reflected in replayed known
state rather than only in the live simulation object.

This is intentionally **not** full M4. It does not step every event, show
message queues, expose order/action timelines, or provide interaction
beyond opening a static HTML file. Its purpose is only to make a run's
broad institutional shape readable at a glance.

Validation: generated a seed-1, 200-tick Frontier run and produced
`runs/frontier-seed1-20260602-220543-map.html`. The debug map showed the
five checkpoints, the nested King -> Governor -> Commander hierarchy,
the Province office handoff `Mira of Halen -> Iselle Marn`, and the
expected divergence around Aldric's real vs. King-known Frontier stats.
Added `tests/test_run_map.py` so the checkpoint labels, known-state
columns, nested actor content, and replacement lineage stay covered.

### 2026-06-02 — Policy module split (GPT-5 via Codex)

`policy.py` had become the central pile-up point called out in the
previous structure review. The code is now split by responsibility under
`src/infosim/policies/`: role decisions, order routing, INFO_REQUEST
handling, review / dismissal, corruption, hierarchy helpers, and policy
constants. `src/infosim/policy.py` remains as a compatibility facade so
older local experiments can still import the old names.

The tests were migrated to import the new purpose-specific modules rather
than the facade, which makes the split itself part of what the suite
checks. Behavior should be unchanged; the validation run passed 31/31 via
`just test`, and `just check` also passed.

### 2026-06-02 — Structure review after INFO_REQUEST/deep-chain work (GPT-5 via Codex)

Quick pass over `docs/blueprint.md`, the current README, recent git
history, repo layout, core modules, scenarios, and tests. This is still
an experiment rather than a product codebase, so the read is deliberately
about *major* distortions that could affect design conclusions, not
normal prototype roughness.

Current shape is coherent. The repo is clean on `main`, with a fast
history from M1 sandbox → scheduler → hierarchy → political pressure →
sibling topology → stress tooling → INFO_REQUESTs → deep-chain
validation. The code is small enough to reason about directly: core
engine in `src/infosim/`, scenarios in `src/infosim/scenarios/`,
analysis helpers in `tools/`, and focused stdlib tests in `tests/`.
The test suite passed: 31/31 via `just test`.

Major structural notes:

- **`policy.py` is now the pressure point.** It is ~900 lines and holds
  role behavior, global thresholds, corruption/skimming, review logic,
  order routing, INFO_REQUEST routing, replacement hooks, and audit
  initiation. Fine for the current sandbox; before a port or major
  feature branch, this is the obvious file to split.
- **"Arbitrary depth" is proven for report propagation and middle-rung
  order forwarding, not yet for every policy surface.** `decide_king()`
  only considers direct subordinates and one level deeper. Chain-health
  review and some INFO_REQUEST subject routing still inspect children /
  grandchildren rather than all transitive descendants. The deep-chain
  scenario validates the core idea, but it should not be read as "every
  gameplay rule is already depth-agnostic."
- **The generic-genre claim is aspirational.** The Actor schema and
  message bus are generic, but `garrison_strength`, `food_stores`, and
  `unrest` are still hardcoded in the stat polarity table, policy
  thresholds, audit target construction, and scenario tooling. Replacing
  the stat set is plausible, but it is not currently a config-only swap.
- **The README has historical drift by design.** Older obs entries are
  useful because they record the reasoning path, but some "open" notes
  later became done. Treat the newest entries and the top-level run
  instructions as current; treat old queues as historical context unless
  a later entry reaffirms them.
- **Role dispatch is intentionally narrow.** Policies are keyed by title
  (`King`, `Governor`, `Commander`). That keeps the prototype legible,
  but it is the main mismatch with the broader "same Actor at every
  depth / any institution" ambition.

Net read: no alarming breakage. The main risk is that the docs can sound
more general than the implementation. For experiment validity, that
means the next serious validation should either stay inside the current
scenario envelope, or first make depth traversal / stat schemas / policy
dispatch honestly generic enough that the experiment is testing the
intended architecture rather than today's hand-tuned medieval case.

### 2026-06-02 — Engine refactor: actor schema + INFO_REQUEST + arbitrary depth (Claude Opus 4.7 via Claude Code)

Three commits land the engine reshape we discussed (and the user
confirmed) the prototype needed before any port to a faster language.
The math the scenario uses is the same; what changed is the *shape*.

**Step 1 — Unified actor schema.** Every node in the hierarchy uses
the same Actor dataclass. Stats live on actors (not regions);
`region` → `location`, `reports_to` → `commander`. Subjects are keyed
by actor id rather than region name
(``"Frontier.garrison_strength"`` →
``"cmd_aldric.garrison_strength"``). Region/Location is topology-
only; resources are tied to the *office* (location) so a dismissed
official's stockpile transfers to their replacement. Sweep numbers
unchanged — pure refactor, behaviour-preserving.

**Step 2 — INFO_REQUEST / INFO_RESPONSE.** Two new MessageKinds ride
the existing bus. Each actor gains `request_inbox` and
`pending_requests`; the scheduler gains `REQUEST_TIMEOUT`. The
king's policy is no longer purely passive: when peer comparison
flags a chain as "suspiciously rosy," he spends a courier to
**ask**. The relay's policy is the five-way choice we sketched —
forward, answer-from-cache, fabricate, refuse, investigate
(deferred). A disloyal relay (loyalty <
``REQUEST_TRUST_THRESHOLD``) defaults to **protective mode**:
answers from cache without asking the subordinate, possibly
forging on the way through. On the return path the same forgery
dynamic can shade the values as they pass back upstream. Lost
couriers, timeouts, and orphan responses all handled. Verified end-
to-end on a single-seed trace where corr=1 is lost, times out at
t=100 and the King re-audits; corr=2 completes the full round-trip
with truth integrated at t=118; corr=7's downstream response is
lost on the way back and gov_mira's own timeout auto-dispatches a
refusal upstream.

**Step 3 — Arbitrary depth.** Generalised the middle-rung order
handler so a Governor receiving an order for a deeper-than-direct
target forwards the order to whichever direct subordinate covers
that target's chain. Built `scenarios/deep_chain.py` — a 4-level
hierarchy (King → General → Colonel → Captain). The same policies,
same engine, no depth-specific code anywhere. End-of-run snapshot
on seed=1 (Captain Dren, the deepest actor, set disloyal +
ambitious):

```
[Outpost] Dren Marcellus garrison_strength:
  truth=800  king ≈ 2077 (chain cap_dren → col_renna → gen_kallen → king)
[Outpost] Dren Marcellus unrest:
  truth=90   king ≈ 47   (chain cap_dren → col_renna → gen_kallen → king)
[Outpost] Dren Marcellus food_stores:
  truth=90   king ≈ 115  (chain cap_dren → col_renna → gen_kallen → king)
```

Three relay hops of compounding forgery produce a +160% over-
estimate of the deepest garrison. The source_chain shows exactly
the path each belief traveled. That's the design promise: the
deeper the chain, the more leverage misinformation has — and the
engine handles it for free because every layer is the same shape.

**What the engine is now ready for** (not necessarily what the
prototype does):

- Any genre: replace the {garrison_strength, food_stores, unrest}
  stat schema with X4's {ore, credits, energy} or an RTS's
  {soldiers, ammo, morale} and the same code runs. No engine module
  mentions those keys.
- Arbitrary depth: tested at 4 layers, no upper bound encoded
  anywhere. A complete corporate / military / feudal / political
  hierarchy with dozens of layers would use the same machinery.
- Player as actor: the player's "policy" is just `drain UI input
  queue → dispatch messages`. Engine doesn't distinguish player
  from NPC actors. Real-time vs paused vs scheduled is a scheduler
  config, not a code change.
- Cross-rung addressing: the bus can deliver to any actor at any
  depth; the only "cost" is the chain-of-locations travel time.
- Pull-based intelligence gathering at any level: any actor with a
  reason and a courier budget can audit any subordinate.

**Pre-port residual queue** (none blocking a port; these are the
next *interesting* design moves):

- Detection-avoidance for skim ("3% off the top is safer than
  20%") and forgery (small lies harder to catch than large ones).
- Sibling collusion / conflict — peer-to-peer messaging on the
  same bus, or cross-rung routing via the King as broker.
- A reputation gradient separate from traits (King trusts Cassia
  more, weights her reports higher).
- `strikes_by_kind` memory so the King's review doesn't reset
  when complaint type changes.
- Audit results weighted differently from ambient pushes ("freshly
  authenticated, treat as truer than a routine report").

### 2026-06-02 — Smoothed gates + peer-comparison review (Claude Opus 4.7 via Claude Code)

Acting on the two pre-port action items the stress dial surfaced:

**(a) Smoothed forgery/skim gates.** Raised both hard gates from
``loyalty < 0.4`` to ``loyalty < 0.85`` — so only effectively-saints
are exempt — and squared the disloyalty term in the probability:
``ambition * (1 - loyalty)^2``. Severity multiplier becomes
``disloyalty * uniform(0.5, 1.5)`` clamped to [0,1]. Effect: mildly
loyal actors lie occasionally rather than not at all; the dial no
longer has a cliff at the boundary.

**(b) Peer-comparison review.** When the King has ≥2 direct
subordinates, ``_review_subordinate`` now compares each sub's
chain-health (normalised garrison + food − unrest, summed over their
span) against the median of peers. A score *below* the median by
``PEER_DEV_LOW`` is an **underperformance strike**; a score *above* by
``PEER_DEV_HIGH`` is a **suspicion strike** — "your region is
reporting prosperity while peers under similar shocks are not." With
only one subordinate, falls back to absolute thresholds.

Stress dial re-run shows the cliff is gone:

| profile  | report_forged | Frontier garrison err |
| -------- | ------------: | --------------------: |
| pristine |       7.8     |        +3.9           |
| low      |      16.0     |        +6.3           |
| default  |      44.6     |       +44.3           |
| high     |      94.2     |      +111.8           |
| broken   |     108.9     |      +131.2           |

Pristine and low are now distinguishable (forgery 7.8 → 16). The curve
is monotonic and smooth, not a step function. Pristine no longer
produces zero forgeries — even very loyal actors occasionally shade
the truth, which is realistic.

100-seed sweep shows a much wider spread on Frontier divergence:
``garrison_strength`` p10..p90 went from +3..+79 to **+3..+131**
(seed-to-seed variance much richer). Median is now +13% rather than
+24% — half of seeds Aldric barely lies, half he gets away with
egregious forgery. Different runs produce different institutional
arcs, which is the dynamic uncertainty we wanted.

**Dismissals dropped 3.5/seed → 1.1/seed.** The peer comparison is
much more selective. Walking through seed=7's review events:

```
t= 40  strike  gov_mira:    suspiciously rosy vs peers (6.08 vs 5.11)
t= 60  strike  gov_mira:    suspiciously rosy vs peers (6.02 vs 4.91)
t= 60  strike  gov_cassia:  underperforming peers     (4.91 vs 6.02)
t=100  strike  gov_mira:    underperforming peers     (4.00 vs 5.03)
t=100  strike  gov_cassia:  suspiciously rosy vs peers (5.03 vs 4.00)
t=140  strike  gov_mira:    underperforming peers     (2.67 vs 3.73)
t=140  strike  gov_cassia:  suspiciously rosy vs peers (3.73 vs 2.67)
```

The King's verdict alternates: early on, Aldric's forgeries make
Mira's chain look rosy → Cassia "underperforming." Then Frontier
shocks finally percolate through belief; the picture flips and Cassia
looks suspiciously rosy while Mira "underperforms." The *honest*
governor (Cassia) is being punished for being too good; the *honest
middle manager* (Mira) is being punished for honestly reporting the
rot below her. The corrupt commander (Aldric) catches no strikes at
all — the review only sees direct subordinates, and his governor
takes every blow for him.

This is the **exact institutional pathology** the design was meant to
produce: a sovereign with all the data, two honest officials, one
liar — and the liar is the only person never punished. The honest
people punish each other.

A consequence to think about: dismissals drop because strikes don't
accumulate three consecutive — they alternate strike-type between
"rosy" and "underperforming" cycles. A real bureaucracy would track
different complaints separately, not reset them. A future
``strikes_by_kind`` dict on the actor would preserve memory across
complaint types. Not blocking; logged in obs.

Updated obs queue (pre-port action items from earlier sweeps):

- ~~Stochastic forgery + skim~~ — done.
- ~~Sibling topology~~ — done.
- ~~Stress dial~~ — done; no cliff edge.
- ~~Smooth forgery/skim gates~~ — done in this commit.
- ~~Compare-against-peer review~~ — done in this commit.
- **Open:** strike-by-kind memory (so complaints don't reset across types).
- **Open:** reputation/trust per actor in the King's mind (separate from traits).
- **Open:** comparison-suspicion at the commander level too, not just governor.
- **Open:** pull-based INFO_REQUEST (King spends a courier to verify).

### 2026-06-02 — Stress dial (Claude Opus 4.7 via Claude Code)

Built `tools/stress.py` — runs the scenario under five preset profiles
(pristine, low, default, high, broken) and prints a comparison matrix.
Each profile mutates `bus_loss_prob`, `bus_jitter_frac`, and an
"integrity" scalar that pushes loyalty/honesty toward 1 (integrity=0)
or away from 1 (integrity>1), with the fear trait pushed toward 0
inversely. `ambition` is left untouched — it isn't a moral axis.

Run: 5 profiles × 50 seeds × 300 ticks.

King's belief vs. truth, **signed mean % error**:

| subject                       | pristine |  low  | default | high  | broken |
| ----------------------------- | -------: | ----: | ------: | ----: | -----: |
| Frontier.garrison_strength    |    +3.6  |  +5.8 |   +37.5 |+113.4 | +126.0 |
| Borderlands.garrison_strength |    +1.9  |  +0.8 |    +5.2 |  +6.1 |  +11.7 |
| Frontier.food_stores          |    +3.6  |  +6.4 |   +47.2 |+119.0 | +126.6 |
| Borderlands.food_stores       |    +3.9  |  +3.2 |    +4.1 |  +7.9 |   +7.2 |
| Frontier.unrest               |    −2.0  |  −5.3 |   −30.0 | −69.6 |  −58.4 |
| Borderlands.unrest            |    −8.6  |  −1.8 |    +0.5 |  −2.7 |   +5.1 |

Mean events per seed:

| kind            | pristine |  low |  default |  high  | broken |
| --------------- | -------: | ---: | -------: | -----: | -----: |
| report_forged   |      0   |   0  |     60.4 |   83.0 |   83.4 |
| skim            |      0   |   0  |     22.8 |   29.6 |   29.4 |
| dismissed       |    4.9   |  4.5 |      3.5 |    2.3 |    1.9 |
| courier_lost    |      0   |   11 |     43.2 |  108.6 |  221.1 |
| urgent_report   |    4.8   |  4.5 |     10.8 |   14.9 |   16.6 |

What this tells us:

- **System degrades gracefully.** Errors grow monotonically with stress
  on the corrupt chain (3.6 → 5.8 → 38 → 113 → 126%) and stay near zero
  on the honest chain regardless of stress. Nothing pathological — no
  saturation, no collapse into noise.
- **Pristine bottoms out at ~3–8% error.** This is observation noise +
  relay competence noise — the engine's *floor*. Confirms that
  divergence at default is genuinely caused by the bias mechanics, not
  by accumulated numerical drift.
- **There is a cliff at the forgery / skim threshold.** Between
  pristine and low, behaviour barely changes — forgery and skim stay
  at zero because halved gaps leave loyalty above the 0.4 trigger.
  Between low and default the dynamics *switch on* abruptly. The
  threshold gates are too discrete for smooth stress response.
  Making forgery probability a smooth function of loyalty
  (`(1 − loyalty)^k`) with no hard gate would give a more dial-like
  response curve.
- **The forging commander protects his governor from review.**
  Counterintuitive but clean: as stress rises, Aldric's lies inflate
  Frontier's reported numbers so much that Mira no longer trips the
  King's strike thresholds — dismissals *drop* 3.5 → 1.9. Meanwhile
  on the pristine chain, the honest governor *Mira* gets dismissed
  *more* (4.9/seed) because the scripted shocks genuinely push the
  region below the King's absolute thresholds. **The King's
  review system rewards lying.** This is correct emergent behaviour
  and also the natural lead-in to comparison-based review (compare
  siblings; review against trend, not absolute).
- **The integrity dial is asymmetric and that's right.** Even at
  broken (×2.5), Borderlands stays under ±12% because Talen's
  loyalty/honesty defaults are very high — scaling the gap toward 1
  doesn't move him as much as it moves Aldric. Reporter integrity is
  doing what reporter integrity should.

Net read: dynamics are not in a sensitive range. The default profile
sits in the middle of a long, smooth curve, not on a cliff edge. Two
clear improvement targets came out of this experiment, neither
blocking a port:

1. **Smooth the forgery/skim gates** — make probability a continuous
   function of `loyalty` instead of binary `loyalty < 0.4`. The
   stress dial would then show a smooth dose-response instead of the
   pristine↔low plateau.
2. **Compare-against-peer review.** The King should notice that
   Borderlands is reporting raid damage while Frontier (under similar
   shocks) is reporting prosperity, and strike-count accordingly.
   This is the natural exploitation of the sibling artifact.

### 2026-06-02 — Sibling topology, two parallel chains (Claude Opus 4.7 via Claude Code)

Doubled the scenario into two structurally similar chains under the same
King:

```
Capital  ──→ Province (Mira)   ──→ Frontier    (Aldric)   corrupt chain
         └→ Marches  (Cassia)  ──→ Borderlands (Talen)    honest chain
```

Cassia and Talen are deliberate foils — high loyalty, high honesty,
moderate competence. Borderlands and Frontier get comparable
(staggered) raid / unrest / supply shocks so their *true* states are
roughly similar. Any divergence in the King's belief between them is
then almost entirely the integrity of the commander.

Candidate pool widened from 3 → 5 (Orla of Stenmark, Vanek the Younger)
because two-chain dismissals cycle through faster.

Sweep over 100 seeds × 300 ticks — King's end-of-run belief vs. truth,
parallel regions side by side:

| variable             |  Frontier  | Borderlands | ratio   |
| -------------------- | ---------: | ----------: | ------: |
| garrison_strength    |    +34.8%  |       +4.0% |    8.7× |
| food_stores          |    +48.8%  |       +4.5% |   10.8× |
| unrest               |    −22.2%  |       +2.2% |   ~10×  |

The intermediate rungs reflect their governors. Province (Mira: somewhat
dishonest, moderately corrupt) shows +2–7% errors. Marches (Cassia:
honest, loyal) shows ±2%. The reporter's integrity is now legible in
the data at every level.

**Why this matters:** until now, divergence was a single signal — the
King saw inflated Frontier numbers but had nothing to compare them
against. With siblings, the King now sits on a *comparison artifact*.
Two frontier regions face comparable shocks; one reports calmly, the
other reports prosperity. A future "compare siblings" layer in the
King's policy has something concrete to act on. (Not added in this
commit — the point first was to surface the data, not to consume it.)

Other knock-on effects:

- Courier traffic ~doubled (lost 23 → 43, orders 15 → 33, actions
  10 → 20). Engine handles it without breaking a sweat — the
  discrete-event scheduler scales by *events*, not by actors.
- Dismissals went 3.1 → 3.5 per seed despite the wider pool, because
  there are now two governors that can fail their performance reviews.
  Cassia's chain stays mostly intact; Mira's still cycles regularly.
- 100/100 seeds remain narratively interesting; 0/100 silent.

Things this enables but doesn't implement:

1. **Comparison-based suspicion.** King notices that Aldric's region
   reports a 1500-garrison raid as 1450; Talen reports an 800-garrison
   raid as 850. A skill-check on the King (education? honesty?) against
   the reporting commander (loyalty? competence?) could trigger an
   investigation event.
2. **Collusion / conflict between siblings.** Cassia could
   *cross-corroborate* Aldric's report ("the King asked me — yes,
   Frontier looks fine") or *undermine* it ("I hear different from
   travellers"). Requires either a peer-message channel or routing via
   the King.
3. **Reputation gradient.** Each actor accumulates a perceived
   trustworthiness in the King's mind, separate from their actual
   traits. Belief weighting at relay/observation time would then drift
   with reputation, not just with hop count.

### 2026-06-02 — Stochastic forgery + skim (Claude Opus 4.7 via Claude Code)

Acting on the previous sweep's "dynamics are under-randomized" finding.
Both forgery and skimming gained a probability gate plus magnitude noise,
all derived from existing traits — no new actor fields, no new tunables
beyond two skim fraction bounds.

- **Forgery probability** per outgoing bad-news report:
  ``ambition * (1 - loyalty)`` (Aldric: 0.8 × 0.75 = 0.6).
  Severity multiplier ``uniform(0.5, 1.5)`` clamped to [0,1], so even when
  he does lie, the magnitude varies.
- **Skim probability** per decide cycle: same
  ``ambition * (1 - loyalty)`` formula.
- **Skim magnitude** is now ``uniform(0.02, 0.06) * food_stores *
  (1 + (1 - loyalty))`` — a small fraction of *current* stores, scaled by
  disloyalty. Replaces the fixed 60 food/cycle. The user's framing — "3%
  off the top is less likely to be noticed" — is the design intent.
- Detection-avoidance (small-and-steady vs. large-and-suspicious), inter-
  sibling collusion, and superior skill-checks against subordinates are
  deliberately deferred. Once siblings exist they become the natural
  next layer.

Sweep re-run (100 seeds × 300 ticks), Frontier deltas vs. previous build:

| variable               | mean before | mean after | p10..p90 before | p10..p90 after |
| ---------------------- | ----------: | ---------: | --------------- | -------------- |
| garrison_strength      |     +69%    |    +34%    | +57..+80 (23pt) | +3..+79 (76pt) |
| food_stores            |    +156%    |    +48%    | −23..+229       | −3..+106       |
| unrest                 |    −39%     |    −20%    | −46..−34 (12pt) | −54..−0 (53pt) |

Garrison spread widened **3.3×**, unrest spread widened **4.4×**. The
"institutional rot" pattern still appears in 100% of seeds, but its
*shape* now varies meaningfully across seeds — some runs Aldric lies
heavily and gets away with it; some he lies less, the King sees the
truth, and intervention happens earlier. That's the dynamic we wanted.

Dismissals jumped 0.8 → 3.1 per seed, and `courier_undeliverable`
events from 1.9 → 7.2 — the Province governor now visibly cycles
through replacements, because *honest* reporting of a degrading region
keeps tripping the strike counter while *forged* reporting of an even
worse region (Frontier) keeps the corrupt commander in place. The
"most-loyal-looking liar survives, honest manager is punished" dynamic
is now reliably the dominant institutional story.

One latent bug surfaced and was fixed in the same change: when the
3-candidate pool was exhausted, `_dismiss_and_replace` would leave a
subordinate pointing at a dismissed superior, and the next
`decide_commander` would crash on `sim.actors[reports_to]`. Now reads
defensively via `.get()` and skips urgent reports if the chain is
broken. A larger candidate pool (or lazy instantiation per blueprint)
would also address this from the other side.

### 2026-06-02 — Multi-seed sweep #1 (Claude Opus 4.7 via Claude Code)

First aggregation across 100 seeds × 300 ticks of the Frontier scenario, via
`tools/sweep.py`. Numbers are the King's end-of-run belief vs. truth, expressed
as signed % error.

| Subject                       |  mean | median |  p10 |  p90 |
| ----------------------------- | ----: | -----: | ---: | ---: |
| Capital.{food,garrison,unrest}|  ≈ 0  |   ≈ 0  |  −8  |  +8  |
| Province.garrison_strength    |  +0.6 |  +0.3  |  −4  |  +5  |
| Province.unrest               |  −0.7 |  −1.9  |  −7  |  +9  |
| Frontier.garrison_strength    | **+69**| **+70**| **+57** | **+80** |
| Frontier.food_stores          | +156  |  +122  |  −23 | +229 |
| Frontier.unrest               |  −39  |  −41   |  −46 |  −34 |

Event counts (per seed): forgery ≈ 96, skim ≈ 34, courier_lost ≈ 23,
urgent_report ≈ 17, orders ≈ 15, actions ≈ 10. **100/100** seeds saw
forgery; **69/100** saw a dismissal; **0/100** were narratively silent.

What this tells us:

- The "institutional rot" pattern is **structurally robust**, not lucky. Every
  seed produces the politically-tinted divergence at the Frontier and almost
  none at Province / Capital where reporters are honest. The honest-vs-
  dishonest contrast is the central finding the design is meant to produce,
  and it's there in 100% of runs.
- However, divergence on `Frontier.garrison_strength` is **very tightly
  banded** (p10 +57, p90 +80). That's a ~23-point spread on a ~70-point
  mean — much narrower than I'd expect from a "noisy political system."
  The forgery trigger is binary (`loyalty < 0.4`) with severity derived
  deterministically from `(threshold − loyalty)`, and `forge_value` caps at
  2.5× true belief. So the King's eventual error is almost a function of
  `(Aldric's traits)`, not the seed. Stochastic inputs (observation noise,
  jitter, loss) are dwarfed by this structural ceiling.
- `Frontier.food_stores` is much wider (−23 to +229). That's the one
  variable where skimming directly competes with `SEND_SUPPLIES` orders —
  the timing race between drain and resupply gives randomness real leverage.
  This is the "interesting" variable in the current scenario.
- `Province.food_stores` has 63/100 seeds where Mira is dismissed and the
  new appointee has no belief about the variable yet — that's why the mean
  is dominated by a few outlier seeds (+514%). The honest replacement
  hasn't had time to observe before t=300.

Action items this surfaces:

1. **Forgery is too on-rails.** It needs at least one of: trait-driven
   per-report stochasticity ("does Aldric lie *this time*?"), a calibration
   risk (lies get caught when reality and report diverge too much), or
   superior counter-checks. Right now Aldric lies *every* time it's
   politically convenient, identically across all seeds.
2. **Skim rate is fixed at 60 food/cycle** (also noted in M3 obs). The
   30–35 skim count per seed is basically "decide cycles fired" — no
   variance at all. Tying skim magnitude to `ambition × (1 − loyalty)`
   with a random component would give the food curve real seed-sensitivity.
3. **Honest replacements need bootstrap belief.** When the King dismisses
   Mira at t=200 and Iselle has no belief about anything at t=300, the
   final snapshot reads as "no belief" rather than "honest fresh read."
   A new appointee should observe their region immediately on appointment
   (currently waits one `observe_every` cycle).
4. The 100/100 "narratively interesting" hit rate is a positive sign, but
   the metric is loose. A stricter sweep — "did the King act on a
   demonstrably wrong belief in a way that visibly hurt true state?" —
   would be more discriminating, and is the next iteration of this tool.

Net read: the pattern *is* what the design promised; the **dynamics are
under-randomized**. Before porting to Rust, the forgery and skim mechanics
want a stochastic layer so seed-to-seed variance reflects genuine political
uncertainty rather than just observation noise.

### 2026-05-26 — initial M1 build (Claude Opus 4.7 via Claude Code)

- Three-hop relay chain produces visible drift: at end of 200-tick seed=1 run, King
  believes Frontier ≈ 1255 against truth 1100 — ~14% overestimate, predominantly from
  the Commander's fear bias compounded by the Governor's corruption term.
- Province belief is reasonably accurate (~7% off) because it goes through only one
  relay hop, validating that confidence and accuracy should both degrade per hop.
- The raid-at-t=40 narrative beat works on the very first scenario, with no tuning
  needed. That's a positive sign the basic shape is right.
- Things that feel weak already and want attention before M2:
  - Actors observe their own region every tick, which floods the log. A cadence on
    *observation* (or aggregating into a digest) would make logs more readable.
  - The Commander's fear-inflated observations also become his own belief, so he
    "actually thinks" the garrison is bigger than it is. That's actually correct
    per the blueprint (actors act on known state), but it muddies the relay term —
    worth separating "what I report" from "what I privately know" in M2.
  - Only one variable per region. Adding `food_stores` and `unrest` would let
    fear-bias direction differ per variable (low food = bad, suppress; high unrest
    = bad, suppress) and produce richer divergence patterns.

### 2026-05-26 — Discrete-event scheduler refactor (Claude Opus 4.7 via Claude Code)

Replaced the fixed-tick loop with a global priority queue of `Event`s. Same
behaviour shape, fundamentally different engine.

- `Simulation.tick: int` → `Simulation.now: float`. There is no fixed tick
  rate; logical time advances to the next scheduled event.
- Each actor schedules its own next OBSERVE / REPORT / DECIDE event after
  firing, instead of the engine polling everyone each tick. Idle actors
  consume zero cycles.
- Messages now schedule a `MESSAGE_ARRIVED` event at their ETA at dispatch
  time, instead of sitting in a per-bus heap polled every tick.
- Actions schedule an `ACTION_COMPLETE` event when started, instead of
  sitting in `sim.actions_in_flight`.
- Scripted scenario events become `SCRIPTED` events in the same queue.
- Same-seed runs remain byte-identical (determinism tests pass). The
  scheduler breaks time ties by insertion-order seq counter, so RNG
  consumption order is stable.
- 1000-tick scenario run drops to ~90 ms with 4 events/unit-time; the old
  loop did ~9 cadence-check no-ops per tick on top of the actual work.

Next layers this enables, **not** in this commit:

- Pull-based `INFO_REQUEST` as a third `MessageKind`, so the King can
  spend a courier to ask "what's actually going on?" rather than only
  waiting for ambient pushes.
- Eventual port to Rust/Tokio for real parallelism — the scheduler
  abstraction maps cleanly to async channels and the Actor schema
  is now language-neutral.

### 2026-05-26 — M3 political pressure (Claude Opus 4.7 via Claude Code)

The institutional failure modes the blueprint asks for now arise cleanly. The
Commander in the seed=1 scenario is dialled to `loyalty=0.25`, `ambition=0.8`,
which is enough to trigger both forgery and skimming from t=0.

Seed=1 trace (300 ticks):

- **t=0 onward**: Cmdr Aldric forges every Frontier report — food, garrison,
  and unrest are all reported in the "everything fine" direction regardless of
  belief. He simultaneously skims 60 food per decide cycle.
- **By t=80**: Frontier food has been skimmed to zero. Aldric's belief honestly
  says 0; his report says ~1. The King keeps issuing `SEND_SUPPLIES` from
  Province on the assumption that a slow drain is in progress; the food arrives
  and Aldric immediately resumes skimming it.
- **t=220**: King's belief about Province has crossed his garrison/unrest
  thresholds three decide cycles in a row (the SEND_SUPPLIES orders have drained
  Province food, and earlier scripted shocks pushed Province metrics around).
  Mira is dismissed for "3 consecutive bad reviews." Iselle Marn (competence
  0.9, loyalty 0.5) is appointed. Her appointment is driven by the King's
  high `education` weighting competence.
- **Late run**: the institutional rot at Frontier is *worse*. Iselle is honest
  and competent, so she relays Aldric's lies upward with minimal distortion —
  i.e. the King now reads more accurate forgeries. Final snapshot:

  | Region   | Variable           | Truth | King |  Δ    |
  | -------- | ------------------ | ----- | ---- | ----- |
  | Frontier | garrison_strength  | 800   | 1345 | +68%  |
  | Frontier | food_stores        | 355   | 219  | −38%  |
  | Frontier | unrest             | 0     | 15   |  +15  |
  | Province | food_stores        | 0     | 0    |   0   |

  The +68% garrison overestimate at Frontier dwarfs any divergence achievable
  in M1 or M2. That is the "institutional failure" the milestone was for. And
  it pairs with a *correctly* reported Province collapse (food=0 reported as
  0 by the honest new governor), giving a clear contrast between the
  reformed rung and the unreformed one.

Things to watch / address before M4:

- The King's review uses his *own belief* about each region. Aldric's forgeries
  push Frontier belief above the strike thresholds, so the King paradoxically
  thinks Frontier is going *well* — and rotates only Province where Mira is
  honestly reporting a degrading situation. The most loyal-looking liar
  survives; the honest middle manager is punished. That dynamic is dead-on
  for the blueprint and worth keeping as-is.
- The skim rate is fixed at 60 food/cycle. A trait-modulated rate would
  give a smoother gradient between "petty corruption" and "looting the
  province."
- Forgery is currently applied at outgoing-report time only. Forged orders
  (an actor altering an order before relaying it down) are a natural M4 topic.
- The candidate pool is static and small. Lazy instantiation of historical
  figures (blueprint §Lazy Instantiation) would scale this up cleanly.

### 2026-05-26 — M2 hierarchical decisions (Claude Opus 4.7 via Claude Code)

The closed loop works. Seed=1 trace from a 250-tick run:

- **t=40**: raid drops Frontier garrison 1500→800, unrest 40→70.
- **t=60**: King's first decision cycle after the raid. He orders only
  `SUPPRESS_UNREST` — *not* `REINFORCE`, because the Commander's fear-biased
  reports inflated the garrison number above the king's threshold.
  **This is the exact failure mode the design was built to surface**:
  political distortion delays a critical military decision by tens of ticks.
- **t=80**: Suppression order finally reaches the Commander (20 ticks after issue
  via Capital→Province→Frontier). The King also begins issuing `REINFORCE`
  and `SEND_SUPPLIES` orders as the bias-attenuated picture finally darkens
  enough.
- **t=88, 96, 104**: Commander sends URGENT food reports out-of-cadence
  because his *honest* local belief sees food crossing 500. Honest perception
  vs. politically-shaped reporting — both behaviors visible at once.
- **t=92**: First suppression *succeeds*, unrest 95→62. Second wave on
  another seed has historically backfired (110 from 95), demonstrating the
  competence-modulated stochastic outcome.
- **t=96–116**: Reinforcements arrive (90 troops then 57), food arrives (217).
  The action queue produces a believable cadence of consequences trickling
  back to the front.

End-of-run truth vs. King's belief stays politically tinted: Frontier
garrison truth 997, king believes 1145; Province garrison truth 603,
king 514 (notable undershoot — the Governor's noisy observation that run
landed below truth and the relay biases didn't overcome it).

Things to watch / address before M3:

- The King re-issues the same orders every decide cycle (no memory of
  pending orders). That actually produces a great narrative — escalating
  intervention because feedback hasn't arrived yet — but it would feel
  better if the King tracked "I've already asked for this" with a cooldown.
- The Governor's REINFORCE/SUPPRESS handling is hardcoded; standing
  directives with priorities are a clean M3 generalization.
- Forgery, interception, and alteration of orders/reports would
  immediately make this much more game-like.
- The Commander's autonomous food alarms fire every decide cycle while
  food remains below threshold — should fire once per crossing.

### 2026-05-26 — pre-M2 refactor (Claude Opus 4.7 via Claude Code)

Addressed all three items from the M1 observations:

- **Perception is now honest.** Fear bias moved from `observe()` to `relay()` so an
  actor's *private* belief reflects what they actually saw; distortion enters only
  when they *report* upward. This will make M2 decisions readable — a commander
  acts on what they truly believe, then sends a politically-shaped version to
  superiors.
- **Multi-variable regions with polarity.** Each region now tracks
  `garrison_strength`, `food_stores`, and `unrest`. Variable metadata in
  `world.VARIABLES` gives each a `polarity` (+1 / −1) so the same fear and
  corruption terms can push every variable in the "good news" direction. End-of-run
  for seed=1 shows the desired emergent pattern:
  - Frontier garrison: truth 1100 → king 1199 (inflated, low = bad news)
  - Frontier unrest:   truth 70  → king 60   (understated, high = bad news)
  - Frontier food:     truth 1000 → king 1149 (inflated)

  All three Frontier biases bend the same political way — the King is reading a
  systematically rosier version of reality, exactly as designed.
- **Observation cadence.** Each actor has an `observe_every` interval; the log
  is roughly 4× shorter and easier to follow event-to-event.

Nothing felt missing for M2 entry after this pass. Next: decisions from belief
(M2 proper) — at minimum, governors and commanders ordering reallocations
based on what they believe vs. what is true.

---

## Layout

```
src/infosim/
  world.py            # World, Location (topology only), STATS (polarity table)
  actors.py           # Actor, Traits, BeliefRecord; stats, cadences, inboxes
  reports.py          # Report + observe() / relay() + forge_value()
  orders.py           # Order, OrderKind (targets actor ids)
  requests.py         # InfoRequest, InfoResponse, PendingRequest
  messages.py         # MessageBus + MessageKind (REPORT | ORDER | INFO_REQUEST | INFO_RESPONSE)
  actions.py          # ActionInFlight + transfer_garrison / suppress_unrest / send_supplies
  personnel.py        # Candidate pool, appoint / dismiss / pick_replacement
  policy.py           # compatibility facade for the policies package
  policies/
    constants.py      # current scenario thresholds
    corruption.py     # skimming policy
    hierarchy.py      # subordinate traversal / routing helpers
    info_requests.py  # INFO_REQUEST / INFO_RESPONSE handling
    orders.py         # downward order dispatch and middle-rung routing
    review.py         # peer review, strikes, dismissal / replacement
    roles.py          # decide_* and run_policy role dispatch
  scheduler.py        # Discrete-event Scheduler + Event/EventKind primitives
  sim.py              # Simulation: dispatches events, owns world+actors+bus+pool
  logging_setup.py    # JSONL + human dual-sink event log
  scenarios/
    frontier.py       # wide frontier scenario (1/2/3 commanders) + CLI
    deep_chain.py     # 4-level scenario validating arbitrary depth
    space_miner.py    # CEO/Manager/Captain economy with mobile Commanders
tools/
  inspect_run.py      # filter a JSONL run by actor / location / kind / subject / time range
  sweep.py            # multi-seed aggregation
  stress.py           # parameter-stress comparison
tests/
  _runner.py          # stdlib test runner (no pytest)
  test_*.py
```

---

## Out of scope (deliberately)

- Any visual output → Milestone 4.
- Fully generic deep-hierarchy gameplay policy beyond the validated
  4-level scenario.
- Standing-directive data structure with priority resolution (thresholds remain hardcoded
  in `policies/constants.py`).
- Forged *orders* (a subordinate altering a directive before relaying it down).
- Interception of couriers by hostile actors.
- Lazy instantiation of historical figures from a large population pool.
