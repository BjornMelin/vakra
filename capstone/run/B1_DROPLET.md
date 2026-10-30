# Launching B1 on the droplet

Prerequisite: the droplet restored from the B0 snapshot (vLLM + MCP images,
`data/train`, `.venv`). Nothing here creates, resizes or destroys it.

```bash
# 0. code
cd ~/vakra && git fetch origin && git checkout capstone/b1-verifier && source .venv/bin/activate
python -m pytest capstone/tests -q                      # offline, ~3 s

# 1. services (as for B0)
docker compose up -d && docker compose ps               # MCP servers
curl -s localhost:8000/v1/models                        # vLLM serving gpt-oss-120b

# 2. B1 verdicts for the finished B0 run, no agent re-run
B0=/scratch/runs/b0_full_train_20261029
python -m capstone.b1 collect "$B0" /scratch/runs/b0_full_tool_outputs    # MCP re-exec, no LLM
python -m capstone.b1 gold-check --out /scratch/runs/b1_gold_check        # sanity: false alarms on gold
export JUDGE_ENDPOINT=http://localhost:8000 JUDGE_MODEL=gpt-oss-120b      # judge for free-text answers
python -m capstone.b1 replay "$B0" /scratch/runs/b1_replay_b0full \
  --tool-outputs /scratch/runs/b0_full_tool_outputs
python -m capstone.b1 eval /scratch/runs/b1_replay_b0full --gt-root data/train
python -m capstone.analysis summarize /scratch/runs/b1_replay_b0full --gt-root data/train \
  --out /scratch/runs/b1_replay_b0full/analysis

# 3. inline B1 (agent + check in one run); smoke first, then the full split
N=2 RUN_ID=b1_n2 capstone/run/run_cut.sh capstone/run/configs/b1.conf
N=all PARALLEL=48 EVAL_JOBS=8 RUN_ID=b1_full_train_$(date +%Y%m%d) \
  capstone/run/run_cut.sh capstone/run/configs/b1.conf
python -m capstone.b1 eval /scratch/runs/b1_full_train_<date>
python -m capstone.analysis compare "$B0" /scratch/runs/b1_full_train_<date>
```

Notes
- `--no-judge` on `replay`, or `judge.enabled=false`, keeps everything
  deterministic (judge-bound answers become `insufficient_evidence`).
- Inline B1 adds one judge call only for free-text / untraced-name answers;
  check latency and judge tokens are reported separately by `eval`.
- In `flag` mode (default) B1's scored answers equal B0's, so accuracy only moves
  with `on_reject=abstain`; then rescoring is required (`run_cut.sh` does it
  inline; for `replay`, rerun the evaluator on the `needs_rescore` capabilities
  with `SKIP_AGENTS=1 RUN_ID=<replay dir>`).
- Train split only; no leaderboard submissions.
