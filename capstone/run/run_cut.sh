#!/usr/bin/env bash
# Run one VAKRA cut (agents -> evaluator -> analysis) from a non-secret config.
#
#   capstone/run/run_cut.sh capstone/run/configs/b0.conf
#   N=5 TRACING=1 capstone/run/run_cut.sh capstone/run/configs/b0.conf
#   N=all PARALLEL=48 capstone/run/run_cut.sh capstone/run/configs/b0.conf   # full split
#
# Layout under $RUN_ROOT/$RUN_ID:
#   config.json               run manifest (capstone/run/manifest.py)
#   cap<C>/<domain>.json      agent predictions      logs/cap<C>_s<shard>.log
#                                                     (PARALLEL>0: logs/cap<C>_<domain>.log)
#   eval/cap<C>.json          evaluator output        logs/eval_cap<C>.log
#   traces/spans-<pid>.jsonl  span records when TRACING=1
#   analysis/                 capstone.analysis summarize output
#
# N=all (or 0) runs every task. SHARDS=k starts k runner processes per capability
# with domains dealt round-robin. PARALLEL=p instead runs one runner per
# (capability, domain), largest domains first, with p running at once across all
# capabilities; use it for full-split runs, where domain sizes vary 1-150 tasks.
#
# Evaluators run one capability at a time by default: concurrent evaluators
# start competing MCP sessions against the same containers and corrupted
# results in earlier runs. Set EVAL_PARALLEL=1 only if you know they are isolated.
set -euo pipefail

