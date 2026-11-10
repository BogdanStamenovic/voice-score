| tracker | RTF | synth-breathy RPA | synth-clean RPA | synth-high RPA | synth-low RPA | synth-mid RPA | synth-snr10 RPA | synth-snr20 RPA | synth-snr5 RPA | vocadito-clean RPA | vocadito-pink10 RPA |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| rmvpe | 0.0389 | 0.946 | 0.976 | 0.862 | 0.999 | 1.000 | 0.944 | 0.959 | 0.944 | 0.984 | 0.983 |

| tracker | group | OA | RPA | RCA | VR | VFA | MAE c | P95 c | note MAE c | notes <=10c | notes <=25c |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| rmvpe | synth-breathy | 0.895 | 0.946 | 0.950 | 0.962 | 0.283 | 1.2 | 4.0 | - | - | - |
| rmvpe | synth-clean | 0.932 | 0.976 | 0.976 | 0.978 | 0.219 | 0.9 | 4.9 | - | - | - |
| rmvpe | synth-high | 0.855 | 0.862 | 0.918 | 0.945 | 0.171 | 1.5 | 1199.5 | - | - | - |
| rmvpe | synth-low | 0.900 | 0.999 | 0.999 | 1.000 | 0.448 | 1.1 | 3.1 | - | - | - |
| rmvpe | synth-mid | 0.955 | 1.000 | 1.000 | 1.000 | 0.204 | 1.1 | 4.0 | - | - | - |
| rmvpe | synth-snr10 | 0.893 | 0.944 | 0.984 | 0.995 | 0.285 | 1.2 | 4.1 | - | - | - |
| rmvpe | synth-snr20 | 0.905 | 0.959 | 0.963 | 0.973 | 0.282 | 1.1 | 3.6 | - | - | - |
| rmvpe | synth-snr5 | 0.889 | 0.944 | 0.990 | 1.000 | 0.302 | 1.4 | 4.8 | - | - | - |
| rmvpe | vocadito-clean | 0.885 | 0.984 | 0.985 | 0.999 | 0.307 | 2.7 | 23.1 | 1.8 | 0.940 | 0.990 |
| rmvpe | vocadito-pink10 | 0.881 | 0.983 | 0.984 | 0.999 | 0.316 | 3.1 | 22.4 | 1.8 | 0.951 | 0.990 |

Voicing threshold tuned for OA on odd vocadito tracks, scored on even tracks:

| tracker | group | threshold | OA | RPA | VFA | note MAE c | notes <=25c |
|---|---|---|---:|---:|---:|---:|---:|
| rmvpe | vocadito-clean | default 0.03 | 0.881 | 0.981 | 0.317 | 1.8 | 0.989 |
| rmvpe | vocadito-clean | tuned 0.687 | 0.944 | 0.945 | 0.060 | 1.8 | 0.979 |
| rmvpe | vocadito-pink10 | default 0.03 | 0.872 | 0.980 | 0.341 | 1.9 | 0.989 |
| rmvpe | vocadito-pink10 | tuned 0.687 | 0.945 | 0.939 | 0.046 | 1.9 | 0.982 |
