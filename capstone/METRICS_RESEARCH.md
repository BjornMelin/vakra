# Metrics and experimental variables for B0/B1/B2 on VAKRA: research and recommendations

Project: "Checking the answer, not just the tool call" (DATASCI 210, Bjorn Melin and Thomas Young)
Prepared: Thu 29 Oct 2026 (America/Denver, MDT). Status: proposal for review. It does not edit `capstone-master-plan.md`. Items to fold into that plan are listed in the final section.

## 0. Summary

1. **Branch the systems instead of re-running them.** Compute B1 by replaying its checks on the saved B0 trajectories. Run B2 by resuming only the flagged trajectories for the recovery step. Every B0 → B1 → B2 difference then comes from the intervention and not from run-to-run noise in vLLM, and the paired experiment costs about one B0 run plus about 30%, not three full runs.
2. **Add a compute-matched control for B2.** Trigger the same recovery step on a random set of tasks, with the trigger rate equal to B1's flag rate. Without this control, a B2 gain cannot be credited to the verifier signal and not to extra compute (Kapoor et al.; Huang et al.).
3. **Measure the noise floor before running sweeps.** Run B0 twice more on a dev subset at temperature 0 and report the per-task flip rate. Zero temperature does not make vLLM inference deterministic (Atil et al.; Thinking Machines).
4. **Treat B1's verifier quality vs gold (precision, recall, false-alarm rate) as a primary metric, and report the deterministic path and the judge path separately.** Choose verifier strictness offline on dev traces. This needs no GPU time.
5. **For B2, report "fixed" (wrong → right) and "broken" (right → wrong) counts, not just net accuracy.** Self-correction is known to break correct answers when the feedback comes from the model itself (Huang et al.; Kamoi et al.).
6. **Keep three tuning sweeps, redesigned to be cheaper and free of leakage:**
   - Reasoning effort: low and high on a 400-task dev subset; medium is reused from B0.
   - Max steps: lower caps simulated offline; only tasks that hit the cap are re-run at a higher cap.
   - Tool-list size: vary the existing shortlister `--top-k-tools` (default 128), after an offline recall@k check, instead of selecting gold tools plus distractors.
7. **Skip temperature, prompt-format, tool-description and serving-parameter sweeps.** Record them as fixed settings and limitations.
8. **Statistics:**
   - At most two primary comparisons.
   - Exact McNemar on a pre-registered binarization.
   - Paired bootstrap clustered by domain.
   - Three repeats on the frozen set, which also yield pass^k with k ≤ 3.
   - The MDE table is in §5.

**Proposed core set:** about 59 GPU-hours (~$152) in the central timing scenario, or 34–89 GPU-hours (~$88–$229) across the optimistic and pessimistic scenarios. Each total includes 7.5 h of session overhead and a 25% reserve. The full $483 credit is about 186.5 GPU-hours. Adding the if-time items and a conditional gated-test run gives 50–140 GPU-hours (~$130–$362). Every figure rests on an assumed seconds-per-task value because **no per-task timing has been measured yet**. Timing tonight's ~270-task B0 run is the first action.

## 1. Sources consulted (all opened on 29 Oct 2026)

VAKRA and the project
- [VAKRA] IBM Research, VAKRA paper, https://arxiv.org/abs/2608.12282
- [VAKRA-blog] "VAKRA benchmark analysis", https://huggingface.co/blog/ibm-research/vakra-benchmark-analysis
- [VAKRA-repo] https://github.com/IBM/vakra (README test-split table: 2,077 / 1,597 / 869 / 644 samples for capabilities 1–4)
- Local: `vakra/benchmark_runner.py` (`--top-k-tools` default 128; `--max-iterations` default None, with 10 for capability 1 and the provider default otherwise; `AGENT_TIMEOUT_SECONDS` default 300; `--temperature` default 0.0), `vakra/agents/components/tool_shortlister.py` (all-MiniLM-L6-v2 cosine shortlist), `vakra/evaluator/judge.py` (judge default `openai/gpt-oss-120b`, temperature 0), `vakra/capstone/data_stats.md` (train: 1,324 / 1,860 / 346 / 898 = 4,428 tasks; sales_in_weather 70).

