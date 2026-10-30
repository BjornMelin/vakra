# DATASCI 210 Capstone: master execution plan, 29 Oct to 15 Dec 2026

Project: "Checking the answer, not just the tool call". Thomas Young and Bjorn Melin, UC Berkeley MIDS.
Drafted Thu 29 Oct 2026, 7:10 PM MT, by Grok Bot (Capstone executor).

The canonical copy will be `capstone/PLAN.md` in the fork github.com/BjornMelin/vakra, with a Google Doc copy in the Berkeley Drive folder "210-Capstone" for Thomas. Grok Bot handles that placement. This file, `/workspace/berkeley/plans/capstone-master-plan.md`, is the working draft. If the three copies differ, the fork copy wins once it exists.

## How to use this plan

- Pick one numbered item, do its steps, check its acceptance criteria, and send the report described under "Report back" to the parent agent or the item owner.
- **OPEN** means a fact, path, number or decision that was not in any source on 29 Oct. Do not fill it in by guessing. Resolve it from a named source, or leave it OPEN and report it.
- Times are America/Denver (MT). All results are on the VAKRA public train split and stay internal unless Bjorn approves otherwise.
- Hard rules for every agent:
  - Never read `.env` files or credentials.
  - Never start, stop, snapshot or destroy the GPU droplet unless Bjorn explicitly asks in that session.
  - Never push, post, open issues, submit to the leaderboard, or contact IBM, faculty or Thomas without Bjorn's explicit approval of that specific action.
  - Never modify the source SQLite databases or the gold files.
  - Never invent a number. Every number in the paper or talk must trace to a saved artifact.

### Owners

| Owner | Responsibilities |
|---|---|
| Bjorn | ReAct runtime, verifier, VAKRA adapter, experiment runner, droplet operation (Timeline v1.2) |
| Thomas | Data audit, RCA tools, gold scoring, ground-truth labels (Timeline v1.2) |
| Grok Bot | Repo work on the box (branches, scripts, analysis code); never on the droplet unless asked |
| Capstone bot | Research, writing, reviews, slide and paper drafts, source checking |

### Sources this plan was built from

- `/workspace/berkeley/capstone-plan.md` (14 Oct)
- `/workspace/berkeley/VAKRA_Capstone_Implementation_Timeline.pdf` (Timeline v1.2, 8 Oct)
- `/workspace/berkeley/plans/2026-10-19-week-plan.md` and `2026-10-26-week-plan.md`
- `/workspace/berkeley/capstone-examples/` (research-log.md, slide-brief.md, questions-for-bjorn.md, c40/c43/c44 scripts)
- `/workspace/berkeley/p2deck/final/notes_final.json` and the P2 PDF
- `/workspace/berkeley/reviews/p2-urgent-review.md`
- `/workspace/berkeley/amd-baseline-runbook.md`
- `/workspace/berkeley/b0-tonight/`
- Local clone `/workspace/berkeley/vakra`, which has three branches:
  - `capstone/p0-gate`: checked out in the main clone
  - `capstone/b0-tonight`: worktree `/tmp/vk-b0`, head da5d4db
  - `capstone/observability`: worktree `/tmp/vk-obs`, head b26fb7c, no Phoenix commits yet as of 7:10 PM MT
- `gh api` returned EOF errors on 29 Oct, so the remote branch state was not checked.

### Facts from the sources that every item depends on

- **Train split.** 4,428 tasks across 137 domains: cap 1 has 33 domains / 1,324 tasks, cap 2 has 40 / 1,860, cap 3 has 28 / 346, cap 4 has 36 / 898. There are 63 SQLite databases (`vakra/capstone/data_stats.md`). sales_in_weather has 54 tasks in cap 2 and 16 in cap 4, 70 in total.
- **B0 run, 29 Oct.**
  - Runner: `capstone/b0/run_cut.sh` on `capstone/b0-tonight`.
  - Settings: `--provider litellm --model gpt-oss-120b --temperature 0.0`, `N=2` samples per domain (about 270 tasks), 8 shards per capability, output in `/scratch/runs/b0_HHMM` on the droplet. The exact run directory is OPEN.
  - Scoring broke on an MCP library rename (as relayed by the parent agent) and was being rerun. Rerun status is OPEN.
- **Evaluator judge.** The VAKRA evaluator (`evaluator/judge.py`) uses an LLM judge whose default model is `openai/gpt-oss-120b`. The droplet setup patches the judge endpoint to `JUDGE_ENDPOINT`. **The evaluator's judge may therefore be the same model as the agent.** Which judge model and endpoint actually scored the 29 Oct run is OPEN.
- **Data path.** The droplet setup links `data/test -> train`, so the runner reads train data through the `test` path.
- **Heuristic error split.** `capstone/b0/summarize.py` labels a wrong answer "not supported by tool output" when the evaluator judge's `groundedness_score < 0.5` on any turn, and "supported but still wrong" otherwise. This is a heuristic, not the final taxonomy.
- **Compute.**
  - AMD MI300X droplet (DigitalOcean billing). The runbook gives a list price of $2.59 per GPU-hour.
  - The runbook says the credit is $500 and expires 15 Dec. The parent brief says $483 remains and it expires 14 Dec. The exact expiry is OPEN; plan to 14 Dec.
  - Billing continues while a droplet is powered off.

---

## WS1. B0 full scoring and error analysis (due Wed 4 Nov)

### 1.1 Fix scoring after the MCP library rename
- [ ] Owner: Bjorn (droplet); Grok Bot can prepare the patch on the box. Due: Sat 31 Oct.
- Inputs:
  - Branch `capstone/b0-tonight` (`/tmp/vk-b0`): `run_cut.sh`, the `evaluator/` directory, `benchmark/mcp_connection_config.yaml`, `requirements_benchmark.txt` (`mcp>=1.0.0`, unpinned), `pyproject.toml` (`fastmcp>=0.2.0`).
  - Failing evaluator logs in `<RUN>/eval/cap*.log` on the droplet. Path is OPEN.
- Steps:
  - [ ] Get the exact error text from `<RUN>/eval/cap*.log` (Bjorn). The renamed module or symbol is OPEN.
  - [ ] Reproduce the import on the box in a fresh `uv` venv with the same requirements, with no droplet needed.
  - [ ] Pin the working `mcp` and `fastmcp` versions in a capstone requirements lock. Commit it on a new branch `capstone/b0-scoring-fix` (local commit only, no push without approval).
  - [ ] Rerun only the evaluator on the existing predictions; do not rerun the agent.
