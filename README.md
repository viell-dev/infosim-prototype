# InfoSim — Distributed Information Strategy Simulation (Prototype)

This is the prototype sandbox for the design described in [`docs/blueprint.md`](docs/blueprint.md).
Its goal is not to be a game — it is to find out whether the **True / Known / Reported state**
separation produces interesting emergent narratives when read as logs. If reading the logs feels
like reading a believable little history of misinformation and delay, the concept is worth investing
in. If not, it isn't.

This repository implements **Milestone 1 — Information Sandbox** only. No graphics, no UI,
no decisions yet. Just regions, actors, couriers, reports, and divergence between truth and belief.

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
# default scenario, seed 1, 200 ticks
PYTHONPATH=src python3 -m infosim.scenarios.frontier --seed 1 --ticks 200

# tests
python3 tests/_runner.py

# inspect a run
python3 tools/inspect_run.py runs/frontier-seed1-*.jsonl --kind dispatch
python3 tools/inspect_run.py runs/frontier-seed1-*.jsonl --region Frontier
```

Outputs land in `runs/frontier-seed<N>-<timestamp>.{jsonl,log}`.

---

## What the M1 scenario does

`scenarios/frontier.py` wires a three-region line: **Capital → Province → Frontier**.

Three named actors form a hierarchy:

- **King Halric III** (Capital): high education, honest, low fear. Reports to no one.
- **Governor Mira of Halen** (Province): moderate competence, somewhat dishonest, fearful, ambitious.
- **Commander Aldric Vale** (Frontier): competent observer, but fearful of looking weak.

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

## Observations log

Append-only. Add notes as the design evolves.

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
  world.py            # World, Region, adjacency
  actors.py           # Actor, Traits, BeliefRecord
  reports.py          # Report + observe()/relay() transformation pipeline
  messages.py         # MessageBus — heap-queued courier delivery with loss/jitter
  sim.py              # Simulation tick loop
  logging_setup.py    # JSONL + human dual-sink event log
  scenarios/
    frontier.py       # the M1 three-region scenario + CLI entry
tools/
  inspect_run.py      # filter a JSONL run by actor / region / kind / subject
tests/
  _runner.py          # stdlib test runner (no pytest)
  test_*.py
```

---

## Out of scope (deliberately)

- Decisions / orders flowing downward → Milestone 2.
- Politics, loyalty consequences, appointments → Milestone 3.
- Any visual output → Milestone 4.
- More than one true variable per region — expand only once single-variable stories are alive.
