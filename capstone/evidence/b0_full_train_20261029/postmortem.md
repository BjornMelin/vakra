# B0 full train run: postmortem

Run: `b0_full_train_20261029`. Agent: plain ReAct (B0). Model: gpt-oss-120b on vLLM 0.27.1, one AMD MI300X droplet (vakra-b0-oct29). Split: train, 4,428 tasks across 4 capabilities. All times are Mountain Time (UTC−6).

Status: final. All 4,428 tasks have a prediction and a score.

Paths such as `analysis/` and `logs/` are relative to the run directory. The run artifacts are not in the repository; copies are on the operator box under `/workspace/berkeley/runs/b0_full_train_20261029/` and `/workspace/berkeley/runs/b1_replay_b0full_20261030/`.

## Timeline

| Time (MT) | Event |
|---|---|
| Oct 29 18:10 | Droplet up. vLLM serving gpt-oss-120b (max-model-len 65536, max-num-seqs 64). |
| Oct 29 19:27–22:21 | Fixes for MCP 2.x, content blocks, cap1 universe IDs, eval queue and merge (commits a9e6730 … 4e48658). |
| Oct 29 22:21:56 | Full run started: 48 agents in parallel, 8 shards. |
| Oct 29 22:23 | First cap2 HTTP timeout, on bike_share_1 `date_highest_trips_avg_min_temp`. |
| Oct 29 22:46 | cap2 timeouts became sustained. Between 22:49 and 23:57, 17 cap2 domains returned 0 items after OpenAPI spec timeouts, and the runner still exited 0. |
| Oct 30 03:22 | cap2 REST server restarted. The 17 domains were rerun 6 at a time. |
| Oct 30 03:41 | Second wedge, during the eval with 16 parallel jobs. REST restarted at 04:22. mental_health_survey was rerun alone and finished at 04:42. |
| Oct 30 05:33–05:34 | The 23 timeout-hit cap2 domains were relaunched for a clean rerun, 6 at a time. The first attempt skipped every domain because the files had been copied instead of moved; fixed and relaunched at 05:34. |
| Oct 30 05:36 | Rescore finished with 0 missing scores (eval at 2 parallel jobs, with sequential retries for 5 domains). |
| Oct 30 06:18:45 | Third wedge, triggered by a sales_in_weather snowfall query. 6 running domains got errors, and 7 more returned 0 items. Pass 3 was started at 06:52. |
| Oct 30 07:18:54 | Fourth wedge: bike_share_1 sent the trips-by-temperature query 10 times. movie_platform and cars were contaminated, and beer_factory failed on spec timeouts. Pass 3 was stopped. |
| Oct 30 07:26 | Pass 4 started: the blocking domains run alone and last, with a health gate before every attempt. beer_factory (36/36) and cars (40/40) finished with 0 HTTP errors. |
| Oct 30 08:12 | movie_platform pass 4 attempt 1 stopped at 116/150 (see problem 5). Attempt 2 started. |
| Oct 30 08:46 | movie_platform attempt 2: 150/150, 0 HTTP errors. bike_share_1 started alone. |
| Oct 30 09:07 | bike_share_1: 37/37 predictions, 24 HTTP errors (slow endpoint, see caveats). REST restarted; sales_in_weather started alone at 09:08. |
| Oct 30 09:22 | B1 gold check attempt 1 (started 06:22) stopped: it could not finish one 853M-character cap2 gold answer. Fixed in 80fdb28 and rerun, 4 processes. |
| Oct 30 09:49 | B1 gold check with judge finished (28 min). |
| Oct 30 10:00 | cap4 gold check rerun with the abstention fix (21e0624) finished. |
| Oct 30 10:30–18:15 | Operator usage limit reached. The scripts already running finished on their own; nothing else was done, and the droplet sat idle after 13:15. |
| Oct 30 10:44 | sales_in_weather: 54/54 predictions, 162 HTTP errors. Pass 4 agents done. |
| Oct 30 10:44–13:08 | Pass 4 eval: 21 domains at 2 parallel jobs, then bike_share_1 and sales_in_weather alone with REST restarts. Merge and summarize reported `missing=0`. |
| Oct 30 13:09–13:14 | B1 collect for cap2 (all 40 domains, 4 shards, blocking domains alone). The automatic cap2 replay then failed (problem 7). |
| Oct 30 18:15 | Resumed. Found mental_health_survey unscored (0/27, problem 7). Re-evaluated it: 10/27. Final B0 score 2,299/4,428. |
| Oct 30 18:22 | B1 replay restarted for all capabilities on 21e0624 into a new directory. |
| Oct 30 18:41–18:44 | B1 replay finished (exit 0); B1 eval and summary finished. |
| Oct 30 18:55 | config.json finalized: 24.8 GPU hours from droplet start to this point. |

