# B1: answer check on the shared harness

B0 is plain ReAct. B1 is B0 plus **one post-answer step**: before the answer is
scored, check that its values trace back to the tool outputs the agent saw.
B2 (one recovery step) will plug into the same hook. All three variants share
`benchmark_runner.py`; the variant is a flag:

```bash
python benchmark_runner.py ... --variant B1 --verifier-config capstone/run/configs/b1_verifier.json
capstone/run/run_cut.sh capstone/run/configs/b1.conf      # same, via the run script
```

`capstone/variants.py` maps `B0 -> no step`, `B1 -> capstone.b1.step.B1Step`,
`B2 -> NotImplementedError` (until Nov 18).

## What the check does
1. **Extract** checkable values from the answer (`values.py`): numbers (with
   `$`, `%`, `k/million/billion` scale and units), dates (ISO, `Jan 2, 2020`,
   `2/1/2020`, with or without time), IDs (mixed letter+digit tokens) and
   capitalized names. List markers, years-as-ordinals and sentence-start capitals
   are skipped.
2. **Trace** each value in the evidence (`evidence.py`): every tool output of
   the trajectory (cap1 includes the `get_data` initial data), the query, and
   for cap4 the earlier turns. Matching is after normalization: number tolerance
   follows the precision the answer printed (`1.2649` supports `1.26`, not `1.27`);
   `1,200` reads as both 1200 and (1, 200); dates normalize to ISO; IDs and names
   match case-insensitively on word boundaries. `derivations` optionally lets
   row counts (`count`, default) or simple arithmetic (`simple`) count as traced.
3. **Decide** (`verifier.py`), recording `b1_path`:
   - `deterministic`: all values traced -> `accept`; any number/date/ID untraced
     -> `reject` (with `failed_field`); no tool output / agent error / empty
     answer -> `insufficient_evidence`; abstentions -> `accept` (nothing claimed).
   - `judge`: only for free text (no checkable values) or names that could not be
     traced (`names_missing="judge"`). The judge (`judge.py`, OpenAI-compatible)
     sees the question, answer and tool outputs, **never gold**, and replies
     `supported | unsupported | insufficient`. If the judge is disabled or
     unreachable the outcome is `insufficient_evidence` (`judge_unavailable`).
4. **Act** (`on_reject`, `on_insufficient`): `flag` (default) keeps the B0 answer
   and records the verdict; `abstain` replaces the answer with `abstain_text`.

Every verdict carries `outcome`, `b1_path`, `reason`, `failed_field`, the traced
values, `latency_s`, and judge tokens; it is logged per task in
`cap<C>/<domain>_trajectory.json` (with the tool outputs) and, when tracing is
on, as `b1.*` span attributes.

## Config (`capstone/run/configs/b1_verifier.json`)
| key | default | meaning |
|---|---|---|
| `derivations` | `count` | `none` strict; `count` list lengths count as traced; `simple` adds sum/mean/diff/ratio |
| `allow_query_values` | `true` | values repeated from the question are traced |
| `names_missing` | `judge` | untraced names go to the judge, or `reject` deterministically |
| `accept_abstentions` | `true` | "I could not find ..." is accepted |
| `on_reject` / `on_insufficient` | `flag` | or `abstain` |
| `judge.*` | enabled, endpoint/model from `JUDGE_ENDPOINT`/`JUDGE_MODEL` | key read from the env var named in `api_key_env` at call time; never stored |

`config.json` of a B1 run records the full verifier config, its sha256, the
judge prompt sha256 and the resolved judge model/endpoint (plan WS2).

## Offline commands (`python -m capstone.b1 ...`)
| command | does |
|---|---|
| `collect SRC OUT` | re-executes a finished run's tool calls on the MCP servers (no LLM, same coercion as the evaluator) and writes trajectory sidecars. Needed for B0 runs made before sidecars existed; the evaluator re-runs calls but does not store outputs. |
| `replay SRC OUT [--tool-outputs DIR]` | applies B1 to a finished run, writing a **new** run dir (source untouched). In `flag` mode answers are unchanged, so the evaluator output is copied; in `abstain` mode changed capabilities are listed as `needs_rescore`. |
| `eval RUN` | B1 verdicts vs gold: 2x2 (accept/reject/insufficient x correct/wrong) per capability and per `b1_path`, with false-alarm rate (reject or insufficient on correct), catch rate (reject on wrong), insufficient rate, reject precision, check latency and judge tokens, plus catch rate per error label. Labels use `auto_label(use_b1=False)` to avoid circularity. |
| `gold-check --out DIR` | runs B1 on gold answers with gold tool outputs (false alarms) and on seeded errors (number shift, date shift, ID swap, entity swap) for detection rate. Judge off by default. Files > `--max-file-mb` (200) are skipped and listed. |

## Error labels
`capstone/analysis/labels.py` gives every wrong answer a headline and a
sub-reason (plan WS1.4); deterministic rules first, judge-derived evidence only
when needed. First matching rule wins:

1. `reference_wrong` (uuid list) -> B
2. error / empty answer -> A `no_answer` (auxiliary)
3. evaluator policy score 0 -> B `policy_violation` (auxiliary)
4. predicted calls differ from gold -> A `wrong_tool` / `wrong_arguments`
5. evaluator groundedness < 0.5 -> A `answer_not_in_output`
6. B1 deterministic: reject -> A `answer_not_in_output`; all traced -> B `wrong_reasoning`
7. B1 judge: unsupported -> A; supported -> B
8. support ratio of answer tokens in tool outputs (legacy fallback)
9. calls match gold -> B `wrong_reasoning` (low confidence)
10. otherwise unlabeled (needs human)

Rules 6-7 use a recorded B1 verdict, or compute one deterministically (no judge)
from sidecar outputs or, when calls match gold, gold responses.

## Tests
`capstone/tests/test_b1_core.py` (extraction, tracing, verdicts, judge parsing,
config) and `capstone/tests/test_b1_pipeline.py` (sidecars, loader, replay,
collect with a fake MCP session, labels, 2x2 eval, gold check on real train-split
gold records in `fixtures/b1_gold_sample.json`, runner helpers, manifest, CLI).
No GPU, droplet or network.

## Open questions
See the PR description; defaults above are the conservative choices pending Bjorn's call.
