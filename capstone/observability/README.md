# Tracing VAKRA runs with Arize Phoenix

Tracing is **opt-in**. If `VAKRA_TRACING` is unset, `benchmark_runner.py` behaves exactly as it does upstream and imports nothing extra.

## What gets traced
- **One root span per benchmark item.** `vakra.task` is a CHAIN span whose input is the query and whose output is the final answer, plus `vakra.status`, `vakra.n_tool_calls` and `vakra.duration_s`.
- **Every LLM call** (`ChatLiteLLM`, i.e. `--provider litellm`), with prompt, completion and total token counts and latency. The OpenInference LangChain instrumentor captures these.
- **Every MCP tool call.** The agent calls MCP tools through LangChain `StructuredTool` wrappers, so each call shows up as a TOOL span with its arguments and output.
- **Tags on every span**, so you can filter on them in Phoenix: `vakra.run_id`, `vakra.variant` (B0/B1/B2), `vakra.capability_id`, `vakra.domain` and `vakra.uuid`. Spans also get `session.id = <run_id>:<uuid>`, which groups each task's spans into one Phoenix session.

We deliberately don't use the LiteLLM instrumentor. It would record the same LLM calls a second time.

## Setup
```bash
uv pip install -r capstone/requirements.txt          # client side (agent venv)
capstone/observability/start_phoenix.sh              # server: own venv, tmux session "phoenix"
capstone/observability/start_phoenix.sh status       # / stop
```
`start_phoenix.sh` installs the pinned `arize-phoenix` (`requirements-phoenix-server.txt`) into its own venv, which defaults to `/scratch/phoenix/.venv`. It then runs `phoenix serve` bound to **127.0.0.1:6006** and keeps its data in `PHOENIX_WORKING_DIR`, which defaults to `/scratch/phoenix/data`.

## Running with tracing
```bash
export VAKRA_TRACING=1
export PHOENIX_COLLECTOR_ENDPOINT=http://127.0.0.1:6006   # "none" = JSONL only
export PHOENIX_PROJECT_NAME=vakra-capstone
export VAKRA_RUN_ID=b0_20261029 VAKRA_AGENT_VARIANT=B0
export VAKRA_TRACE_DIR=$RUN/traces                        # optional local JSONL copy
python benchmark_runner.py --capability_id 2 ... --provider litellm --model gpt-oss-120b
```
`capstone/run/run_cut.sh` sets all of these when `TRACING=1` is in the config.

| Variable | Default | Meaning |
|---|---|---|
| `VAKRA_TRACING` | off | `1/true/yes/on` turns tracing on |
| `PHOENIX_COLLECTOR_ENDPOINT` | `http://127.0.0.1:6006` | Phoenix base URL (spans are posted to `/v1/traces`) |
| `PHOENIX_PROJECT_NAME` | `vakra-capstone` | Phoenix project |
| `VAKRA_RUN_ID` | unset | run identifier stamped on spans |
| `VAKRA_AGENT_VARIANT` | `B0` | B0 / B1 / B2 |
| `VAKRA_TRACE_DIR` | unset | also write `spans-<pid>.jsonl` here (one file per shard process) |
| `VAKRA_TRACE_MAX_CHARS` | 4000 | truncation for input/output values in the JSONL copy |

When tracing is on, it replaces the runner's own `--phoenix` flag. Only one tracer provider gets installed.

## Viewing from your laptop
Phoenix listens only on localhost on the droplet. To view it, tunnel the port:
```bash
ssh -N -L 6006:127.0.0.1:6006 <user>@<droplet-ip>
# open http://localhost:6006 → project "vakra-capstone"
```
Useful span filters (Phoenix filter box; uuid, variant and span_kind forms were tested against arize-phoenix 20.27.0):
- `vakra.uuid == 'abc-123'`: every span for one task (root, LLM and tool)
- `vakra.variant == 'B1' and vakra.capability_id == 2`
- `span_kind == 'TOOL' and vakra.uuid == 'abc-123'`: the exact MCP calls for that task
- `vakra.status != 'success'`: root spans for items that errored or timed out
- Sessions view: one session per `run_id:uuid`

Dotted keys are nested paths, so write `vakra.uuid` or `attributes['vakra']['uuid']`, not `attributes['vakra.uuid']`. The root span also carries `metadata['variant']`, `metadata['capability_id']` and so on.

## Offline JSONL
`$RUN/traces/spans-*.jsonl` has one compact record per span: ids, name, kind, latency, status, `vakra.*`, token counts, tool name, and truncated input/output. `python -m capstone.analysis` reads these files to get per-item token counts and the tool-output text that the error heuristics use. See `capstone/analysis/README.md`.
