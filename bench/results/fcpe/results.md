| tracker | RTF | synth-breathy RPA | synth-clean RPA | synth-high RPA | synth-low RPA | synth-mid RPA | synth-snr10 RPA | synth-snr20 RPA | synth-snr5 RPA | vocadito-clean RPA | vocadito-pink10 RPA |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| fcpe | 0.1910 | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 | 0.989 | 0.981 |

| tracker | group | OA | RPA | RCA | VR | VFA | MAE c | P95 c | note MAE c | notes <=10c | notes <=25c |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| fcpe | synth-breathy | 0.943 | 1.000 | 1.000 | 1.000 | 0.256 | 1.3 | 4.3 | - | - | - |
| fcpe | synth-clean | 0.961 | 1.000 | 1.000 | 1.000 | 0.176 | 0.9 | 4.2 | - | - | - |
| fcpe | synth-high | 0.929 | 1.000 | 1.000 | 1.000 | 0.317 | 2.0 | 7.0 | - | - | - |
| fcpe | synth-low | 0.908 | 1.000 | 1.000 | 1.000 | 0.413 | 1.2 | 3.8 | - | - | - |
| fcpe | synth-mid | 0.954 | 1.000 | 1.000 | 1.000 | 0.205 | 1.3 | 4.0 | - | - | - |
| fcpe | synth-snr10 | 0.916 | 1.000 | 1.000 | 1.000 | 0.375 | 1.5 | 4.0 | - | - | - |
| fcpe | synth-snr20 | 0.934 | 1.000 | 1.000 | 1.000 | 0.298 | 1.1 | 3.6 | - | - | - |
| fcpe | synth-snr5 | 0.899 | 1.000 | 1.000 | 1.000 | 0.454 | 1.7 | 5.9 | - | - | - |
| fcpe | vocadito-clean | 0.881 | 0.989 | 0.990 | 0.999 | 0.328 | 3.3 | 23.0 | 2.0 | 0.934 | 0.988 |
| fcpe | vocadito-pink10 | 0.793 | 0.981 | 0.983 | 0.997 | 0.567 | 3.5 | 24.0 | 2.1 | 0.936 | 0.989 |

Voicing threshold tuned for OA on odd vocadito tracks, scored on even tracks:

| tracker | group | threshold | OA | RPA | VFA | note MAE c | notes <=25c |
|---|---|---|---:|---:|---:|---:|---:|
| fcpe | vocadito-clean | default 0.006 | 0.879 | 0.987 | 0.334 | 2.2 | 0.984 |
| fcpe | vocadito-clean | tuned 0.6 | 0.935 | 0.951 | 0.100 | 2.2 | 0.982 |
| fcpe | vocadito-pink10 | default 0.006 | 0.762 | 0.981 | 0.646 | 2.3 | 0.989 |
| fcpe | vocadito-pink10 | tuned 0.6 | 0.941 | 0.949 | 0.079 | 2.2 | 0.977 |