- Acceptance criteria:
  - `evaluator/evaluator.py` writes `<RUN>/eval/cap{1..4}.json` for all four capabilities.
  - `summarize.py <RUN>` prints n, accuracy and missing predictions per capability.
  - The pinned versions are recorded in `<RUN>/config.json`.
- Report back: the error text, the fix (versions pinned), the commit SHA, and per-capability n / accuracy / missing predictions, copied verbatim from `summarize.py`.

### 1.2 Record a run manifest for every run
- [ ] Owner: Bjorn. Due: 31 Oct, then for every run.
- Inputs: `<RUN>/commit.txt`, `start_epoch`, `end_epoch`, vLLM server log `/scratch/runs/vllm_server.log`.
- Steps:
  - [ ] Write `<RUN>/config.json` with: model id, vLLM version, temperature, reasoning effort (current value OPEN), max steps (current value OPEN), N per domain, shard count, commit SHA, prompt hash, judge model and endpoint, `mcp`/`fastmcp` versions, wall-clock time, and droplet hours.
- Acceptance criteria: no field is blank; unknown values are written as "OPEN".
- Report back: the path to `config.json` and the list of fields still OPEN.

### 1.3 Full B0 run at N=10 per domain (about 1,370 tasks)
- [ ] Owner: Bjorn. Due: Tue 3 Nov, so scoring is done by 4 Nov.
- N=10 is a default that Bjorn has not explicitly confirmed (see Decisions). The arithmetic is 137 domains × 10 = 1,370 tasks. Domains with fewer than 10 tasks will contribute fewer, so the real total is below 1,370 and is OPEN until counted.
- Inputs: `capstone/b0-tonight` runner with the WS1.1 fix, `N=10`, the same model and temperature as the 29 Oct run.
- Steps:
  - [ ] Count the exact task IDs selected per domain before the run and save `<RUN>/task_ids.json`. This becomes the candidate frozen set for WS8.
  - [ ] Run, score, summarize, then snapshot and destroy the droplet (WS10.1).
  - [ ] Log GPU-hours and estimated cost (droplet hours × $2.59).
- Acceptance criteria:
  - Eval JSON exists for all four capabilities.
  - Missing predictions are listed in a missing-run ledger (Timeline v1.2, Dec 2 gate).
  - `task_ids.json` is saved.
- Report back: per-capability n and accuracy, missing-run count, wall-clock time, GPU-hours, and the path to the run directory.

### 1.4 Error taxonomy and labeling of B0's wrong answers
- [ ] Owner: Thomas (label definitions, adjudication); Bjorn (second labeler); Grok Bot (labeling sheet and tooling). Due: Wed 4 Nov for the 29 Oct run; Sat 7 Nov for the N=10 run.
- Taxonomy (fixed before labeling; do not change after 4 Nov without a dated note):
  - Headline A, **not supported by tool output**: the final answer contains a value not present in, or not derivable from, any tool output in the trajectory. Sub-reasons:
    - **wrong tool**: the needed tool was never called.
    - **wrong arguments**: the right tool was called with wrong values.
    - **answer not in output**: the tools returned the right data, but the answer does not reflect it.
  - Headline B, **supported but still wrong**: every answer value traces to a tool output, but the evaluator scores it wrong. Sub-reasons:
    - **wrong reasoning**: a wrong aggregation, comparison or interpretation of correct output.
    - **reference wrong**: the gold answer is wrong; requires WS7 evidence.
  - One headline and one primary sub-reason per wrong answer. A secondary sub-reason is optional.
- Inputs: `<RUN>/cap*/*.json` (predictions with tool calls), `<RUN>/eval/cap*.json`, gold `data/train/<cap dir>/output/<domain>.json`, and `summarize.py` (heuristic pre-label only).
- Steps:
  - [ ] Write `capstone/analysis/labeling_guide.md`: definitions, one worked example per sub-reason, and decision rules for ties.
  - [ ] Export one row per wrong answer to `capstone/analysis/labels_<run_id>.csv` with columns: task uuid, capability, domain, question, final answer, gold, tool calls, the judge's heuristic label, and empty label columns for each labeler.
  - [ ] Both Bjorn and Thomas label the same stratified random sample of wrong answers independently. Sample size is OPEN; suggest at least 50 or all wrong answers if fewer. Record the seed.
  - [ ] Compute Cohen's kappa on the headline label and on sub-reasons (WS4.4). Adjudicate disagreements and log the reason.
  - [ ] One labeler labels the rest; the second spot-checks a stated fraction (OPEN).
  - [ ] Compare the human headline labels with the judge heuristic in `summarize.py` and report the agreement. This tells us whether the heuristic can be used at all.
- Acceptance criteria:
  - Every wrong answer has a label.
  - Kappa is reported with n.
  - "reference wrong" appears only with a WS7 evidence ID.
- Report back: counts per headline and sub-reason per capability, kappa (headline and sub-reason), heuristic-versus-human agreement, and the path to the CSV.

---

## WS2. B1 verifier (due Wed 11 Nov)

### 2.0 Decision record
- Decided (Bjorn, relayed 29 Oct):
  - B1 is a **deterministic provenance check**: every value in the final answer (numbers, IDs, dates, units) must trace back to a value in some tool output in the same trajectory, after normalization.
  - A **model judge** is used **only for free-text answers** that have no checkable values.
  - Outcomes are accept / reject / insufficient evidence (Timeline v1.2 W5; P2 slide 13).
- Alternatives considered:

  | Option | Strengths | Weaknesses |
  |---|---|---|
  | LLM judge with the same model | Cheap; covers any answer | Correlated errors with the agent ("grading its own homework") |
  | LLM judge with a different model | Less correlated | Extra cost and another dependency |
  | Pure deterministic check | Reproducible; no added model cost | Cannot judge free text |
  | Hybrid (chosen) | Deterministic on values; judge only where needed | Must report the two parts separately |

- Why it answers the P2 "same-model checker" critique: the value check uses no model. The judge part is reported separately (Timeline W5: "optional semantic causal-claim judge must be reported separately"), so its share of decisions and of false alarms is visible.
- OPEN: which judge model is used for free text. Same as the agent, or different? If different, which one? Also OPEN: how free-text answers are detected (for example, no numeric, ID or date tokens after extraction, or an answer-type field in the task).

