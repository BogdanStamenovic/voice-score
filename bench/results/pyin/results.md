| tracker | RTF | synth-breathy RPA | synth-clean RPA | synth-high RPA | synth-low RPA | synth-mid RPA | synth-snr10 RPA | synth-snr20 RPA | synth-snr5 RPA | vocadito-clean RPA | vocadito-pink10 RPA |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| pyin | 0.0456 | 0.998 | 0.998 | 0.919 | 0.997 | 0.996 | 0.992 | 0.998 | 0.868 | 0.892 | 0.879 |

| tracker | group | OA | RPA | RCA | VR | VFA | MAE c | P95 c | note MAE c | notes <=10c | notes <=25c |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| pyin | synth-breathy | 0.889 | 0.998 | 0.998 | 1.000 | 0.487 | 5.0 | 14.8 | - | - | - |
| pyin | synth-clean | 0.882 | 0.998 | 0.998 | 1.000 | 0.523 | 5.0 | 12.1 | - | - | - |
| pyin | synth-high | 0.844 | 0.919 | 0.919 | 0.925 | 0.417 | 5.5 | 16.0 | - | - | - |
| pyin | synth-low | 0.882 | 0.997 | 0.997 | 1.000 | 0.517 | 5.0 | 11.0 | - | - | - |
| pyin | synth-mid | 0.880 | 0.996 | 0.996 | 1.000 | 0.524 | 5.0 | 12.1 | - | - | - |
| pyin | synth-snr10 | 0.889 | 0.992 | 0.992 | 0.994 | 0.471 | 5.0 | 15.0 | - | - | - |
| pyin | synth-snr20 | 0.884 | 0.998 | 0.998 | 1.000 | 0.511 | 5.0 | 11.7 | - | - | - |
| pyin | synth-snr5 | 0.800 | 0.868 | 0.868 | 0.880 | 0.439 | 7.4 | 29.8 | - | - | - |
| pyin | vocadito-clean | 0.737 | 0.892 | 0.894 | 0.991 | 0.542 | 11.8 | 75.2 | 4.9 | 0.726 | 0.924 |
| pyin | vocadito-pink10 | 0.764 | 0.879 | 0.881 | 0.980 | 0.439 | 12.3 | 76.2 | 5.6 | 0.706 | 0.915 |

Voicing threshold tuned for OA on odd vocadito tracks, scored on even tracks:

| tracker | group | threshold | OA | RPA | VFA | note MAE c | notes <=25c |
|---|---|---|---:|---:|---:|---:|---:|
| pyin | vocadito-clean | default 0.5 | 0.723 | 0.882 | 0.569 | 5.2 | 0.914 |
| pyin | vocadito-clean | tuned 0.0561 | 0.805 | 0.840 | 0.259 | 5.1 | 0.913 |
| pyin | vocadito-pink10 | default 0.5 | 0.756 | 0.876 | 0.470 | 5.6 | 0.913 |
| pyin | vocadito-pink10 | tuned 0.0561 | 0.807 | 0.750 | 0.087 | 5.3 | 0.880 |
