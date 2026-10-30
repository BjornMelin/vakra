# Running a cut

```bash
capstone/run/run_cut.sh capstone/run/configs/b0.conf
N=5 TRACING=1 RUN_ID=b0_n5 capstone/run/run_cut.sh capstone/run/configs/b0.conf   # env overrides config
```
- **Config files** (`configs/*.conf`) are non-secret bash `KEY=VALUE` files. They cover the model, endpoint, temperature, reasoning effort, N, shards, capabilities, judge endpoint/model, tracing, and paths. Any variable already exported in the environment takes precedence. The keys for the local vLLM default to `dummy`.
- **Agents:** for each capability, `SHARDS` processes split the domains round-robin.
- **Evaluator:** runs **one capability at a time** by default. In earlier runs, concurrent evaluators collided on the same MCP containers. `EVAL_PARALLEL=1` opts back in to running them concurrently.
- **Judge:** `JUDGE_ENDPOINT` and `JUDGE_MODEL` are read by `evaluator/judge.py`. The defaults are still upstream Groq.
- **Reasoning effort:** `REASONING_EFFORT=low|medium|high` is sent to vLLM as `LITELLM_EXTRA_BODY={"reasoning_effort": ...}`. This doesn't happen if you've set `LITELLM_EXTRA_BODY` yourself.
- **Manifest:** `$RUN/config.json` (`python -m capstone.run.manifest`) records:
  - run id, variant, model, provider, temperature, reasoning effort, N, shards, capabilities and timeouts
  - judge settings
  - vLLM `/version` and `/v1/models`, plus the local `vllm serve` command line (credentials redacted) and the configured flags
  - git SHA, branch and dirty files
  - package versions, an allow-listed set of env vars, and phase timestamps/exit codes (UTC)
- **Analysis:** at the end, the script runs `python -m capstone.analysis summarize` into `$RUN/analysis` (turn this off with `ANALYZE=0`).
