set shell := ["bash", "-euo", "pipefail", "-c"]

# Show available recipes.
default:
    @just --list

# Run the stdlib test suite.
test:
    @python3 tests/_runner.py

# Run tests plus a bytecode compile check.
check: test
    @python3 -m compileall -q src tests tools

# Run a scenario: scenario can be "frontier", "deep_chain", "deepchain", or "space_miner".
run scenario="frontier" seed="1" ticks="200" runs_dir="runs":
    #!/usr/bin/env bash
    set -euo pipefail
    case "{{scenario}}" in
        frontier)
            module="infosim.scenarios.frontier"
            ;;
        deep_chain|deepchain)
            module="infosim.scenarios.deep_chain"
            ;;
        space_miner|spaceminer)
            module="infosim.scenarios.space_miner"
            ;;
        *)
            echo "Unknown scenario: {{scenario}}" >&2
            exit 2
            ;;
    esac
    output=$(PYTHONPATH=src python3 -m "$module" --seed "{{seed}}" --ticks "{{ticks}}" --runs-dir "{{runs_dir}}")
    paths="${output#Wrote }"
    jsonl_path="${paths%% and *}"
    log_path="${paths##* and }"
    echo "JSONL: $(realpath "$jsonl_path")"
    echo "Log:   $(realpath "$log_path")"

# Run the frontier scenario.
frontier seed="1" ticks="200" runs_dir="runs":
    @just run frontier "{{seed}}" "{{ticks}}" "{{runs_dir}}"

# Run the deep-chain scenario.
deep-chain seed="1" ticks="400" runs_dir="runs":
    @just run deep_chain "{{seed}}" "{{ticks}}" "{{runs_dir}}"

# Run the space-miner scenario.
space-miner seed="1" ticks="500" runs_dir="runs":
    @just run space_miner "{{seed}}" "{{ticks}}" "{{runs_dir}}"

# Generate a plain HTML debug map. Defaults to the latest runs/*.jsonl file.
map path="" scenario="" out="":
    #!/usr/bin/env bash
    set -euo pipefail
    jsonl_path="{{path}}"
    if [ -z "$jsonl_path" ]; then
        jsonl_path=$(find runs -maxdepth 1 -type f -name '*.jsonl' -printf '%T@ %p\n' \
            | sort -nr \
            | head -n 1 \
            | cut -d' ' -f2-)
        if [ -z "$jsonl_path" ]; then
            echo "No JSONL run files found under runs/" >&2
            exit 2
        fi
    fi
    args=()
    if [ -n "{{scenario}}" ]; then
        args+=(--scenario "{{scenario}}")
    fi
    if [ -n "{{out}}" ]; then
        args+=(--out "{{out}}")
    fi
    output=$(python3 tools/map_run.py "$jsonl_path" "${args[@]}")
    html_path="${output#Wrote }"
    echo "HTML:  $(realpath "$html_path")"

# Inspect a run JSONL file. Optional filters mirror tools/inspect_run.py.
inspect path actor="" region="" kind="" subject="" from_time="" to_time="":
    #!/usr/bin/env bash
    set -euo pipefail
    args=()
    if [ -n "{{actor}}" ]; then
        args+=(--actor "{{actor}}")
    fi
    if [ -n "{{region}}" ]; then
        args+=(--region "{{region}}")
    fi
    if [ -n "{{kind}}" ]; then
        args+=(--kind "{{kind}}")
    fi
    if [ -n "{{subject}}" ]; then
        args+=(--subject "{{subject}}")
    fi
    if [ -n "{{from_time}}" ]; then
        args+=(--from-time "{{from_time}}")
    fi
    if [ -n "{{to_time}}" ]; then
        args+=(--to-time "{{to_time}}")
    fi
    python3 tools/inspect_run.py "{{path}}" "${args[@]}"

# Inspect events by kind.
inspect-kind path kind:
    @python3 tools/inspect_run.py "{{path}}" --kind "{{kind}}"

# Inspect events by region/location.
inspect-region path region:
    @python3 tools/inspect_run.py "{{path}}" --region "{{region}}"

# Inspect events by actor id.
inspect-actor path actor:
    @python3 tools/inspect_run.py "{{path}}" --actor "{{actor}}"

# Run the multi-seed sweep.
sweep seeds="50" ticks="300" seed_start="1":
    @PYTHONPATH=src python3 tools/sweep.py --seeds "{{seeds}}" --ticks "{{ticks}}" --seed-start "{{seed_start}}"

# Run the stress profile comparison.
stress seeds="50" ticks="300" seed_start="1":
    @PYTHONPATH=src python3 tools/stress.py --seeds "{{seeds}}" --ticks "{{ticks}}" --seed-start "{{seed_start}}"