### 2.1 Value extraction and normalization
- [ ] Owner: Bjorn; Grok Bot may draft. Due: Thu 5 Nov.
- Inputs: B0 predictions from WS1.3; `capstone/schemas.py` (verifier result fields: passed / failed / not_applicable / insufficient_evidence, failed_field, evidence_ids, allowed action).
- Steps:
  - [ ] Write an extractor for numbers (including thousands separators, percentages and units), IDs, dates (several formats normalized to ISO) and unit words.
  - [ ] Write a normalizer for numeric tolerance. Integer-unit tolerance is from Timeline W7; the float tolerance is OPEN.
  - [ ] Build an index of the same normalized values from every tool output in the trajectory.
  - [ ] Write unit tests: at least one per value type, plus known traps (rounding, derived values such as sums that appear in no single output).
- Policy for derived values: the Timeline grounding rule allows a "verified deterministic derivation". Whether B1 recomputes simple derivations (sum, difference, count) or rejects them is OPEN and must be decided by Bjorn before 2.3.
- Acceptance criteria: the tests pass, and the extractor recovers the answer values on a hand-checked sample of 20 B0 answers (sample to be drawn by Grok Bot and checked by Bjorn).
- Report back: test results, the extraction accuracy on the sample, and the derivation-policy decision.

### 2.2 Free-text judge path
- [ ] Owner: Bjorn. Due: Sat 7 Nov.
- Steps:
  - [ ] Implement the free-text detector (rule OPEN, per 2.0).
  - [ ] Write a judge prompt that checks the answer against the tool outputs only. The judge never sees gold.
  - [ ] Log `b1_path = deterministic | judge` for every task.
- Acceptance criteria: the share of tasks routed to the judge is reported per capability, and the judge's model and prompt hash are in `config.json`.
- Report back: the share of judge-path tasks per capability, plus the judge model and prompt hash.

### 2.3 Seeded-error test and false-alarm measurement
- [ ] Owner: Thomas (seeded cases, expected verdicts); Bjorn (runs). Due: Wed 11 Nov.
- Inputs: Timeline W5 seeded cases (wrong store, SKU, unit count, date range, missing day, unsupported weather claim); B0 predictions with gold scores.
- Steps:
  - [ ] Build seeded incorrect answers with expected verdicts. Count them and report the count; the target count is OPEN.
  - [ ] Run B1 on the B0 trajectories offline (no new agent calls), then build a 2×2 table: B1 verdict (accept/reject) × evaluator gold (correct/wrong).
  - [ ] Report:
    - **False-alarm rate**: rejected among gold-correct.
    - **Catch rate**: rejected among gold-wrong, split by headline label.
    - Insufficient-evidence rate.
    - All of the above separately for the deterministic and judge paths.
- Acceptance criteria:
  - The detection rate on seeded errors is reported.
  - The false-alarm rate is reported with n.
  - No threshold is tuned on the frozen evaluation set (tune on development domains only; Timeline risk register).
- Report back: the 2×2 tables per capability and per path, the seeded-error detection rate, and the path to the results.

### 2.4 B1 integrated in the agent loop
- [ ] Owner: Bjorn. Due: Wed 11 Nov.
- Define what B1 does on a reject, since B1 has no retry: return the B0 answer with a flag, abstain, or return "insufficient evidence". The choice is OPEN and determines how B1 is scored by the VAKRA evaluator. Decide it before running.
- Acceptance criteria: B1 runs on the identical task IDs from WS1.3, and the cost and latency of the check are logged separately.
- Report back: B1 versus B0 per-capability accuracy on identical tasks, plus the added latency and tokens.

---

## WS3. B2 one bounded recovery step (due Wed 18 Nov)

### 3.1 Recovery design
- [ ] Owner: Bjorn. Due: Sat 14 Nov.
- Steps:
  - [ ] After a B1 reject, give the agent structured feedback: which value failed, and which tool outputs were checked.
  - [ ] Allow exactly one targeted correction. Caps on extra tool calls, tokens and seconds are OPEN; set them before running and record them in `config.json`.
  - [ ] Re-check the corrected answer with B1. If it is still rejected, abstain or return the flagged answer, using the same policy as WS2.4.
- Confounds to control, so the B1→B2 difference measures recovery alone:
  - [ ] Same model, temperature, tool list and max steps as B0 and B1.
  - [ ] B2 only acts on tasks that B1 rejected. Report B2's effect on that subset and overall.
  - [ ] Extra compute is itself a treatment. Report B2 tokens and latency, and compare with a B0 that is simply given the same extra step budget if time allows (Stretch).
  - [ ] With temperature 0.0, nondeterminism in vLLM can still change outputs. Rerun a small B0 subset twice to measure run-to-run flip rate (size OPEN), so B2 gains can be compared with noise.
- Acceptance criteria (Timeline W6):
  - B2 corrects a seeded argument error.
  - B2 abstains on insufficient data.
  - B2 never exceeds its caps (verified from logs).
- Report back: recovered / still wrong / newly broken counts, cap hits, the B0 run-to-run flip rate, and added cost.

---

## WS4. Observability (Arize Phoenix) and analysis pipeline

### 4.1 Phoenix tracing on `capstone/observability`
- [ ] Owner: Grok Bot (building now). Due: Sun 1 Nov, so the N=10 B0 run is traced.
- Inputs: branch `capstone/observability` (worktree `/tmp/vk-obs`, head b26fb7c, clean as of 7:10 PM MT); `benchmark_runner.py`; the litellm provider.
- Steps:
  - [ ] Add OpenInference/OTel instrumentation for LLM calls and MCP tool calls, with spans for each agent step, the B1 check and the B2 recovery.
  - [ ] Attach attributes: task uuid, capability, domain, system (B0/B1/B2), run_id, tokens, latency.
  - [ ] Choose where Phoenix runs (local on the box, on the droplet, or hosted). The choice is OPEN. It must not send benchmark data anywhere Bjorn has not approved.
  - [ ] Add a flag that turns tracing off, so traced and untraced runs give identical predictions.
- Acceptance criteria:
  - A 5-task smoke run shows complete traces.
  - Predictions with tracing on and off are identical on those tasks.
  - The overhead is measured.
- Report back: the commit SHA, a screenshot path, the overhead, and anything that needed Bjorn's approval.