Agent and tool-use benchmarks
- [tau] Yao et al., τ-bench, https://arxiv.org/abs/2406.12045
- [tau2] τ²-bench, https://arxiv.org/abs/2506.07982
- [BFCL] Berkeley Function Calling Leaderboard blog, https://gorilla.cs.berkeley.edu/blogs/8_berkeley_function_calling_leaderboard.html
- [ToolLLM] https://arxiv.org/abs/2307.16789; [StableToolBench] https://arxiv.org/abs/2403.07714; [AppWorld] https://arxiv.org/abs/2407.18901; [AgentBench] https://arxiv.org/abs/2308.03688

Evaluation methodology and cost
- [Kapoor] Kapoor et al., "AI Agents That Matter", https://arxiv.org/abs/2407.01502
- [HAL] Holistic Agent Leaderboard, https://arxiv.org/abs/2510.11977
- [HELM] https://arxiv.org/abs/2211.09110
- [Miller] Miller, "Adding Error Bars to Evals", https://arxiv.org/abs/2411.00640
- [Card] Card et al., "With Little Power Comes Great Responsibility", https://arxiv.org/abs/2010.06595
- [Dror] Dror et al., "The Hitchhiker's Guide to Testing Statistical Significance in NLP", https://aclanthology.org/P18-1128/
- [statsmodels] McNemar documentation, https://www.statsmodels.org/stable/generated/statsmodels.stats.contingency_tables.mcnemar.html

Self-correction, verification and judges
- [Huang] Huang et al., "LLMs Cannot Self-Correct Reasoning Yet", https://arxiv.org/abs/2310.01798
- [Kamoi] Kamoi et al., "When Can LLMs Actually Correct Their Own Mistakes?", https://arxiv.org/abs/2406.01297
- [Tyen] Tyen et al., "LLMs cannot find reasoning errors, but can correct them given the error location", https://arxiv.org/abs/2311.08516
- [CRITIC] https://arxiv.org/abs/2305.11738; [CoVe] https://arxiv.org/abs/2309.11495; [Reflexion] https://arxiv.org/abs/2303.11366
- [Panickssery] https://arxiv.org/abs/2404.13076; [Wataoka] https://arxiv.org/abs/2410.21819; [Zheng] MT-Bench / LLM-as-a-judge, https://arxiv.org/abs/2306.05685; [Thakur] "Judging the Judges", https://arxiv.org/abs/2406.12624
- [AbstSurvey] https://arxiv.org/abs/2407.18418; [AbstBench] AbstentionBench, https://arxiv.org/abs/2506.09038

Model, inference, prompts, tools
- [gpt-oss] model card, https://arxiv.org/abs/2508.10925
- [vLLM-recipe] vLLM GPT-OSS recipe, https://docs.vllm.ai/projects/recipes/en/latest/OpenAI/GPT-OSS.html
- [Atil] Atil et al., non-determinism of "deterministic" LLM settings, https://arxiv.org/abs/2408.04667
- [TM] Thinking Machines, "Defeating Nondeterminism in LLM Inference", https://thinkingmachines.ai/blog/defeating-nondeterminism-in-llm-inference/
- [Sclar] prompt-format sensitivity, https://arxiv.org/abs/2310.11324
- [Hsieh] tool documentation for zero-shot tool use, https://arxiv.org/abs/2308.00675
- [RAG-MCP] https://arxiv.org/abs/2505.03275
- [LostMiddle] https://arxiv.org/abs/2307.03172
- [DO] DigitalOcean GPU Droplet pricing, https://www.digitalocean.com/pricing/gpu-droplets

## 2. Evidence that shapes the design

- **The VAKRA evaluator checks stages in order** [VAKRA-blog]:
  - a policy check for capability 4;
  - a tool-sequence check that re-executes the predicted calls and tests whether the ground-truth tool responses are contained in them, with an LLM-judge fallback;
  - a final-response judge for groundedness in the predicted tool outputs and consistency with the ground truth.
  
  Each failure is assigned to the earliest stage that fails. The paper reports a matching "sieve" for gpt-oss-120b [VAKRA]:
  - Dashboard: Tool 72.7 → ArgN 72.3 → ArgV 59.9 → Gnd 50.5.
  - SLOT: 86.2 → 85.3 → 64.0 → 42.7.
  - Within the grounding stage, 68.9% (Dashboard) and 75.8% (BI) of failures are labeled hallucination rather than extraction error.
  
  This is direct evidence that the "answer not supported by tool output" failure B1 targets is the dominant final-stage failure for this model.
