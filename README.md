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

## What the scenario does (M1 + M2)

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

5. On a slower **decide cadence** each actor runs its policy (`src/infosim/policy.py`). The King
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
  world.py            # World, Region, VARIABLES (with polarity)
  actors.py           # Actor, Traits, BeliefRecord; observe/report/decide cadences; inbox
  reports.py          # Report + observe()/relay() transformation pipeline
  orders.py           # Order, OrderKind
  messages.py         # MessageBus + MessageKind (REPORT | ORDER)
  actions.py          # ActionInFlight + transfer_garrison / suppress_unrest / send_supplies
  personnel.py        # Candidate pool, appoint / dismiss / pick_replacement
  policy.py           # decide_king (orders + reviews) / decide_governor / decide_commander
                      # forgery, skimming, performance reviews live here
  sim.py              # Simulation tick loop (8 steps now fully wired)
  logging_setup.py    # JSONL + human dual-sink event log
  scenarios/
    frontier.py       # the three-region scenario + CLI entry
tools/
  inspect_run.py      # filter a JSONL run by actor / region / kind / subject
tests/
  _runner.py          # stdlib test runner (no pytest)
  test_*.py
```

---

## Out of scope (deliberately)

- Any visual output → Milestone 4.
- Multiple subordinates per superior, or hierarchy depth > 3.
- Standing-directive data structure with priority resolution (thresholds remain hardcoded
  in `policy.py`).
- Forged *orders* (a subordinate altering a directive before relaying it down).
- Interception of couriers by hostile actors.
- Lazy instantiation of historical figures from a large population pool.
