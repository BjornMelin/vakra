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
Two headline labels, each with sub-reasons:

| headline | sub-reasons |
|---|---|
| `not_supported`: the answer isn't backed by the tool outputs | `answer_not_in_output`, `no_answer` |
| `supported_but_wrong`: the answer is backed by tool output, but it's the wrong answer | `wrong_tool`, `wrong_arguments`, `wrong_reasoning`, `reference_wrong`, `policy_violation` |

The automatic first pass checks these rules in order, and every label records its confidence and evidence:
1. The uuid is in `--exclude-uuids`, so the label is `reference_wrong`.
2. Error, timeout or empty answer gives `no_answer`.
3. Policy score 0 gives `policy_violation`.
4. Judge groundedness < 0.5 gives `answer_not_in_output`.
5. If the predicted tool calls differ from the reference path, the label is `wrong_tool` or `wrong_arguments`. Argument comparison is case- and whitespace-insensitive.
6. Otherwise, the share of the answer's numbers and content words found in the tool outputs decides between `answer_not_in_output` and `wrong_reasoning`. The tool outputs come from the traced outputs, or from the reference outputs when the calls match the reference path.

To label by hand, fill in `human_headline`, `human_subreason` and `human_notes` in `error_labels.csv` and pass the file back with `--labels`. Human labels override the automatic ones. Invalid headline/sub-reason pairs are rejected.

**Reference-wrong list:** a text file with one uuid per line. `#` comments and CSV files whose first column is the uuid are both accepted. Pass it with `--exclude-uuids`, and those items are dropped from accuracy and from paired tests.