usage() { sed -n '2,6p' "$0" | sed 's/^# \{0,1\}//'; exit "${1:-0}"; }
[[ "${1:-}" == "-h" || "${1:-}" == "--help" ]] && usage 0
[[ $# -eq 1 ]] || usage 2

CONFIG_FILE=$(realpath "$1")
REPO=$(git -C "$(dirname "$0")" rev-parse --show-toplevel)
cd "$REPO"

# Config values are defaults: anything already exported in the environment wins.
load_config() {
  local line key
  while IFS= read -r line || [[ -n "$line" ]]; do
    [[ "$line" =~ ^[[:space:]]*([A-Z_][A-Z0-9_]*)= ]] || continue
    key=${BASH_REMATCH[1]}
    [[ -n "${!key+x}" ]] && continue
    eval "$line"
  done < "$CONFIG_FILE"
}
load_config

: "${VARIANT:=B0}" "${MODEL:?MODEL is required}" "${PROVIDER:=litellm}"
: "${LITELLM_BASE_URL:?LITELLM_BASE_URL is required}" "${TEMPERATURE:=0.0}" "${REASONING_EFFORT:=}"
: "${N:=2}" "${SHARDS:=8}" "${CAPS:=1 2 3 4}" "${SHARD_TIMEOUT_S:=1200}" "${AGENT_TIMEOUT_SECONDS:=300}"
: "${RUNNER_ARGS:=}" "${RUN_ROOT:=runs}" "${GT_ROOT:=data/train}" "${MCP_CONFIG:=benchmark/mcp_connection_config.yaml}"
: "${VENV:=}" "${EXCLUDE_UUIDS:=}" "${JUDGE_BACKEND:=groq}" "${JUDGE_ENDPOINT:=}" "${JUDGE_MODEL:=}"
: "${PARALLEL:=0}" "${EVAL_PARALLEL:=0}" "${TRACING:=0}" "${PHOENIX_COLLECTOR_ENDPOINT:=http://127.0.0.1:6006}"
: "${PHOENIX_PROJECT_NAME:=vakra-capstone}" "${VLLM_FLAGS:=}" "${ANALYZE:=1}"

if [[ -n "$VENV" ]]; then
  # shellcheck disable=SC1091
  source "$VENV/bin/activate"
fi

# Local vLLM ignores the key; never hard-code real keys in configs.
export LITELLM_API_KEY="${LITELLM_API_KEY:-dummy}" API_KEY="${API_KEY:-dummy}"
export LITELLM_BASE_URL AGENT_TIMEOUT_SECONDS JUDGE_BACKEND
[[ -n "$JUDGE_ENDPOINT" ]] && export JUDGE_ENDPOINT
[[ -n "$JUDGE_MODEL" ]] && export JUDGE_MODEL
if [[ -n "$REASONING_EFFORT" && -z "${LITELLM_EXTRA_BODY:-}" ]]; then
  export LITELLM_EXTRA_BODY="{\"reasoning_effort\": \"$REASONING_EFFORT\"}"
fi

RUN_ID=${RUN_ID:-$(tr '[:upper:]' '[:lower:]' <<<"$VARIANT")_$(date +%Y%m%d_%H%M%S)}
RUN="$RUN_ROOT/$RUN_ID"
mkdir -p "$RUN/eval" "$RUN/logs"
echo "$RUN" > "$RUN_ROOT/LATEST"

if [[ "$TRACING" == 1 ]]; then
  export VAKRA_TRACING=1 VAKRA_RUN_ID="$RUN_ID" VAKRA_AGENT_VARIANT="$VARIANT" VAKRA_TRACE_DIR="$RUN/traces"
  export PHOENIX_COLLECTOR_ENDPOINT PHOENIX_PROJECT_NAME
fi

declare -A DIRS=([1]=capability_1_bi_apis [2]=capability_2_dashboard_apis [3]=capability_3_multihop_reasoning [4]=capability_4_multiturn)
declare -A NAMES=([1]=capability_bi_apis [2]=capability_dashboard_apis [3]=capability_multihop_reasoning [4]=capability_multiturn)

[[ "$N" == all ]] && N=0
N_ARGS=(); (( N > 0 )) && N_ARGS=(--max-samples-per-domain "$N")

# Tasks selected per capability (min(N, domain size) summed over domains).
task_counts=$(python - "$GT_ROOT" "$N" $CAPS <<'PY'
import json, sys
from pathlib import Path
root, n, caps = Path(sys.argv[1]), int(sys.argv[2]), sys.argv[3:]
dirs = {"1": "capability_1_bi_apis", "2": "capability_2_dashboard_apis",
        "3": "capability_3_multihop_reasoning", "4": "capability_4_multiturn"}
out = {}
for c in caps:
    sizes = [len(json.loads(p.read_text())) for p in (root / dirs[c] / "input").glob("*.json")]
    out[c] = sum(min(s, n) if n > 0 else s for s in sizes)
print(json.dumps(out))
PY
)

manifest() { python -m capstone.run.manifest "$@"; }
eval_flag=(); [[ "$EVAL_PARALLEL" == 1 ]] && eval_flag=(--eval-parallel)
# shellcheck disable=SC2086
manifest start --run-dir "$RUN" --run-id "$RUN_ID" --variant "$VARIANT" --model "$MODEL" \
  --provider "$PROVIDER" --temperature "$TEMPERATURE" ${REASONING_EFFORT:+--reasoning-effort "$REASONING_EFFORT"} \
  ${N_ARGS:+--n "$N"} --shards "$SHARDS" --parallel "$PARALLEL" --task-counts "$task_counts" --capabilities $CAPS --shard-timeout "$SHARD_TIMEOUT_S" \
  --runner-args "$RUNNER_ARGS" --config-file "$CONFIG_FILE" --vllm-flags "$VLLM_FLAGS" "${eval_flag[@]}"

on_interrupt() {
  manifest finish --run-dir "$RUN" --status interrupted >/dev/null 2>&1 || true
  kill 0 2>/dev/null || true
  exit 130
}
trap on_interrupt INT TERM

# ---- agents: SHARDS processes per capability, domains round-robin ----------
manifest mark --run-dir "$RUN" --event agents_started
agent_failures=0
run_agents_queue() {
  # One job per (capability, domain), largest first, PARALLEL slots in total.
  local C d n jobs="$RUN/logs/agent_jobs.tsv"
  : > "$jobs"
  for C in $CAPS; do
    for d in "$GT_ROOT/${DIRS[$C]}/input"/*.json; do
      n=$(python -c 'import json,sys; print(len(json.load(open(sys.argv[1]))))' "$d")
      printf '%s\t%s\t%s\n' "$n" "$C" "$(basename "$d" .json)" >> "$jobs"
    done
  done
  sort -t$'\t' -k1,1nr -o "$jobs" "$jobs"
  export RUN SHARD_TIMEOUT_S PROVIDER MODEL TEMPERATURE RUNNER_ARGS
  export N_ARGS_STR="${N_ARGS[*]:-}"
  # shellcheck disable=SC2016
  cut -f2,3 "$jobs" | xargs -P "$PARALLEL" -L1 bash -c '
    C=$0 d=$1
    # shellcheck disable=SC2086
    timeout "$SHARD_TIMEOUT_S" python benchmark_runner.py --capability_id "$C" --domain "$d" \
      $N_ARGS_STR --provider "$PROVIDER" --model "$MODEL" --temperature "$TEMPERATURE" \
      --output "$RUN/cap$C" $RUNNER_ARGS > "$RUN/logs/cap${C}_$d.log" 2>&1 \
      || { echo "WARN: job cap$C/$d exited $? (see $RUN/logs/cap${C}_$d.log)" >&2; exit 1; }
  ' || agent_failures=1
}
if (( PARALLEL > 0 )); then
  run_agents_queue
else
  declare -a PIDS=() LABELS=()
  for C in $CAPS; do
    mapfile -t DOMS < <(find "$GT_ROOT/${DIRS[$C]}/input" -maxdepth 1 -name '*.json' -printf '%f\n' | sed 's/\.json$//' | sort)
    for ((s = 0; s < SHARDS; s++)); do
      ARGS=()
      for i in "${!DOMS[@]}"; do (( i % SHARDS == s )) && ARGS+=(--domain "${DOMS[$i]}"); done
      (( ${#ARGS[@]} )) || continue
      # shellcheck disable=SC2086
      timeout "$SHARD_TIMEOUT_S" python benchmark_runner.py --capability_id "$C" "${ARGS[@]}" \
        "${N_ARGS[@]}" --provider "$PROVIDER" --model "$MODEL" --temperature "$TEMPERATURE" \
        --output "$RUN/cap$C" $RUNNER_ARGS > "$RUN/logs/cap${C}_s$s.log" 2>&1 &
      PIDS+=($!); LABELS+=("cap${C}_s$s")
    done
  done
  for i in "${!PIDS[@]}"; do
    if ! wait "${PIDS[$i]}"; then
      echo "WARN: shard ${LABELS[$i]} exited non-zero (see $RUN/logs/${LABELS[$i]}.log)" >&2
      agent_failures=$((agent_failures + 1))
    fi
  done
fi
manifest mark --run-dir "$RUN" --event agents_finished --exit-code "$agent_failures"

# ---- evaluator: sequential by default --------------------------------------
manifest mark --run-dir "$RUN" --event eval_started
run_eval() {
  local C=$1
  python evaluator/evaluator.py --capability_name "${NAMES[$C]}" --gt_root "$GT_ROOT/${DIRS[$C]}/output" \
    --pred_root "$RUN/cap$C" --output "$RUN/eval/cap$C.json" --mcp-config "$MCP_CONFIG" \
    > "$RUN/logs/eval_cap$C.log" 2>&1
}
eval_failures=0
if [[ "$EVAL_PARALLEL" == 1 ]]; then
  declare -a EPIDS=()
  for C in $CAPS; do run_eval "$C" & EPIDS+=($!); done
  for p in "${EPIDS[@]}"; do wait "$p" || eval_failures=$((eval_failures + 1)); done
else
  for C in $CAPS; do
    if [[ ! -d "$RUN/cap$C" ]]; then echo "WARN: no predictions for cap$C" >&2; eval_failures=$((eval_failures + 1)); continue; fi
    run_eval "$C" || { echo "WARN: evaluator cap$C failed (see $RUN/logs/eval_cap$C.log)" >&2; eval_failures=$((eval_failures + 1)); }
  done
fi
manifest mark --run-dir "$RUN" --event eval_finished --exit-code "$eval_failures"

# ---- analysis ----------------------------------------------------------------
if [[ "$ANALYZE" == 1 ]]; then
  analysis_args=(summarize "$RUN" --gt-root "$GT_ROOT" --out "$RUN/analysis")
  [[ -n "$EXCLUDE_UUIDS" ]] && analysis_args+=(--exclude-uuids "$EXCLUDE_UUIDS")
  python -m capstone.analysis "${analysis_args[@]}" || echo "WARN: analysis failed" >&2
fi

status=ok; (( agent_failures + eval_failures )) && status=partial
trap - INT TERM
manifest finish --run-dir "$RUN" --status "$status"
echo "RUN_DONE $RUN ($status)"