## Problems

### 1. cap2 REST server wedges (main issue)

**Diagnosis.** The cap2 M3 REST server is a single uvicorn worker. All 9,891 endpoints are `async def` but run blocking sqlite queries on a shared cursor. A slow query therefore blocks the event loop for every cap2 domain. Two endpoints take longer than the MCP client's 30 s timeout:
- `sales_in_weather/items_by_highest_snowfall_station`: over 120 s, measured.
- `bike_share_1/date_highest_trips_avg_min_temp`: a trip × weather join.

The agent retries timed-out calls, which queues more blocking queries. Higher concurrency makes this more likely. While the server is wedged:
- running domains get HTTP timeouts
- new domains fail the OpenAPI spec fetch and record 0 items

**Fix.** The benchmark server was left unmodified, because changing it would change the environment. Instead:
- Every rerun waits for `openapi.json` health and for 30 s of stable health before starting a domain.
- Each domain is checked for prediction count equal to ground-truth count and 0 HTTP errors, with up to 3 attempts.
- bike_share_1 and sales_in_weather run alone, after all other domains, with a REST restart after each.
- Every failed attempt is archived under `logs/` and `cap2_first_pass/`.

**Rerun.** All 23 cap2 domains that had at least one HTTP timeout or 0 items were rerun. Pass 4 results are filled in below.

### 2. Runner exited 0 when a domain produced no results

**Diagnosis.** When the MCP server fails during startup, the TaskGroup error is logged as "Cleanup error (ignored)". The domain then yields 0 results and the process exits 0.

**Fix.** Commit 0d11e4a: a domain with fewer results than items is not written, so a resumed run retries it, and the runner exits with code 2.

### 3. Evaluation wedged the REST server

**Diagnosis.** The evaluator re-executes tool calls against the same REST server. Running 16 eval jobs at once wedged it.

**Fix.** Eval runs per domain at 2 parallel jobs. Domains that failed were retried one at a time.

### 4. Operator errors

- At 05:33 the domain files were copied instead of moved before a rerun. Because the runner skips existing outputs, every domain was skipped. Relaunched at 05:34.
- A `pkill` pattern also killed the operator's own SSH session.
- `docker exec … kill` failed because the container has no `kill` binary. It must run as `sh -c "kill …"`.
- A manual 120 s curl test of the snowfall endpoint wedged the server again.

### 5. Runner stalled after a large tool response

**Diagnosis.** In pass 4, movie_platform task 114 called `user_avatar_image_urls_by_rating_score`. The REST call returned 200 after 19 s. The runner's main thread then stayed at 100% CPU, and tasks 114, 115 and 116 each hit the 300 s agent timeout. vLLM had no running requests, and the REST server was healthy. In passes 1 and 2 the model answered task 114 without a tool call, so this had not happened before. The per-task timeout cancels the agent but not the work that is still running in the shared process, so later tasks in the same domain are also delayed.

**Fix.** Attempt 1 was stopped and archived (`logs/failed_rest_wedge_1219/cap2_movie_platform.attempt1.log`), and the domain was rerun. The root fix, isolating each task or capping tool response size before processing, is left for B1/B2.

### 6. B1 gold check could not finish

**Diagnosis.** The gold check with judge (started 06:22) was still running at 09:22. py-spy showed it inside number tracing (`_trace_number`) for one cap2 movie_platform case. That gold answer is 853,500,443 characters, built from an 898 MB tool output. Tracing every number in it would not finish in any useful time.

**Fix.** Commit 80fdb28 on `capstone/b1-verifier`:
- `_trace_number` returns at the first direct hit. Output is unchanged.
- `gold-check` skips answers over 100,000 characters (`--max-answer-chars`, 0 = no limit) and lists each skipped case in the report.

Attempt 1 was stopped and its pane saved (`b1_gold_attempt1_pane.txt`). The rerun used one process per capability and finished in 28 minutes. 37 cases were skipped (13 cap1, 24 cap2).

The rerun showed that 24 cap4 gold answers of the form "I can not answer." were judged as errors. The abstention pattern matched `cannot` but not `can not`. Commit 21e0624 fixed the pattern, and cap4 was rerun.

The same `pkill -f` mistake from problem 4 happened again here and killed the operator's SSH session. State was checked before the rerun was started.

### 7. Two checks that passed when they should have failed

**mental_health_survey unscored.** The final report showed cap2 at 1,833/1,860 scored. The eval part for mental_health_survey had 0 paired predictions. It was written while the domain had no predictions, before its 04:42 rerun. Later evals skipped the domain because `evaluator.py` resumes from an existing output file. The completeness check only tested that each part file existed, so it printed `missing=0`.

