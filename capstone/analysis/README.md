# Analysis pipeline

```bash
python -m capstone.analysis summarize RUN [RUN ...] [--out DIR] [--labels error_labels.csv] \
    [--exclude-uuids reference_wrong.txt] [--price-in USD_PER_M --price-out USD_PER_M]
python -m capstone.analysis compare RUN_A RUN_B [--resamples 10000 --seed 0] [--exclude-uuids ...]
python -m capstone.analysis trace RUN [--uuid U --capability C] [--labels ...]
```
Shared options: `--gt-root data/train` (the reference answers and tool paths), `--threshold 1.0` (an item counts as correct when score ≥ threshold), `--no-plots`, and `--out` (defaults to `analysis_out/`).

A **run dir** follows the layout that `capstone/run/run_cut.sh` writes:
- `cap<C>/<domain>.json` holds the predictions
- `eval/cap<C>.json` is the evaluator output
- `config.json` (optional) is the manifest
- `traces/spans-*.jsonl` (optional) holds the spans

## Outputs
| Command | Files |
|---|---|
| `summarize` | `accuracy_by_capability.csv` (with overall), `accuracy_by_domain.csv`, `cost_latency.csv`, `error_labels.csv`, `error_summary.csv`, `report.md`, `accuracy_by_capability.png`, `error_breakdown.png`, `latency.png` |
| `compare` | `comparison.csv`, `paired_items.csv`, `comparison.md`, `comparison.png` |
| `trace` | `example_trace_cap<C>_<uuid>.md`, a compact trace you can paste into slides. Without `--uuid` it picks a representative wrong item. |

## Definitions
- **Accuracy** is computed over *scored* items: items the evaluator returned a score for, minus any excluded uuids. Each row also reports `n_items`, `coverage = scored / items`, and a Wilson 95% CI. Missing predictions show up as lower coverage. They are not counted as wrong answers.
- **Latency** comes from the runner's per-item `duration_s`. **Tokens** and LLM-call counts come from the trace spans and are blank when a run wasn't traced. Cost is only estimated when you pass `--price-in/--price-out`.
- **Paired comparison** uses items scored in both runs:
  - exact McNemar on the discordant pairs (b = only A correct, c = only B correct), plus χ² with continuity correction;
  - a seeded percentile bootstrap CI for the mean score difference B − A.

## Error labels
Two headline labels (plan WS1.4), each with sub-reasons; `no_answer` and `policy_violation` are auxiliary:

| headline | sub-reasons |
|---|---|
| `not_supported` (A): the answer isn't backed by the tool outputs it should have come from | `wrong_tool`, `wrong_arguments`, `answer_not_in_output`, `no_answer` |
| `supported_but_wrong` (B): the answer is backed by tool output, but it's wrong | `wrong_reasoning`, `reference_wrong`, `policy_violation` |

The automatic first pass checks these rules in order (first match wins); every label records its confidence, evidence and `auto_rule`:
1. The uuid is in `--exclude-uuids`: `reference_wrong`.
2. Error, timeout or empty answer: `no_answer`.
3. Policy score 0: `policy_violation`.
4. Predicted tool calls differ from the reference path: `wrong_tool` or `wrong_arguments` (arguments compared case- and whitespace-insensitively).
5. Judge groundedness < 0.5: `answer_not_in_output`.
6. B1 deterministic check (`capstone/b1`): a value not traced to tool output gives `answer_not_in_output`; all values traced gives `wrong_reasoning`.
7. B1 judge verdict (free-text answers, only when a B1 run recorded one): unsupported gives `answer_not_in_output`, supported gives `wrong_reasoning`.
8. Otherwise the share of the answer's numbers and content words found in the tool outputs decides between `answer_not_in_output` and `wrong_reasoning`.
9. Calls match the reference: `wrong_reasoning` (low confidence); else unlabeled.

Rules 6-8 use tool outputs from the run's trajectory sidecars (`cap<C>/<domain>_trajectory.json`, written by the runner or `python -m capstone.b1 collect`), else traced spans, else the reference outputs when the calls match. `error_labels.csv` includes `b1_outcome`, `b1_path` and `tool_outputs_source`.

To label by hand, fill in `human_headline`, `human_subreason` and `human_notes` in `error_labels.csv` and pass the file back with `--labels`. Human labels override the automatic ones. Invalid headline/sub-reason pairs are rejected.

**Reference-wrong list:** a text file with one uuid per line. `#` comments and CSV files whose first column is the uuid are both accepted. Pass it with `--exclude-uuids`, and those items are dropped from accuracy and from paired tests.
