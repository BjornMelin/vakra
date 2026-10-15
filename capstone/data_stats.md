# Public train split: task counts (ibm-research/VAKRA)

| Capability | Domains | Tasks | sales_in_weather tasks |
|---|---|---|---|
| 1 BI APIs | 33 | 1,324 | 0 |
| 2 Dashboard APIs | 40 | 1,860 | **54** |
| 3 Multi-hop reasoning | 28 | 346 | 0 |
| 4 Multi-turn | 36 | 898 | **16** |
| **Total** | | **4,428** | **70** |

Counted from `data/train/capability_*/input/*.json` (one file per domain). 63 SQLite databases in `data/databases/`.
`sales_in_weather` is only in capabilities 2 and 4, not in capability 3 (multi-hop), so the RCA plan needs to account for that.
