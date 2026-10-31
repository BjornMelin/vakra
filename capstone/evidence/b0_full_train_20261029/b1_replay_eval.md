# B1 verdicts vs gold: b1_replay_b0full_v2

Items without a B1 verdict: 0; excluded (reference-wrong): 0

| capability | b1_path | n | accept_correct | accept_wrong | reject_correct | reject_wrong | insufficient_correct | insufficient_wrong | false_alarm_rate | catch_rate | insufficient_rate | latency_p50_s | judge_calls |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| all | all | 4428 | 2081 | 1246 | 174 | 497 | 44 | 386 | 0.0757 | 0.2334 | 0.0971 | 0.000335 | 363 |
| all | deterministic | 4065 | 1965 | 1143 | 168 | 431 | 38 | 320 | 0.0774 | 0.2276 | 0.0881 | 0.000282 | 0 |
| all | judge | 363 | 116 | 103 | 6 | 66 | 6 | 66 | 0.0469 | 0.2809 | 0.1983 | 2.834279 | 363 |
| 1 | all | 1324 | 657 | 420 | 19 | 102 | 0 | 126 | 0.0281 | 0.1574 | 0.0952 | 0.001579 | 66 |
| 1 | deterministic | 1258 | 626 | 401 | 18 | 89 | 0 | 124 | 0.028 | 0.145 | 0.0986 | 0.0015 | 0 |
| 1 | judge | 66 | 31 | 19 | 1 | 13 | 0 | 2 | 0.0312 | 0.3824 | 0.0303 | 3.144115 | 66 |
| 2 | all | 1860 | 1016 | 428 | 103 | 207 | 2 | 104 | 0.0919 | 0.2801 | 0.057 | 0.000215 | 206 |
| 2 | deterministic | 1654 | 951 | 372 | 98 | 173 | 0 | 60 | 0.0934 | 0.286 | 0.0363 | 0.000199 | 0 |
| 2 | judge | 206 | 65 | 56 | 5 | 34 | 2 | 44 | 0.0694 | 0.2537 | 0.2233 | 2.640879 | 206 |
| 3 | all | 346 | 96 | 146 | 20 | 69 | 0 | 15 | 0.1724 | 0.3 | 0.0434 | 0.000325 | 21 |
| 3 | deterministic | 325 | 87 | 139 | 20 | 65 | 0 | 14 | 0.1869 | 0.2982 | 0.0431 | 0.000315 | 0 |
| 3 | judge | 21 | 9 | 7 | 0 | 4 | 0 | 1 | 0.0 | 0.3333 | 0.0476 | 3.258652 | 21 |
| 4 | all | 898 | 312 | 252 | 32 | 119 | 42 | 141 | 0.0829 | 0.2324 | 0.2038 | 0.000204 | 70 |
| 4 | deterministic | 828 | 301 | 231 | 32 | 104 | 38 | 122 | 0.0863 | 0.2276 | 0.1932 | 0.000191 | 0 |
| 4 | judge | 70 | 11 | 21 | 0 | 15 | 4 | 19 | 0.0 | 0.2727 | 0.3286 | 3.437996 | 70 |

## Catch rate by error label (labels computed without B1)

| headline | subreason | n_wrong | rejected | insufficient | accepted | catch_rate | catch_rate_deterministic | catch_rate_judge |
|---|---|---|---|---|---|---|---|---|
| not_supported | answer_not_in_output | 339 | 103 | 8 | 228 | 0.3038 | 0.2478 | 0.056 |
| not_supported | no_answer | 320 | 0 | 320 | 0 | 0.0 | 0.0 | 0.0 |
| not_supported | wrong_arguments | 212 | 46 | 2 | 164 | 0.217 | 0.1934 | 0.0236 |
| not_supported | wrong_tool | 1256 | 347 | 56 | 853 | 0.2763 | 0.2436 | 0.0326 |
| supported_but_wrong | wrong_reasoning | 2 | 1 | 0 | 1 | 0.5 | 0.0 | 0.5 |

