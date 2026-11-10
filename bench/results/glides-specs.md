Pass rate of V-006 renditions under alternative lesson specs (trainer gradeSing formula; the landing gate multiplies a note's score by min(1, landed_ratio / gate); pass_cents = tolerance).

| tolerance c | pass | landing gate | correct | long-last | wrong-top-2st | never-lands | drop-last |
|---:|---:|---|---:|---:|---:|---:|---:|
| 100 | 0.6 | - | 1.000 | 1.000 | 1.000 | 1.000 | 0.667 |
| 75 | 0.75 | - | 1.000 | 1.000 | 0.398 | 1.000 | 0.333 |
| 100 | 0.75 | - | 1.000 | 1.000 | 0.917 | 1.000 | 0.333 |
| 100 | 0.75 | landed_ratio >= 0.4 | 1.000 | 1.000 | 0.333 | 1.000 | 0.333 |
| 100 | 0.75 | landed_ratio >= 0.5 | 1.000 | 1.000 | 0.333 | 1.000 | 0.333 |
| 75 | 0.75 | landed_ratio >= 0.5 | 1.000 | 1.000 | 0.333 | 0.889 | 0.333 |
