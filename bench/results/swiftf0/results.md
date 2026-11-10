| tracker | RTF | synth-breathy RPA | synth-clean RPA | synth-high RPA | synth-low RPA | synth-mid RPA | synth-snr10 RPA | synth-snr20 RPA | synth-snr5 RPA | vocadito-clean RPA | vocadito-pink10 RPA |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| swiftf0 | 0.0090 | 0.986 | 0.987 | 0.979 | 0.985 | 0.992 | 0.986 | 0.985 | 0.982 | 0.971 | 0.969 |

| tracker | group | OA | RPA | RCA | VR | VFA | MAE c | P95 c | note MAE c | notes <=10c | notes <=25c |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| swiftf0 | synth-breathy | 0.986 | 0.986 | 0.986 | 0.992 | 0.013 | 2.5 | 7.4 | - | - | - |
| swiftf0 | synth-clean | 0.987 | 0.987 | 0.987 | 0.992 | 0.015 | 2.7 | 6.7 | - | - | - |
| swiftf0 | synth-high | 0.977 | 0.979 | 0.985 | 0.992 | 0.031 | 2.8 | 7.4 | - | - | - |
| swiftf0 | synth-low | 0.985 | 0.985 | 0.985 | 0.993 | 0.014 | 2.0 | 6.6 | - | - | - |
| swiftf0 | synth-mid | 0.984 | 0.992 | 0.992 | 0.997 | 0.042 | 2.2 | 6.8 | - | - | - |
| swiftf0 | synth-snr10 | 0.980 | 0.986 | 0.989 | 0.997 | 0.042 | 2.4 | 6.7 | - | - | - |
| swiftf0 | synth-snr20 | 0.986 | 0.985 | 0.985 | 0.991 | 0.011 | 2.1 | 6.4 | - | - | - |
| swiftf0 | synth-snr5 | 0.972 | 0.982 | 0.989 | 0.999 | 0.063 | 2.7 | 7.0 | - | - | - |
| swiftf0 | vocadito-clean | 0.935 | 0.971 | 0.972 | 0.984 | 0.131 | 3.8 | 22.8 | 2.7 | 0.937 | 0.992 |
| swiftf0 | vocadito-pink10 | 0.937 | 0.969 | 0.970 | 0.982 | 0.120 | 4.4 | 23.2 | 2.7 | 0.931 | 0.990 |

Voicing threshold tuned for OA on odd vocadito tracks, scored on even tracks:

| tracker | group | threshold | OA | RPA | VFA | note MAE c | notes <=25c |
|---|---|---|---:|---:|---:|---:|---:|
| swiftf0 | vocadito-clean | default 0.5 | 0.930 | 0.965 | 0.143 | 2.8 | 0.990 |
| swiftf0 | vocadito-clean | tuned 0.678 | 0.936 | 0.950 | 0.094 | 2.8 | 0.989 |
| swiftf0 | vocadito-pink10 | default 0.5 | 0.934 | 0.964 | 0.129 | 2.8 | 0.986 |
| swiftf0 | vocadito-pink10 | tuned 0.678 | 0.941 | 0.952 | 0.083 | 2.7 | 0.984 |