**Fix.** The stale part was moved to `logs/stale_eval_mhs/` and the domain was re-evaluated (10/27). The check now reads every part and fails on any missing prediction or 0 paired dialogues (`/scratch/runs/check_parts.py`). All 137 parts pass. Commit 864a14d on `capstone/b0-full` puts the same rule in `merge_eval`: it exits 2 when any domain has ground-truth items without a prediction, so `run_cut.sh` counts it as an eval failure.

**B1 cap2 replay did not run.** `capstone.b1 replay` refuses to write into a non-empty directory. The caps 1/3/4 replay had already written to that directory, so the cap2 replay exited 1 and the B1 eval covered only caps 1/3/4. The wrapper script printed the exit code but did not stop.

**Fix.** The full replay, all capabilities, was rerun on 21e0624 into `b1_replay_b0full_v2`. The interim directory is kept as `b1_replay_b0full` (caps 1/3/4, 7c19752).

## Results

Final B0 scores, train split, 4,428/4,428 scored. Correct means score ≥ 1.0.

| capability | n | correct | accuracy | 95% CI |
|---|---|---|---|---|
| 1 · API chaining | 1324 | 676 | 0.511 | 0.48–0.54 |
| 2 · Tool selection | 1860 | 1121 | 0.603 | 0.58–0.62 |
| 3 · Multi-hop reasoning | 346 | 116 | 0.335 | 0.29–0.39 |
| 4 · Multi-source + policy | 898 | 386 | 0.430 | 0.40–0.46 |
| all | 4428 | 2299 | 0.519 | 0.50–0.53 |

Error labels for the 2,129 wrong answers (automatic first pass):

| headline | sub-reason | n | share |
|---|---|---|---|
| supported_but_wrong | wrong_tool | 1110 | 52.1% |
| not_supported | answer_not_in_output | 498 | 23.4% |
| not_supported | no_answer | 320 | 15.0% |
| supported_but_wrong | wrong_arguments | 200 | 9.4% |
| supported_but_wrong | wrong_reasoning | 1 | 0.0% |
| — | reference_wrong | 0 | needs human review |

Lowest and highest domains (10 or more tasks):

| cap | lowest | highest |
|---|---|---|
| 1 | authors 3/54, computer_student 5/27, genes 2/10 | music_tracker 12/18, disney 16/23, olympics 48/65 |
| 2 | college_completion 1/17, restaurant 8/27, sales_in_weather 18/54 | books 60/78, computer_student 22/28, ice_hockey_draft 38/46 |
| 3 | college_completion 1/22, trains 1/13, computer_student 2/20 | european_football_1 5/11, disney 15/31, soccer_2016 38/78 |
| 4 | authors 0/21, computer_student 1/20, menu 1/18 | books 20/28, beer_factory 21/29, ice_hockey_draft 12/13 |

Full per-domain table: `analysis/accuracy_by_domain.csv` and `analysis/report.md`.

Latency per task: mean 48 s, p50 16 s, p90 144 s. cap1 is the slowest (p50 41 s, p90 288 s).

cap2 domains rerun in pass 4: beer_factory 26/36, cars 29/40, movie_platform 89/150, bike_share_1 14/37, sales_in_weather 18/54. mental_health_survey (rerun at 04:42): 10/27.

## Caveats

- bike_share_1 (24 HTTP errors) and sales_in_weather (162 HTTP errors) were scored with errors, even though each ran alone. One blocking query also delays the other endpoints in the same domain. This is how the environment is built, and other variants will meet the same errors.
- The operator's usage limit stopped work from 10:30 to 18:15. The droplet was billed for that time with nothing running.
- Some agent errors remain in the scores as failures:
  - context overflow: cap4 106 (inputs up to 551k tokens against a 65,536 limit), cap2 5, cap3 1
  - cap1 "Unknown role": 5
  - 300 s agent timeouts: cap1 119, cap4 53
- `reference_wrong` needs human review, so its automatic count is 0.
- Commits d660904 (MCP session reconnect) and aa6faf3 (run_cut.sh health gate, PARALLEL_CAP, EVAL_RETRIES) were not exercised in a full run.

## Lessons for B1/B2

- **Tool-server health guard:** check REST health before every domain and every eval job, and restart after 10 minutes of failure.
- **Concurrency limits:** run blocking-query domains alone and last. Keep cap2 agents at 6 or fewer and cap2 eval at 2 or fewer.
- **Completeness checks:** after each domain, check predictions = ground truth and 0 HTTP errors. Fail loudly on 0 items (0d11e4a).
- **Eval retry:** retry failed domain evals one at a time.
- **Completeness means scored, not present:** check paired predictions per domain, not file existence (864a14d). An evaluator that resumes from its output file will keep a stale result.
- **Fresh output directories:** give every replay or rerun its own new directory, and have wrapper scripts stop on the first failed step.
- **Idle cost:** when the operator may be interrupted, end long scripts with a checkpoint that needs no follow-up, so the droplet can be torn down without waiting.
- **Server fix as an environment change:** a multi-worker or threadpool REST server would remove the wedge. It changes the environment, so it must be documented and applied to every variant.