### 4.2 Metrics script, verifier evaluation and shortlist recall
- [ ] Owner: Grok Bot. Due: Wed 4 Nov (`metrics.py`, `shortlist_recall.py`); Wed 11 Nov (`verifier_eval.py`).
- Rationale and metric definitions (M1–M17): `/workspace/berkeley/plans/metrics-variables-research.md` §3.
- Inputs: `<RUN>/eval/cap*.json` (including the evaluator's sieve-stage fields), prediction files, `config.json`, vLLM usage fields, Phoenix exports, B1 verdicts (WS2), gold tool sets in `data/train/<cap dir>/output/<domain>.json`.
- Steps:
  - [ ] Write `capstone/analysis/metrics.py`. It produces a table per system and capability with these columns:
    - [ ] n, and accuracy as sum of dialogue scores / n (the `summarize.py` definition; note partial credit).
    - [ ] Fixed / broken / unchanged transition counts for each system pair (M2).
    - [ ] Sieve-stage pass rates: Tool / ArgN / ArgV / Gnd (M8).
    - [ ] Step-cap hit, timeout and exception rates (M11).
    - [ ] Prompt, completion and reasoning tokens per task (M12).
    - [ ] Mean and median latency per task, and GPU-seconds per task (M13).
    - [ ] $ per task and $ per correct answer at $2.59/GPU-h (M14). Label every $ figure as an ASSUMPTION until WS10.2 records measured timing.
    - [ ] pass^k for k = 1–3 with the unbiased estimator, once repeats exist (M10).
  - [ ] Write `capstone/analysis/verifier_eval.py`:
    - [ ] B1 precision, recall and false-alarm rate against gold, split into the deterministic and judge paths (M3).
    - [ ] A precision-recall curve over strictness settings (V3; feeds WS5.4).
  - [ ] Write `capstone/analysis/shortlist_recall.py`: recall@k of gold tools under the existing all-MiniLM-L6-v2 shortlister for k ∈ {16, 32, 64, 128}. CPU only (M15; feeds WS5.3).
  - [ ] Output CSV and Markdown. Stdlib or pandas, pinned.
- Acceptance criteria:
  - On the 29 Oct run, n and accuracy match `summarize.py` exactly.
  - Every column is filled, or marked "n/a" with the reason (for example, no repeats yet).
  - `verifier_eval.py` reproduces a hand-computed 2×2 table.
  - `shortlist_recall.py` runs without a GPU.
- Report back: the tables, recall@k per capability, the B1 precision/recall/false-alarm rates per path, and the paths.

### 4.3 Paired statistics
- [ ] Owner: Grok Bot (code); Thomas (review). Due: Wed 18 Nov (tested on B0/B1 by 11 Nov).
- Rationale: `metrics-variables-research.md` §5.
- Steps:
  - [ ] **Primary family**, fixed before 25 Nov:
    - P1: B2 vs B0 accuracy on the frozen set.
    - P2: B2 vs the random-trigger control (WS8.2).
    - Apply Holm across P1–P2.
    - B1 detection quality (M3) is reported as an estimate with a CI, not as a test.
    - All per-capability tests, and B1 vs B0 and B2 vs B1, are exploratory and labeled as such, with unadjusted CIs.
  - [ ] **Binarization** (proposed; confirm in the decisions list):
    - Correct if the task score equals 1.0.
    - Sensitivity check: the mean partial score with a paired bootstrap.
  - [ ] **Exact McNemar** on per-task outcomes (`statsmodels` `mcnemar(table, exact=True)`). With repeats, aggregate to one outcome per task (majority, or mean with a paired bootstrap). Never pool 3n as independent.
  - [ ] **Paired bootstrap CI** (10,000 resamples, fixed seed), clustered by domain. Report task-level resampling as a sensitivity check. If they differ a lot, use the clustered interval.
  - [ ] **Noise floor**: report B0 vs B0′ discordance per capability (from WS5.0) next to every paired result. A B2 effect whose discordance is not clearly above this floor is not established.
  - [ ] **MDE table**: fill in the §5 table of the research file using the observed discordant share d and the domain-clustering design effect from B0. Report it in the paper as a limitation. The table currently comes from `research-src/budget_calc.py`.
- Acceptance criteria:
  - Unit tests on synthetic data with known effects.
  - The script reproduces a hand-computed exact McNemar on a 2×2 example.
  - The primary family and binarization rule are written into the WS8.1 freeze manifest.
- Report back: the method summary, test results, the noise floor per capability, and the filled MDE table.

### 4.4 Inter-rater agreement and evaluator-judge audit
- [ ] Owner: Grok Bot (scripts); Bjorn and Thomas (labels); Thomas (audit lead). Due: Wed 4 Nov (agreement script); Wed 9 Dec (judge audit on frozen results).
- Steps:
  - [ ] Write `capstone/analysis/agreement.py`: Cohen's kappa with a bootstrap CI for the headline and sub-reason labels, plus a confusion matrix.
  - [ ] **Evaluator-judge audit** (new; M17, `metrics-variables-research.md` §3):
    - [ ] Draw a stratified sample of about 100 tasks: about 50 the judge scored correct and 50 it scored wrong, balanced across B0 and B2. Record the seed.
    - [ ] Have humans label correctness against the question, the database and the gold, without seeing which system produced the answer.
    - [ ] Report the judge error rate per system with a CI. This tests whether a same-model judge favors one system.
- Acceptance criteria:
  - Kappa and n are reported. If headline kappa is below a threshold (OPEN, for example 0.6), revise the guide and relabel before 25 Nov.
  - Judge error rates are reported per system with n.
- Report back: kappa, CI, n, the most frequent disagreements, and the judge error rate per system.

### 4.5 Reference-wrong exclusion list
- [ ] Owner: Thomas. Due: Wed 25 Nov (frozen with the eval set).
- Inputs: WS7 evidence records.
- Steps:
  - [ ] Write `capstone/analysis/reference_wrong.csv` with columns: task uuid, domain, evidence ID, reproducible query path, date added, and who confirmed it.
  - [ ] Every metric in WS4.2 and WS4.3 is reported twice: on all tasks, and with the listed tasks excluded.
- Acceptance criteria:
  - The list is frozen by 25 Nov and not edited after results are seen.
  - Any later addition is reported in a separate sensitivity table.
- Report back: the count per domain and the frozen file hash.

---

## WS5. Tuning and ablations (B0 configuration; development domains only)

Rationale, hypotheses and the variables considered: `/workspace/berkeley/plans/metrics-variables-research.md` §4 (V1–V17) and §6.

Budget and time constraints:
- About 190 GPU-hours at list price on the original $500. On the $483 figure, that is about 186.5 GPU-hours (483 / 2.59). The actual remaining balance is OPEN.
- **All GPU-hour and $ figures in WS5 are ASSUMPTIONS** (central scenario of 10 effective GPU-seconds per task; research file §6). No per-task timing has been measured yet. Replace them after WS10.2.
- Tune only on held-out development domains, never on the frozen evaluation set. Which domains go into development versus evaluation is set in WS8.1.
- The sweeps use a 400-task dev subset drawn from the B0 N=10 run (an ASSUMPTION; its size depends on the WS8.1 split).
- At n = 400 the minimum detectable effect is about 4–6 pp (research file §5). Treat sweep outcomes as selection heuristics, not findings.

### 5.0 Noise floor (new; run before 5.1)
- [ ] Owner: Bjorn. Due: Sat 21 Nov, and before 5.1–5.3 start.
- Inputs: the 400-task dev subset (task IDs saved from WS1.3), and the same `config.json` settings as B0.
- Steps:
  - [ ] Run 2 extra B0 repeats on the dev subset at temperature 0, without changing anything else.
  - [ ] Compute the per-task flip rate per capability (M9) with `metrics.py`.
- Hypothesis: the flip rate is non-zero at temperature 0, because vLLM inference is not deterministic (research file §2, V1).
- Metric: the flip rate per capability. It feeds WS4.3 as the noise floor.
- Cost: about 2.2 GPU-h (ASSUMPTION, central).
- Acceptance criteria: the flip rate per capability is reported with n, and all three runs share an identical `config.json` apart from run_id.
- Report back: the flip rate per capability, GPU-hours used, and the paths.

### 5.1 Reasoning effort (gpt-oss low / medium / high)
- [ ] Owner: Bjorn. Due: Sat 21 Nov.
- Inputs: the dev subset; medium is reused from B0 (if B0 ran at medium; the current setting is OPEN, so check `config.json`).
- Steps:
  - [ ] Run low and high effort on the 400-task dev subset.
- Hypothesis (two-sided): static benchmarks improve with effort [vLLM-recipe], but agent harnesses often get worse [HAL]. Expect tokens and latency to rise with high effort, with no monotone accuracy gain.
- Metrics: accuracy per capability, reasoning tokens per task, latency, and the "wrong reasoning" share.
- Cost: about 2.9 GPU-h (ASSUMPTION, central).

### 5.2 Max agent steps
- [ ] Owner: Bjorn. Due: Sat 21 Nov.
- Inputs: B0 traces from WS1.3. The current `max_iterations` default for capabilities 2–4 is OPEN; it is the provider or LangGraph default, so read it from `config.json` or the installed LangGraph version.
- Steps:
  - [ ] Simulate lower caps offline from the B0 traces. A trajectory that finished in ≤ c steps is unchanged under cap c, apart from nondeterminism.
  - [ ] Re-run only the tasks that hit the cap, at a higher cap.
- Hypothesis: too few steps leave multi-hop tasks unfinished; beyond a point, more steps add cost without accuracy.
- Metrics: accuracy versus step cap, step-cap hit rate (M11), and tokens.
- Cost: about 0.5 GPU-h (ASSUMPTION, central).

### 5.3 Tool-list size (shortlister top-k)
- [ ] Owner: Bjorn. Due: Sat 21 Nov.
- Inputs: the existing shortlister flag `--top-k-tools` (default 128), and recall@k from WS4.2 `shortlist_recall.py`.
- Steps:
  - [ ] Check recall@k offline first, and drop any k where gold-tool recall is too low. The cut-off is OPEN; set it before running.
  - [ ] Run `--top-k-tools` ∈ {32, 64, 128} on dev capabilities 2–4 (128 is reused from B0).
  - [ ] The earlier "gold tools plus k distractors" design is dropped, because it leaks gold tool identity. Use it, if at all, only as a labeled diagnostic.
- Hypothesis: a smaller k cuts "wrong tool" errors and tokens [RAG-MCP] until recall@k drops.
- Metrics: "wrong tool" rate, accuracy per capability, tokens per task, and recall@k (M15).
- Cost: about 1.7 GPU-h (ASSUMPTION, central).

### 5.4 B1 strictness (new; offline)
- [ ] Owner: Bjorn (choice); Grok Bot (curves). Due: Wed 11 Nov.
- Inputs: B0 dev traces, B1 replay (WS2), `verifier_eval.py` (WS4.2).
- Steps:
  - [ ] Write down the false-alarm ceiling before seeing any results.
  - [ ] Plot the precision-recall curve over strictness settings: numeric tolerance, unit and date normalization, ID match, and judge threshold (V3).
  - [ ] Choose the strictest setting that stays under the ceiling.
- Hypothesis: some strictness level reaches recall ≥ ~0.8 at a false-alarm rate that leaves B2 net-positive.
- Metrics: B1 precision, recall and false-alarm rate, per path (M3).
- Cost: about 0 GPU-h (offline replay; judge calls are counted in B1 development).

For each sweep (5.1–5.4):
- [ ] Choose the B0 setting (or B1 strictness) for the frozen experiments before 25 Nov, and record it in the WS8.1 freeze manifest.
- Acceptance criteria: the table, CIs and the chosen setting are saved under `capstone/results/ablations/`; dev numbers are labeled exploratory.
- Report back: the table, the decision, and GPU-hours used against the assumed figure.

### Stretch (out of scope unless time allows)
Reasons are in `metrics-variables-research.md` §4. GPU-hour figures are ASSUMPTIONS (central).

If time allows:
- Located vs generic recovery feedback (V7), frozen ×1, about 1.2 GPU-h.
- A second recovery step (V8), about 0.6 GPU-h.
- gpt-oss-20b as B0/B1/B2 (V9), frozen ×1, about 4.0 GPU-h plus a model reload.
- One system-prompt paraphrase on dev (V11), about 1.1 GPU-h.

Skip (record as fixed settings and limitations):
- Temperature > 0 (V12): adds variance without informing the thesis.
- Tool-description edits (V13): these change the benchmark.
- Serving parameters (V15): they affect throughput and nondeterminism, not the thesis; hold them fixed and record them in the manifest.
- DeepSeek or other model families (V16): different hardware fit, an extra confound, and outside the budget.
- Context length (V14): skip, but monitor overflow and truncation counts (M11).

---

## WS6. RCA track on sales_in_weather

### 6.1 Analytical tools
- [ ] Owner: Thomas (lead); Bjorn (second). Due: 28 Oct per Timeline v1.2. Its status is OPEN; P2 slide 18 lists it as remaining.
- Inputs: `sales_in_weather.sqlite` (read-only; path under `vakra/data/databases/`, exact path OPEN); Timeline W3: `sum_units`, `compare_periods` (two adjacent 28-day windows), `item_contribution`, `weather_coverage`, `data_quality`.
- Acceptance criteria (Timeline W3):
  - Item deltas reconcile exactly to the store delta.
  - Zero-baseline, sparse-window and duplicate-row tests pass.
  - The source database is unchanged (hash before and after).
- Report back: the test output, the hashes, and the branch and commit.

### 6.2 RCA results on the 70 tasks
- [ ] Owner: Thomas. Due: Wed 2 Dec (with the paired experiments).
- Steps:
  - [ ] Report B0/B1/B2 results on the 54 cap-2 and 16 cap-4 sales_in_weather tasks.
  - [ ] Report results both with and without the WS7 reference-wrong tasks (8 of 54 per the 27 Oct audit).
  - [ ] Every RCA answer names each factor and its source. Make no causal claims from coincidence (Timeline W2 exit criterion).
  - [ ] Claims are descriptive, with clustered uncertainty (P2 slide 18).
- Scope question, OPEN: Timeline v1.2 W7 plans ~100 generated RCA incident cases from ~15–25 templates. The P2 deck describes RCA only on the 70 VAKRA tasks. Whether the incident generator is still in scope is a decision (see the end of this plan).
- Report back: the per-system table on the 70 tasks (both versions) and the label distribution.

### 6.3 Home Depot Q1 2026 example (paper framing)
- [ ] Owner: Capstone bot. Due: Wed 9 Dec.
- Inputs: `capstone-examples/shortlist.md`, `candidates.md` C37; SEC Exhibit 99.1 and the 19 May 2026 call transcript (URLs in `notes_final.json` slide 17).
- Steps:
  - [ ] Reopen both sources and confirm these figures verbatim before reuse: +0.6% comp sales, about +55 bp currency (release), 56 bp storms (call), transactions −1.3%, ticket +2.2%, and the CFO quote.
  - [ ] Label them as management statements, not causal estimates.
- Report back: the confirmed figures with URLs and fetch date, or any discrepancy.

---

## WS7. Answer-key audit

Evidence standard. A "reference wrong" claim requires all of the following:
- A saved, read-only query script that reproduces the gold answer.
- A query that produces the corrected answer under a stated reading of the question.
- A one-line statement of the reading.
- Confirmation by a second person.

Without these, the task stays scored as-is.

### 7.1 Re-verify the sales_in_weather finding
- [ ] Owner: Thomas. Due: Sat 7 Nov.
- Inputs: `capstone-examples/c40-audit.py`, `c43-bird-compare.py`, `c44-official-check.py`, `bird-official-train.json`, `bird-mirror-sales_in_weather.json`.
- Steps:
  - [ ] Rerun the three scripts and confirm the 27 Oct results:
    - 214 vs 24 units
    - 54/54 BIRD questions word for word
    - 28 undated joins, of which 27/28 reproduce and 1 timed out
    - 8/54 disagree on a date-matched reading
  - [ ] Also note the research-log pass 7 counts (18 of 76 endpoints; 3 impossible). Reconcile them with the 8/54 figure in writing.
- Acceptance criteria: the outputs match, or differences are explained.
- Report back: the script outputs and the reconciliation note.

### 7.2 Extend to other domains
- [ ] Owner: Thomas (lead); Grok Bot (script support). Due: Wed 25 Nov.
- Steps:
  - [ ] Screen every domain in the frozen eval set for the same pattern: joins on tables with dates but no date key, answers impossible given database totals, and dates outside database coverage (as in research-log C40 "16 September 2022").
  - [ ] Prioritize domains where the BIRD gold SQL can be matched (VAKRA README: databases come from BIRD train and dev).
  - [ ] Log candidates in `capstone/analysis/audit_log.md`. Promote one to WS4.5 only when it meets the evidence standard.
- Acceptance criteria: each audited domain is listed with the number of tasks screened and the number flagged; there are no unverified flags in WS4.5.
- Report back: domains screened, flags, confirmed count, and paths.

### 7.3 Reporting the finding upstream
- [ ] Owner: Bjorn (decision). No bot action.
- An issue on IBM/vakra or a note to BIRD maintainers needs Bjorn's explicit approval. The research log recommends raising it at the IBM meeting, framed as an upstream BIRD issue.
- Capstone bot may draft text for approval only.
- Report back: the draft text, if requested.

---

## WS8. Evaluation-set freeze (Wed 25 Nov) and paired experiments (Wed 2 Dec)

### 8.1 Freeze
- [ ] Owner: Thomas (lead); Bjorn (second). Due: Wed 25 Nov.
- Steps:
  - [ ] Split the domains into development (used for WS2–WS5 tuning) and evaluation (untouched until 2 Dec), stratified by capability. This answers the P2 contamination and over-tuning critique. The rule is OPEN; the P2 notes commit to "hold out domains during development". The split fixes the frozen-set size F (about 2,200 tasks is an ASSUMPTION in the research file §6).
  - [ ] Write `capstone/eval/frozen_tasks.json`: task uuids, plus a hash of the gold files, `reference_wrong.csv` (WS4.5), the labeling guide (WS1.4), and the system configs (B0 settings from WS5, B1 policy, B2 caps).
  - [ ] Write the freeze manifest `capstone/eval/freeze_manifest.json` (rationale: `metrics-variables-research.md` §5). It records:
    - [ ] the binarization rule (proposed: score == 1.0);
    - [ ] the primary family (P1 B2 vs B0, P2 B2 vs random-trigger control) and Holm;
    - [ ] the B1 strictness setting (WS5.4);
    - [ ] the B2 trigger rate observed on dev;
    - [ ] the random seed for the random-trigger control.
  - [ ] Tag the commit `eval-freeze-2026-11-25` locally. Pushing the tag needs Bjorn's approval.
  - [ ] Write a contamination note for the paper. VAKRA train is public and its questions come from BIRD, which may be in gpt-oss-120b's pretraining data; whether it is, is unknown. Absolute accuracy is therefore internal. Paired differences are on identical tasks with the same model. The gated test split is used only if access is granted (IBM/vakra#36).
  - [ ] Write a judge note: the VAKRA evaluator's judge may be gpt-oss-120b (WS-wide facts). Report the judge model used. If it is the agent's model, rely on the WS4.4 human audit; rescore a sample with a different judge only if Bjorn approves the cost.
- Acceptance criteria: the hashes and the manifest are recorded, and no rubric, list or manifest changes after the freeze (Timeline W8: "no post-hoc rubric changes").
- Report back: the task count per capability, the hashes, the manifest contents, and the tag SHA.

### 8.2 Paired experiments
- [ ] Owner: Bjorn (lead); Thomas (second). Due: Wed 2 Dec.
- Design rationale: branch the systems instead of re-running them (`metrics-variables-research.md` §0 item 1). This requires B1 to be a post-answer check; see the decisions list. If B1 changes the trajectory before the final answer, B1 must be run, not replayed, and the GPU-hour figures change.
- Steps (repeat 3 times on `frozen_tasks.json`):
  - [ ] Run B0 once, with the same model, tools and settings. Use checkpoints and resume.
  - [ ] Compute B1 by replaying its checks on the saved B0 trajectories.
  - [ ] Run B2 by resuming only the B1-flagged trajectories for one recovery step.
  - [ ] Run the **random-trigger control** (P2): apply the same recovery step to a random set of tasks, with the same count as B1 flagged in that repeat. Use the seed from the freeze manifest.
  - [ ] Keep a missing-run ledger.
  - [ ] Snapshot and destroy the droplet after each session (WS10.1).
- Cost: about 23.8 GPU-h for B0/B1/B2 ×3 plus about 3.7 GPU-h for the control ×3 (ASSUMPTIONS, central; research file §6).
- Acceptance criteria:
  - Machine-readable results for B0, B1, B2 and the control on identical task IDs in each of the 3 repeats.
  - Any missing or budget-truncated runs are labeled.
  - If repeats are cut to 2 under the WS10.3 rule, this is stated.
- Report back: completion counts per system and repeat, the B1 flag count per repeat, the missing ledger, GPU-hours, and paths.

### 8.3 Analysis
- [ ] Owner: Thomas (lead); Grok Bot (scripts). Due: Wed 9 Dec.
- Steps:
  - [ ] Run WS4.2–4.5 on the frozen results.
  - [ ] Produce:
    - [ ] the error taxonomy for all systems;
    - [ ] fixed/broken counts (M2);
    - [ ] recovery fix and break rates for the verifier trigger vs the random trigger (M7);
    - [ ] pass^1–3 (M10);
    - [ ] the false-alarm table;
    - [ ] the cost-accuracy Pareto plot (M14);
    - [ ] the judge-audit error rates per system (WS4.4);
    - [ ] 3–5 representative traces (Phoenix).
- Acceptance criteria: every figure regenerates from saved outputs with one command (Timeline W9).
- Report back: the tables, figures, and the regeneration command.

---

## WS9. Final paper, talk and package (Tue 15 Dec)

### 9.1 Paper
- [ ] Owner: Thomas (lead); Bjorn (second); Capstone bot (drafting, source checks). Draft due Wed 9 Dec; final due 15 Dec.
- Contents: problem, related work, VAKRA, method (B0/B1/B2), the taxonomy, results with CIs and the with/without reference-wrong tables, the RCA track, limitations (see below), ethics, and reproducibility.
- The four locked examples. Each must be reopened and its quote or figure re-verified before the final; source URLs are in `notes_final.json`.
  - [ ] Moffatt v. Air Canada, 2024 BCCRT 149, paras. 22, 27, 28 ($812.02; small-claims decision, not precedent).
  - [ ] Answer key: 214 vs 24 units, inherited from BIRD (WS7.1).
  - [ ] Home Depot Q1 2026 (WS6.3).
  - [ ] Ask Augustana, The Augustana Mirror, 25 Sep 2026 (student newspaper).
- Limitations section must cover the P2 review risks:
  - Train-only evaluation and possible contamination.
  - The same-model evaluator judge.
  - The B1 judge path on free text.
  - "Reference wrong" as a possibly self-serving label, handled by the evidence standard, the second confirmation, and reporting with and without.
  - Power (the minimum detectable difference from WS4.3).
  - Inter-rater agreement (WS1.4).
  - vLLM nondeterminism (WS3).
  - Benchmark-only claims (Upadhyay privacy and impact assessment).
- Acceptance criteria: every number links to an artifact path, and every quote to a source and paragraph or page.
- Report back: the draft link or path, and a list of unverified claims.

### 9.2 Final talk
- [ ] Owner: Bjorn and Thomas; Capstone bot (deck draft, notes timed at about 150 words per minute). Due: 15 Dec. The final talk length is OPEN; P2 was 13 minutes.
- Acceptance criteria: the scripts fit the slot at 150 wpm, and each slide has a source footer.
- Report back: the word count per slide and the total time.

### 9.3 Reproducibility package and demo notebook
- [ ] Owner: Bjorn (lead); Grok Bot (support). Due: 15 Dec.
- Steps:
  - [ ] Pin dependencies (including `mcp` and `fastmcp`) and the model ID.
  - [ ] Write a setup guide: droplet, vLLM, data download, and `data/test -> train` link.
  - [ ] Provide one command to run each system.
  - [ ] Write the notebook: question → tool calls → provenance → verification → output (Timeline W9).
  - [ ] Tag a clean revision and run the tests plus a small end-to-end run (Timeline W10).
- Acceptance criteria: a fresh clone reproduces the results tables from the saved outputs.
- Report back: the tag, test output, and notebook path.

### 9.4 IBM gated test split and leaderboard (approval-gated)
- [ ] Owner: Bjorn only. No bot posts, comments, submits or contacts IBM.
- Status: gated test access was requested 15 Oct via IBM/vakra#36, and is pending as of 29 Oct (P2 slide 9). The IBM meeting has not been held (P2 slide 7).
- If access is granted and Bjorn approves:
  - [ ] Run on test.
  - [ ] Run `validate_output.py`.
  - [ ] Zip the outputs and config, and attach them to a fork release.
  - [ ] File the `leaderboard_submission` issue (capstone-plan.md, "Eval and submission procedure").
- Bots may prepare the ZIP and draft the issue text locally for Bjorn's review.
- Report back: the draft only.

---

## WS10. Compute, cost and risk

### 10.1 Droplet discipline
- [ ] Owner: Bjorn. Applies to every session.
- Rules:
  - Snapshot before destroying. Destroy after every session, since billing continues while a droplet is powered off (runbook).
  - Record start and end times and droplet hours in the run's `config.json`.
  - Bots never operate the droplet unless asked.
- Snapshot storage cost and restore time are OPEN; measure them at the first snapshot.

### 10.2 Budget ledger
- [ ] Owner: Bjorn (numbers); Grok Bot (ledger file `capstone/results/compute_ledger.csv`). Update after every run.
- Known: list price $2.59 per GPU-hour (runbook, DigitalOcean list price; billed per second with a 5-minute minimum, and powered-off droplets are still billed, per research file §6). Credit is $483 per the parent brief (versus $500 in the runbook). Expiry is 14 Dec per the parent brief (versus 15 Dec in the runbook). The actual balance and expiry are OPEN until Bjorn confirms them from the AMD/DigitalOcean billing page.
- Steps:
  - [ ] After the 29 Oct run is scored (WS1.1), record measured effective seconds per task, tokens per task and concurrency.
  - [ ] Recompute the §6 table of `metrics-variables-research.md` with `research-src/budget_calc.py`, and replace every ASSUMPTION value in this plan.
- Projected need. **These are ASSUMPTIONS** (central scenario, 10 effective GPU-seconds per task, research file §6), not measurements:
  - core ≈ 59 GPU-h (~$152);
  - core + if-time ≈ 68 GPU-h (~$175);
  - with the conditional gated-test run ≈ 91 GPU-h (~$235);
  - pessimistic all-tiers ≈ 140 GPU-h (~$362).
  - Spend before 29 Oct is not counted.
- Fallback: a hosted API, estimated at $8–20 per full run (P2 slide 14). It needs Bjorn's approval to spend.
- Acceptance criteria: the ledger shows measured sec/task, and no plan figure is still labeled ASSUMPTION after 4 Nov.
- Report back: hours used, balance, measured sec/task, and the recomputed projection to 2 Dec.

### 10.3 Risk register

| Risk | Trigger | Response | Owner |
|---|---|---|---|
| Credit exhausted before 2 Dec | Projected hours exceed the balance | Cut ablation N and breadth first, never the paired comparison (Timeline risk register); API fallback with approval | Bjorn |
| Per-task cost far above assumption | Measured effective sec/task > 30 s | Cut frozen repeats from 3 to 2, then drop if-time items. Never drop the random-trigger control or B0/B2 pairing (research file §6) | Bjorn |
| Credit expiry (14 or 15 Dec) | Any run after 9 Dec | All GPU runs done by 2 Dec; reruns by 9 Dec | Bjorn |
| Droplet or scratch disk lost | Destroy without snapshot; provider failure | Snapshot rule; `setup.sh` rebuild; copy results off the droplet after each run (location OPEN) | Bjorn |
| Scoring breakage (as on 29 Oct) | Evaluator error after a dependency change | Pinned lock file (WS1.1); score immediately after each run; keep raw predictions | Bjorn / Grok Bot |
| Same-model judge in the VAKRA evaluator | The evaluator judge is the same model as the agent | M17 human audit of judge error per system (WS4.4); rescore a sample with another judge only if Bjorn approves the cost (WS8.1) | Thomas |
| B1 "grading its own homework" critique | Questions in Q&A or review | Deterministic value path; judge path reported separately (WS2) | Bjorn |
| Train-split contamination critique | Reviewer question | Paired differences only; domain holdout; test split if granted; limitation in paper (WS8.1) | Thomas |
| "Reference wrong" seen as self-serving | Reviewer question | Evidence standard, second confirmation, frozen list, with/without reporting (WS7, WS4.5) | Thomas |
| Label reliability | Kappa below threshold | Revise guide; relabel; report kappa (WS1.4, WS4.4) | Thomas |
| Underpowered comparison | Few discordant pairs | Report the MDE table, noise floor and CIs; avoid claims of "no effect" (WS4.3) | Thomas |
| Schedule slip | A milestone more than 2 days late | Drop Stretch items, then reduce ablations; keep B0/B1/B2 paired on the frozen set | Both |
| Phoenix tracing changes behavior | Traced and untraced predictions differ | Tracing off for scored runs (WS4.1) | Grok Bot |
| No gated test access by 2 Dec | #36 still pending | Train-only results, labeled internal; no leaderboard claim | Bjorn |

---

## Milestone summary

| Date | Milestone | Items |
|---|---|---|
| Sat 31 Oct | Scoring fixed; 29 Oct run scored | 1.1, 1.2 |
| Sun 1 Nov | Phoenix tracing ready | 4.1 |
| Tue 3 – Wed 4 Nov | B0 N=10 run scored; taxonomy and first labels; metrics and agreement scripts | 1.3, 1.4, 4.2, 4.4 |
| Wed 11 Nov | B1 verifier, seeded errors, false alarms | 2.1–2.4 |
| Wed 18 Nov | B2 recovery; paired statistics code | 3.1, 4.3 |
| Sat 21 Nov | Ablations decided | 5.1–5.3 |
| Wed 25 Nov | Eval set, exclusion list and audit frozen | 8.1, 4.5, 7.2 |
| Wed 2 Dec | Paired experiments; RCA results | 8.2, 6.2 |
| Wed 9 Dec | Analysis, demo, paper draft | 8.3, 9.1 |
| Tue 15 Dec | Final submission | 9.1–9.3 |

---

## Decisions only Bjorn or Thomas can make

1. Confirm the next B0 run at **N=10 per domain** (about 1,370 tasks, fewer where a domain has fewer than 10). This default was not explicitly confirmed. (Bjorn)
2. Which judge model scores runs in the VAKRA evaluator, and whether to rescore a sample with a different judge. (Bjorn)
3. B1 open details: the judge model for free-text answers, how free text is detected, whether simple derivations are recomputed or rejected, and what B1 returns on reject. (Bjorn)
4. B2 caps on calls, tokens and seconds. (Bjorn)
5. The development/evaluation domain split rule, and therefore the frozen-set size. Must be fixed before 25 Nov. (Thomas, with Bjorn)
6. Labeling: the size of the double-labeled sample, the kappa threshold, and the spot-check fraction. (Thomas)
7. Whether the Timeline v1.2 RCA incident generator (~100 cases) is still in scope or replaced by the 70 VAKRA tasks. (Thomas)
8. Where Phoenix runs, and whether any trace data may leave the box or droplet. (Bjorn)
9. Whether and when to raise the BIRD/VAKRA answer-key issue with IBM; any leaderboard submission. (Bjorn)
10. Confirm the remaining credit ($483 or $500) and the expiry date (14 or 15 Dec) from the billing page. (Bjorn)
11. Whether B1 is purely a post-answer check, or changes the agent's path before the final answer. Offline replay (WS8.2) is exact only in the first case; in the second case B1 must be run, which raises GPU cost. (Bjorn)
12. Whether B1 and/or B2 may abstain. If yes, add abstention rate and selective accuracy at matched coverage (M16) as core metrics. (Bjorn)
13. Adopt the random-trigger control for B2 as the second primary comparison (P2), with its trigger count matched to B1's flags and a fixed seed recorded at freeze. (Bjorn and Thomas)
14. Adopt the statistical plan: primary family P1/P2 with Holm, binarization at score == 1.0 with mean-score sensitivity, and 3 frozen repeats (cut to 2 only under the WS10.3 rule). (Thomas, with Bjorn)
15. The B1 false-alarm ceiling for WS5.4 and the shortlist recall@k cut-off for WS5.3, both set before results are seen. (Bjorn)