- **The evaluation judge is the same model as the agent.** The judge default is gpt-oss-120b at temperature 0 (`evaluator/judge.py`). Self-recognition correlates with self-preference [Panickssery], and GPT-4 judges favor lower-perplexity text [Wataoka]. Only the strongest judges align well with humans, and leniency bias is common [Thakur]. Judge error that differs between B0 and B2 outputs could create or hide an effect, so a human audit is required (§3, M17).
- **Self-correction needs a reliable external signal.** Prompted self-correction without external feedback does not reliably improve reasoning and can degrade it [Huang]. Successful self-correction appears with reliable external feedback or fine-tuning, and rarely from prompted self-feedback [Kamoi]. Models correct errors much better when given the error's location [Tyen], and tool-grounded critique helps [CRITIC]. Implications:
  - B1's deterministic value-tracing check counts as external feedback.
  - B1's free-text judge path is a same-model self-check and should be expected to perform worse.
  - B2's recovery prompt should pass the specific unsupported value (the location), not a generic "re-check".
- **Simple baselines and cost must be reported.** Retry-style baselines can match complex agents at lower cost, and evaluation should be cost-controlled, with the accuracy-cost trade-off shown jointly [Kapoor]. B2 therefore needs a compute-matched non-verifier control.
- **Reasoning effort is not monotone for agents.**
  - On static benchmarks, gpt-oss-120b rises from low to medium to high effort: GPQA 65.3 / 72.4 / 79.4 and AIME25 51.2 / 79.6 / 93.0 [vLLM-recipe].
  - In agent harnesses, HAL reports that higher reasoning effort reduced accuracy in the majority of runs [HAL].
  
  The direction on VAKRA is an open empirical question, so this sweep is informative.
- **Temperature 0 is not deterministic on vLLM.**
  - In [TM], 1,000 temperature-0 completions of one prompt on Qwen3-235B gave 80 unique outputs. Batch-invariant kernels removed the variation.
  - [Atil] reports accuracy variation of up to 15% across nominally deterministic runs.
  
  B0 vs B0 reruns therefore produce discordant pairs that a McNemar test would count as effects.
- **Consistency differs from single-run accuracy.** τ-bench defines pass^k, the probability that all k i.i.d. trials succeed, estimated without bias from n trials per task. It reports gpt-4o pass^8 below 25% on retail [tau].
- **Statistics for evals** [Miller]:
  - Use paired analysis on shared questions.
  - Use clustered standard errors when questions are grouped. Clustered SEs can be several times larger than naive SEs.
  - Average repeated samples per question to reduce variance.
  - Do not raise the temperature only to measure variance.
  
  Typical NLP comparisons are underpowered [Card]. [Dror] gives a protocol for choosing the test. statsmodels' `mcnemar(exact=True)` uses the binomial distribution [statsmodels].
- **Large tool lists hurt selection; retrieval helps.** RAG-MCP retrieval cut prompt tokens by more than 50% and raised tool-selection accuracy from 13.62% to 43.13% [RAG-MCP]. VAKRA already shortlists to 128 tools because the OpenAI tool-list limit is 128; Dashboard domains have up to 328 tools [VAKRA-blog].
- **Prompt and documentation sensitivity is large but outside our question.** Formatting alone moved accuracy by up to 76 points [Sclar], and tool documentation can substitute for demonstrations [Hsieh]. Changing VAKRA's tool descriptions changes the benchmark, so we hold them fixed.
- **Abstention.** Reasoning fine-tuning degraded abstention by 24% on average [AbstBench]. If B1 or B2 can abstain, accuracy must be reported together with coverage [AbstSurvey].

## 3. Metrics

Scale: 10 = must report and directly tests the thesis; 0 = irrelevant. GPU cost is the *extra* GPU time beyond the runs already planned. "0" means the metric is computed from saved outputs on CPU.