## B1 offline replay

### Gold check with judge

The verifier was run on the gold (reference) answers, which should all be accepted, and on seeded wrong answers, which should all be rejected. Judge: gpt-oss-120b on the same vLLM server.

Gold answers, 4,391 checked (37 skipped for size). cap1–cap3 from 80fdb28, cap4 from 21e0624:

| cap | n | accept | reject | insufficient | false-alarm rate |
|---|---|---|---|---|---|
| cap1 | 1311 | 1290 | 14 | 7 | 1.07% |
| cap2 | 1836 | 1825 | 10 | 1 | 0.54% |
| cap3 | 346 | 344 | 2 | 0 | 0.58% |
| cap4 | 898 | 894 | 1 | 3 | 0.11% |
| all | 4391 | 4353 | 27 | 11 | 0.61% |

Before the abstention fix, cap4 was 773 / 26 / 99 (false-alarm rate 2.9%).

Seeded errors (80fdb28, all caps):

| seed | identifiable | rejected | detection |
|---|---|---|---|
| number_shift | 2785 | 2785 | 100% |
| date_shift | 89 | 89 | 100% |
| id_swap | 172 | 172 | 100% |
| entity_swap | 1036 | 1023 | 98.75% (13 insufficient) |

Remaining gold false alarms are mostly short bare-name answers rejected by the judge (judge evidence is capped at 12,000 characters) and a few list answers.

### Replay on B0 predictions

The verifier was run over all 4,428 B0 predictions with the flag policy: it records a verdict and changes no answers, so the scores equal B0 (2,299/4,428). Code: 21e0624. Tool outputs were re-collected for every task; the cap2 collect covered all 40 domains (not a sample) and took 6 minutes. The judge was called on 363 tasks.

"Correct" and "wrong" are the B0 scores. False-alarm rate is rejected correct answers over all correct answers. Catch rate is rejected wrong answers over all wrong answers.

| cap | n | accept (correct / wrong) | reject (correct / wrong) | insufficient (correct / wrong) | false-alarm rate | catch rate | insufficient rate |
|---|---|---|---|---|---|---|---|
| cap1 | 1324 | 657 / 420 | 19 / 102 | 0 / 126 | 2.8% | 15.7% | 9.5% |
| cap2 | 1860 | 1016 / 428 | 103 / 207 | 2 / 104 | 9.2% | 28.0% | 5.7% |
| cap3 | 346 | 96 / 146 | 20 / 69 | 0 / 15 | 17.2% | 30.0% | 4.3% |
| cap4 | 898 | 312 / 252 | 32 / 119 | 42 / 141 | 8.3% | 23.2% | 20.4% |
| all | 4428 | 2081 / 1246 | 174 / 497 | 44 / 386 | 7.6% | 23.3% | 9.7% |

By path: deterministic checks decided 4,065 tasks (false alarm 7.7%, catch 22.8%); the judge decided 363 (false alarm 4.7%, catch 28.1%).

What this means for B1:
- Accepted answers are 62.5% correct (2,081 of 3,327), against 51.9% for all answers.
- Rejected answers are 74.1% wrong (497 of 671). Insufficient answers are 89.8% wrong (386 of 430).
- The false-alarm rate on real predictions (7.6%) is much higher than on gold answers (0.6%). cap3 is the worst at 17.2%.
- All 320 `no_answer` errors were marked insufficient, not rejected.

Catch rate by error label (labels from the b1-verifier branch):

| label | wrong | rejected | insufficient | accepted | catch rate |
|---|---|---|---|---|---|
| wrong_tool | 1256 | 347 | 56 | 853 | 27.6% |
| answer_not_in_output | 339 | 103 | 8 | 228 | 30.4% |
| no_answer | 320 | 0 | 320 | 0 | 0% |
| wrong_arguments | 212 | 46 | 2 | 164 | 21.7% |
| wrong_reasoning | 2 | 1 | 0 | 1 | 50% |

The b1-verifier branch labels errors differently from the B0 analysis above (for example wrong_tool 1,256 against 1,110, and answer_not_in_output 339 against 498). Both total 2,129. Compare the two tables by label only after the label code is reconciled.

An earlier replay of caps 1, 3 and 4 only (7c19752, n 2,568: false alarm 6.0%, catch 20.9%) is kept in `b1_replay_b0full/` and replaced by the full run.

Output: `/workspace/berkeley/runs/b1_replay_b0full_20261030/` (`b1_replay_b0full_v2/`, `b1_logs/`). The two eval files over 50 MB are byte-identical to the B0 eval files and are not duplicated.
