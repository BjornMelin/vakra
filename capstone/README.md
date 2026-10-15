# Capstone P0 gate (Oct 15, 2026): DATASCI 210 × IBM VAKRA

**Status:** environment is up and the smoke test passes 16/16. The evidence schema is drafted, and the model is **proposed, not agreed** (pending Thomas).

## What's here
| File | What |
|---|---|
| `schemas.py` | Pydantic `Evidence`, `Claim`, `Trace`, `SharedFixture` (draft for freeze) |
| `fixture_example.json` | Example fixture; validates against `SharedFixture` (`evidence/fixture_validation.txt`) |
| `data_stats.md` | Task counts per capability; where `sales_in_weather` appears |
| `evidence/smoke_test.txt` | `make test` output: 16/16 passed |
| `evidence/compose_ps.txt` | All 4 capability containers `Up` |
| `evidence/openrouter_routing_request_capture.json` | The request body the runner sends with provider pinning (captured against a local mock server, so no paid call was made) |

## Model (PROPOSED, to confirm with Thomas)
- Primary: `openai/gpt-oss-120b` on OpenRouter, provider order `crusoe/bf16` then `deepinfra/bf16`, with fallbacks on and `require_parameters: true` (only providers that support tool calls).
- Comparison: DeepSeek V4.1 Flash (check the OpenRouter slug before running).

## Reproduce on Linux / WSL (Ubuntu)
Prerequisites: Docker with at least 8 GB memory, `make`, `uv`, and about 45 GB of free disk.
```bash
uv venv -p 3.12 && source .venv/bin/activate
uv pip install -e ".[init,agents]" -r requirements_benchmark.txt
cp template_env .env              # add HF_TOKEN (Hugging Face read token)
export HF_TOKEN=hf_xxx
make download
```
**If `make download` fails with 403 / GatedRepoError** (our access request for `VAKRA-GatedTest` is still pending), download the public train split directly and point `data/test` at it:
```bash
hf download ibm-research/VAKRA --repo-type dataset --local-dir data/train   # or: huggingface-cli download ...
rm -rf data/test && ln -s train data/test
```
Check the layout first. The dataset may put `databases/` and `indexed_documents/` under `data/train`, while the containers expect them at `data/databases` and `data/indexed_documents`. Move or symlink them up one level if needed. `data/train` should end up with `capability_{1..4}_*/{input,output}`.

Then:
```bash
make build && docker compose up -d && docker compose ps
make test                          # smoke test: expect "Passed: 16/16"
```
(Plain `pytest tests` is not the smoke test. It fails at collection on `tests/unit` because of a missing `apis` module.)

## Running against OpenRouter (do NOT run until the key and model are agreed)
The runner's `litellm` provider forces `custom_llm_provider="openai"` and strips the first `openai/` from the model name. That means the model needs a **double prefix**, and the base URL and key come from env vars. This branch adds an opt-in `LITELLM_EXTRA_BODY` env var (`agents/llm.py`) that passes OpenRouter's `provider` routing through:
```bash
export LITELLM_BASE_URL=https://openrouter.ai/api/v1
export LITELLM_API_KEY=sk-or-...           # keep in .env, never commit
export LITELLM_EXTRA_BODY='{"provider":{"order":["crusoe/bf16","deepinfra/bf16"],"allow_fallbacks":true,"require_parameters":true}}'
python benchmark_runner.py --capability_id 1 --domain card_games \
  --max-samples-per-domain 5 --provider litellm --model openai/openai/gpt-oss-120b
```

Not committed on purpose: `.env`, `data/`, and the box-only `docker-compose.override.yml` (an offline HF cache mount).