| # | Metric | Score | Hypothesis / why | Extra GPU-h | Rec. |
|---|---|---:|---|---:|---|
| M1 | Accuracy per capability and per domain, plus the VAKRA aggregate (mean of the 4 capabilities; capability 4 multi-source items weighted ×2 [VAKRA-blog]); also reported with reference-wrong tasks excluded | 10 | Headline; B2 > B0, with the largest gains in capabilities 2–3, where the grounding stage dominates failures [VAKRA] | 0 | core |
| M2 | Paired transition counts B0→B2: fixed (0→1), broken (1→0), unchanged | 10 | Broken > 0 is expected; a net gain requires fixed ≫ broken [Huang] | 0 | core |
| M3 | B1 verifier precision, recall, false-alarm rate (flagged among correct) against gold correctness, split into deterministic and judge paths | 10 | Deterministic path: high precision. Judge path: lower precision and more false alarms (same-model self-check [Huang], [Panickssery]) | 0 (offline replay; judge calls are counted in B1 development) | core |
| M4 | Seeded-error detection rate (WS2.3) | 8 | Measures recall on known injected value errors, independent of evaluator noise | ~0 | core |
| M5 | Grounded-answer rate: share of final answers whose values all trace to tool output (B1's deterministic check used as a metric on every system) | 8 | B2 raises it. Caveat: circular when used to judge B1 itself; report the evaluator's groundedness score next to it | 0 | core |
| M6 | Error-label distribution: not supported vs supported-but-wrong, and sub-reasons, with Cohen's κ | 9 | B2 shrinks "not supported"; "supported but wrong" and "reference wrong" stay unchanged | 0 (human time) | core |
| M7 | B2 recovery success: fix rate among flagged-and-wrong, break rate among flagged-and-correct, and the same rates under the random-trigger control | 10 | Verifier-triggered fix rate > random-trigger fix rate; this is the causal test of the verifier signal | counted in §6 | core |
| M8 | VAKRA sieve: Tool / ArgN / ArgV / Gnd pass rates (earliest failing stage) | 8 | B2 gains appear at the Gnd stage, not at Tool/Arg | 0 (evaluator output) | core |
| M9 | Run-to-run flip rate (B0 vs B0 repeat), per capability | 9 | Non-zero at temperature 0 [TM], [Atil]; sets the noise floor for M2 | counted in §6 | core |
| M10 | pass^k (k ≤ 3) and the per-task success fraction across repeats | 7 | Verification should raise pass^k more than pass^1 by removing unstable unsupported answers | 0 beyond 3 frozen repeats | core |
| M11 | Steps and tool calls per task; step-cap hit rate; timeout rate (300 s) and exception rate | 8 | Needed to interpret the max-steps sweep and B2 overhead | 0 | core |
| M12 | Tokens per task (prompt, completion, reasoning) | 8 | Cost driver; high effort raises reasoning tokens | 0 (vLLM usage fields) | core |
| M13 | Latency per task and GPU-seconds per task | 8 | Needed for the budget and the cost-accuracy frontier | 0 | core |
| M14 | Cost per task and per correct answer ($ at $2.59/GPU-h [DO]); accuracy-cost Pareto plot [Kapoor] | 7 | B2 sits on the frontier only if its gain beats the random-trigger control at equal cost | 0 | core |
| M15 | Shortlist recall@k: share of tasks whose gold tools all fall within the top-k shortlist | 8 | Recall falls sharply below some k in Dashboard domains; this bounds the tool-list sweep | 0 (CPU embeddings) | core |
| M16 | Abstention or refusal rate, and selective accuracy vs coverage | 6 (7 if B1/B2 can abstain) | Only meaningful if the systems can decline to answer; if so, report accuracy at matched coverage | 0 | core if abstention exists, else skip |
| M17 | Evaluator-judge audit: human labels on a stratified sample (e.g., 100 tasks: 50 judged correct, 50 judged wrong, balanced over B0/B2); judge error rate per system | 8 | Judge error is non-zero and possibly differs by system because of self-preference [Panickssery], [Wataoka] | 0 (human time) | core |
| M18 | Tool-call precision and recall against gold call sets (BFCL-style required-parameter and type matching [BFCL]) | 5 | Mostly redundant with M8; useful only for capability 2 selection diagnostics | 0 | if-time |
| M19 | Per-hop accuracy by hop depth (capabilities 3–4) | 5 | B2 helps more on deeper chains | 0 if hop metadata exists | if-time |
| M20 | Policy-adherence rate (capability 4) | 4 | Not part of the thesis; the evaluator's policy stage already runs | 0 | if-time |
| M21 | Verifier calibration (ECE of judge confidence) | 3 | The deterministic path has no confidence score; low value | 0 | skip |
| M22 | HELM-style toxicity, bias and fairness [HELM] | 1 | Not relevant to grounded tool answers | 0 | skip |
| M23 | Long-horizon state metrics (AppWorld collateral damage [AppWorld]) | 2 | VAKRA tools are read-only queries | 0 | skip |

## 4. Variables

Costs use the formula in §6 with the central assumption (10 effective GPU-seconds per task). Optimistic and pessimistic values are in the §6 table.

| # | Variable | Score | Hypothesis | GPU-h (central) | Rec. |
|---|---|---:|---|---:|---|
| V1 | Repeats at fixed temperature 0 (seeds / reruns) | 9 | The flip rate is several percent per capability [Atil], [TM]; repeats are needed for pass^k and for honest McNemar | 2.2 (dev noise floor) + included in the frozen ×3 | core |
| V2 | Recovery trigger: verifier-flagged vs random at matched rate (compute-matched control) | 9 | The verifier trigger fixes more and breaks fewer than random [Kapoor], [Kamoi] | 3.7 (frozen ×3) | core |
| V3 | Verifier strictness: numeric tolerance, unit and date normalization, ID match, judge threshold | 9 | A strictness level exists with recall ≥ ~0.8 at a false-alarm rate that leaves B2 net-positive; chosen on dev precision-recall curves | ~0 (offline replay) | core |
| V4 | Reasoning effort {low, medium, high} | 8 | Static benchmarks rise with effort [vLLM-recipe], but agent harnesses often get worse [HAL]. Expect a token and latency rise with high effort and no monotone accuracy gain | 2.9 | core |
| V5 | Tool-list size via shortlister `top_k` {32, 64, 128} | 8 | Smaller k cuts "wrong tool" errors and tokens [RAG-MCP] until recall@k (M15) drops. Uses the existing shortlister, so no gold-tool leakage | 1.7 | core |
| V6 | Max agent steps | 7 | Lower caps can be simulated offline: a trajectory that finished in ≤ c steps is unchanged under cap c, apart from nondeterminism. Raising the cap matters only for tasks that hit it | 0.5 | core |
| V7 | Recovery feedback content: located (names the unsupported value and the tool output) vs generic | 7 | Located feedback fixes more [Tyen], [CRITIC] | 1.2 (frozen ×1) | if-time |
| V8 | Retry budget: 1 vs 2 recovery steps | 5 | Diminishing returns; the second step mostly breaks answers [Huang] | 0.6 | if-time |
| V9 | Model size: gpt-oss-20b vs 120b | 5 | The smaller model makes more unsupported answers, so checking helps it more. Requires a model reload. The 20b falls 4.9–8.5 points below 120b on GPQA across effort levels [vLLM-recipe] | 4.0 (+ reload) | if-time |
| V10 | B1 judge-path model (120b vs 20b as the free-text judge) | 5 | A different model reduces self-preference [Panickssery] but is weaker | ~0.3 | if-time |
| V11 | System prompt paraphrase (one alternative) | 4 | Bounds format sensitivity [Sclar]; not part of the thesis | 1.1 | if-time |
| V12 | Temperature > 0 | 3 | Adds variance without informing the thesis; [Miller] advises against changing temperature to estimate variance | — | skip |
| V13 | Tool-description quality | 3 | Large effects are plausible [Hsieh], but editing descriptions changes the benchmark | — | skip |
| V14 | Context length (`--max-model-len 65536`) | 3 | Only matters if traces overflow. Log overflow and truncation counts (M11) instead [LostMiddle] | — | skip (monitor) |
| V15 | Serving parameters (max-num-seqs, batched tokens, KV dtype) | 2 | Affects throughput and nondeterminism, not the thesis; hold fixed and record in the manifest | — | skip |
| V16 | Other model families (e.g., DeepSeek) | 2 | Different hardware fit and an extra confound; outside the budget | — | skip |
| V17 | Gold tools + k distractors (current WS5.3 idea) | 3 | Leaks gold tool identity; diagnostic only. V5 replaces it | — | skip |

## 5. Statistical plan

1. **Primary comparisons are fixed before 25 Nov:**
   - (P1) B2 vs B0 accuracy on the frozen set.
   - (P2) B2 vs the random-trigger control.
   
   Report B1 detection quality (M3) as an estimate with a CI, not as a test. Everything else is secondary. Apply Holm across the primary family; report per-capability results as exploratory, with unadjusted CIs labeled as such.
2. **Binarization.**
   - Primary: correct if the task score equals 1.0.
   - Sensitivity: mean partial score, analyzed with a paired bootstrap.
   
   Record this rule in the freeze manifest, closing the OPEN item at master plan line 243.
3. **Paired test.**
   - Exact McNemar (`statsmodels ... mcnemar(table, exact=True)`) [statsmodels] on the per-task outcomes.
   - With 3 repeats, use the per-task majority (or mean, with a paired t / bootstrap) so each task contributes once [Miller]. Do not pool 3n as independent.
4. **CIs.** Use a paired bootstrap (10,000 resamples, fixed seed) clustered by domain [Miller]. Report the task-level bootstrap as a sensitivity check. If the clustered and naive intervals differ a lot, use the clustered one.
5. **Noise floor.**
   - Report the B0 vs B0' discordance from V1 for each capability.
   - Report a B2 effect alongside it.
   - If B2's discordant pairs are not clearly above the B0 vs B0' rate, the effect is not established.
6. **MDE.** δ ≈ (z_{α/2} + z_β) · √(d/n), where d is the discordant share and the power is 80%. This is the paired-proportion form of the [Miller] power formula. Values below come from `research-src/budget_calc.py`. The clustering design effect enlarges them by √DEFF, which is estimated from B0.

| n tasks | d | MDE, α=0.05 | MDE, α=0.0167 |
|---:|---:|---:|---:|
| 400 | 0.10 | 4.4 pp | 5.1 pp |
| 1,370 | 0.10 | 2.4 pp | 2.8 pp |
| 2,200 | 0.05 | 1.3 pp | 1.5 pp |
| 2,200 | 0.10 | 1.9 pp | 2.2 pp |
| 2,200 | 0.20 | 2.7 pp | 3.1 pp |

   Implication: dev sweeps on 400 tasks can detect only effects of about 4–6 pp. Treat sweep outcomes as selection heuristics, not findings. Because a recovery step touches only flagged tasks, d for B2 vs B0 is at most the trigger rate, so the frozen set should be as large as the evaluation domains allow.
7. **pass^k.** Use the unbiased estimator pass^k = E_task[C(c,k)/C(n,k)] with n = 3 repeats, reported for k = 1, 2, 3 [tau].
8. **Inter-rater agreement.** Report Cohen's κ with a bootstrap CI (WS4.4), and per-system judge error from M17.
9. **Tuning hygiene.** Select settings only on development domains, and freeze them before any evaluation-domain run. Report dev numbers as exploratory, since selecting the best of several configurations inflates dev estimates.

## 6. Cost model and budget

- **Price.** $2.59 per MI300X GPU-hour on-demand. Billing is per second with a 5-minute minimum, and powered-off droplets are still billed [DO]. $483 ÷ 2.59 ≈ 186.5 GPU-hours. The remaining balance is OPEN.
- **Formula.** GPU-h = task-equivalents × effective sec/task ÷ 3600, plus 0.5 h of session overhead × 15 sessions (both ASSUMPTIONS), plus a 25% reserve.
- **ASSUMPTION: effective sec/task = 5 / 10 / 16** (optimistic / central / pessimistic). This is GPU wall time per task at the run's concurrency, including VAKRA judge scoring. It is anchored to the baseline guide's own guess of 6–20 h for the 4,428-task train set (≈ 4.9–16.3 s/task). No measurement exists.
- **Other ASSUMPTIONS:**
  - Evaluation-domain frozen set F ≈ 2,200 tasks (about half of the train split).
  - Dev sweep subset of 400 tasks drawn from the B0 N=10 run.
  - B1 flags 40% of tasks.
  - One recovery step costs 0.5 task.
  - The B1 judge adds 10%.
  - Low and high effort cost 0.6× and 2.0× a medium-effort task.
  - gpt-oss-20b costs 0.5×.
  
  Replace every assumption with measured values after tonight's run.

| Item | Task-equiv | GPU-h @5s | @10s | @16s | Tier |
|---|---:|---:|---:|---:|---|
| B0 N=10 per domain (WS1.3), 1,370 tasks | 1,370 | 1.9 | 3.8 | 6.1 | core |
| Noise floor: 2 extra B0 repeats on dev subset | 800 | 1.1 | 2.2 | 3.6 | core |
| Reasoning effort low + high on dev subset | 1,040 | 1.4 | 2.9 | 4.6 | core |
| Max steps: re-run only cap-hitting tasks at a higher cap | 180 | 0.2 | 0.5 | 0.8 | core |
| Shortlist top_k 32 and 64, dev capabilities 2–4 (300 tasks each) | 600 | 0.8 | 1.7 | 2.7 | core |
| B1 development: free-text judge calls on dev | 120 | 0.2 | 0.3 | 0.5 | core |
| B2 development: recovery on flagged dev tasks, 3 iterations | 240 | 0.3 | 0.7 | 1.1 | core |
| Frozen set: B0 + B1 (replay) + B2 (branch), ×3 repeats | 8,580 | 11.9 | 23.8 | 38.1 | core |
| Frozen set: random-trigger control at B1's trigger rate, ×3 | 1,320 | 1.8 | 3.7 | 5.9 | core |
| **Core subtotal** | | 19.8 | 39.6 | 63.3 | |
| **Core + 7.5 h overhead + 25% reserve** | | **34.1 ($88)** | **58.9 ($152)** | **88.5 ($229)** | |
| If-time: located vs generic recovery feedback, frozen ×1 | 440 | 0.6 | 1.2 | 2.0 | if-time |
| If-time: second recovery step, frozen ×1 | 220 | 0.3 | 0.6 | 1.0 | if-time |
| If-time: gpt-oss-20b B0/B1/B2, frozen ×1 | 1,430 | 2.0 | 4.0 | 6.4 | if-time |
| If-time: one prompt paraphrase on dev | 400 | 0.6 | 1.1 | 1.8 | if-time |
| **Core + if-time (with overhead and reserve)** | | 38.4 ($100) | 67.5 ($175) | 102.4 ($265) | |
| Conditional: gated test, single B0/B1/B2 pipeline run, 5,187 tasks | 6,743 | 9.4 | 18.7 | 30.0 | conditional |
| **All tiers (with overhead and reserve)** | | 50.1 ($130) | 90.9 ($235) | 139.8 ($362) | |

**Reading the table:**
- Even the pessimistic all-tiers total is below 186.5 GPU-hours. However, that bound does not count spend before today, and the balance is unconfirmed.
- If measured sec/task is above about 30 s, cut the frozen-set repeats from 3 to 2 before cutting the random-trigger control.
- The gated-test run, if access is granted, must finish before the 14 Dec expiry, and its pipeline must be frozen on 25 Nov.

**Schedule fit** (all dates America/Denver):
- B0 N=10 by Wed 4 Nov.
- Noise floor and the three sweeps on dev by Sat 21 Nov (about 7.3 GPU-h central).
- B1 strictness chosen offline by Wed 11 Nov.
- B2 design by Wed 18 Nov.
- Freeze Wed 25 Nov.
- Frozen ×3 plus control by Wed 2 Dec (about 27.5 GPU-h central, roughly 2–3 sessions).

## 7. Open items

- Measured effective sec/task, tokens per task and concurrency from the ~270-task B0 run (after the scoring fix).
- Remaining credit balance and the confirmed expiry date (Bjorn).
- Whether B1 is purely a post-answer check, in which case offline replay is exact, or changes the trajectory before the final answer, in which case it needs a run.
- Whether B1/B2 can abstain (decides M16).
- The dev/evaluation domain split, and therefore the size of F.
- Hop-depth metadata availability (M19).
- The `max_iterations` default for capabilities 2–4 (the provider/LangGraph default is used); read it from `config.json` or the LangGraph version in use.
- Whether a second evaluator judge (non-gpt-oss) may be used; this needs Bjorn's approval if it costs money.

## Changes to fold into the master plan

**WS4 (analysis pipeline)**
- 4.2: Add these columns to `metrics.py`:
  - fixed / broken / unchanged transition counts per system pair (M2);
  - sieve stage pass rates Tool / ArgN / ArgV / Gnd (M8);
  - step-cap hit, timeout and exception rates (M11);
  - prompt / completion / reasoning tokens (M12);
  - GPU-seconds and $ per task and per correct answer at $2.59/GPU-h (M13, M14);
  - pass^k for k = 1–3 with the unbiased estimator (M10).
- 4.2: Add `verifier_eval.py`: B1 precision, recall and false-alarm rate against gold, split into deterministic and judge paths, plus the precision-recall curve over strictness settings (M3, V3).
- 4.2: Add `shortlist_recall.py`: recall@k of gold tools under the existing all-MiniLM-L6-v2 shortlister for k ∈ {16, 32, 64, 128}, CPU only (M15).
- 4.3:
  - Fix the primary family to P1 (B2 vs B0) and P2 (B2 vs random-trigger control), with Holm across P1–P2.
  - Treat per-capability tests as exploratory.
  - Binarize with score == 1.0; run the mean-score paired bootstrap as sensitivity.
  - With repeats, use one aggregated outcome per task.
- 4.3: Report the noise floor (B0 vs B0' discordance per capability) next to every paired result, and fill in the MDE table (§5) using the observed d and the clustering design effect.
- 4.4 (new sub-item): Evaluator-judge audit. Human labels on a stratified sample of about 100 tasks balanced across B0 and B2; report the judge error rate per system (M17).

**WS5 (tuning and ablations)**
- New 5.0 (before 5.1): Noise floor. Run 2 extra B0 repeats on the 400-task dev subset at temperature 0. Output: the flip rate per capability. About 2.2 GPU-h central.
- 5.1: Low and high effort on the 400-task dev subset, reusing medium from B0. Record the hypothesis as two-sided, citing [vLLM-recipe] vs [HAL]. About 2.9 GPU-h.
- 5.2: First simulate lower caps offline from B0 traces. Re-run only cap-hitting tasks at a higher cap. About 0.5 GPU-h.
- 5.3: Replace "gold tools + k distractors" with shortlister `--top-k-tools` ∈ {32, 64, 128} on dev capabilities 2–4, chosen after recall@k. Keep the gold+distractor design only as a labeled diagnostic, if at all. About 1.7 GPU-h.
- New 5.4: B1 strictness, chosen offline on dev traces from the precision-recall curve, with the false-alarm ceiling set before results are seen. About 0 GPU-h.
- Stretch list: add located vs generic recovery feedback, a second recovery step, gpt-oss-20b and one prompt paraphrase (if-time). Mark temperature, tool-description edits, serving parameters and DeepSeek as skip, with the reasons from §4.

**WS8 (freeze and paired experiments)**
- 8.1: The freeze manifest records:
  - the binarization rule;
  - the primary family (P1, P2) and Holm;
  - the B1 strictness setting;
  - the B2 trigger rate observed on dev;
  - the random seed for the random-trigger control.
- 8.2: Run B0 once per repeat on the frozen set. Compute B1 by replaying the checks on the saved B0 trajectories. Run B2 by resuming only flagged trajectories for one recovery step. Repeat 3 times.
- 8.2: Add the random-trigger control. Apply the same recovery step to a random set of tasks with the same count as B1 flags in that repeat, ×3. This is P2.
- 8.3: Report fixed/broken counts, recovery fix and break rates for the verifier vs random trigger, pass^1–3, the cost-accuracy Pareto plot, and the judge-audit error rates per system.

**WS10 (compute)**
- 10.2: After the 29 Oct run, record measured effective sec/task, tokens per task and concurrency. Recompute the §6 table (`research-src/budget_calc.py`) and replace all ASSUMPTION values.
- 10.2: Projected need, central scenario: core ≈ 59 GPU-h (~$152); core + if-time ≈ 68 GPU-h (~$175); with the conditional gated-test run ≈ 91 GPU-h (~$235). Pessimistic all-tiers ≈ 140 GPU-h (~$362).
- 10.3 (risk register): New row. Trigger: measured sec/task > 30 s. Response: cut frozen repeats from 3 to 2, then drop if-time items. Never drop the random-trigger control or B0/B2 pairing.
- 10.3 (risk register): New row. Trigger: the evaluator judge is the same model as the agent. Response: the M17 human audit. Owner: Thomas.
