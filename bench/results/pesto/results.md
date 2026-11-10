| tracker | RTF | synth-breathy RPA | synth-clean RPA | synth-high RPA | synth-low RPA | synth-mid RPA | synth-snr10 RPA | synth-snr20 RPA | synth-snr5 RPA | vocadito-clean RPA | vocadito-pink10 RPA |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| pesto | 0.0856 | 0.927 | 0.959 | 0.823 | 0.990 | 1.000 | 0.930 | 0.954 | 0.919 | 0.774 | 0.739 |

| tracker | group | OA | RPA | RCA | VR | VFA | MAE c | P95 c | note MAE c | notes <=10c | notes <=25c |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| pesto | synth-breathy | 0.939 | 0.927 | 0.927 | 0.929 | 0.018 | 2.5 | 13.6 | - | - | - |
| pesto | synth-clean | 0.963 | 0.959 | 0.959 | 0.961 | 0.022 | 2.5 | 13.8 | - | - | - |
| pesto | synth-high | 0.854 | 0.823 | 0.825 | 0.831 | 0.041 | 2.5 | 17.1 | - | - | - |
| pesto | synth-low | 0.992 | 0.990 | 0.990 | 0.990 | 0.000 | 2.7 | 12.4 | - | - | - |
| pesto | synth-mid | 0.996 | 1.000 | 1.000 | 1.000 | 0.016 | 2.1 | 13.6 | - | - | - |
| pesto | synth-snr10 | 0.942 | 0.930 | 0.930 | 0.933 | 0.018 | 2.5 | 13.6 | - | - | - |
| pesto | synth-snr20 | 0.960 | 0.954 | 0.954 | 0.956 | 0.020 | 2.5 | 12.8 | - | - | - |
| pesto | synth-snr5 | 0.933 | 0.919 | 0.921 | 0.924 | 0.018 | 2.6 | 17.8 | - | - | - |
| pesto | vocadito-clean | 0.824 | 0.774 | 0.778 | 0.784 | 0.079 | 8.2 | 23.4 | 7.2 | 0.572 | 0.823 |
| pesto | vocadito-pink10 | 0.804 | 0.739 | 0.746 | 0.754 | 0.066 | 8.1 | 23.6 | 7.3 | 0.557 | 0.796 |

Voicing threshold tuned for OA on odd vocadito tracks, scored on even tracks:

| tracker | group | threshold | OA | RPA | VFA | note MAE c | notes <=25c |
|---|---|---|---:|---:|---:|---:|---:|
| pesto | vocadito-clean | default 0.5 | 0.880 | 0.856 | 0.103 | 6.8 | 0.914 |
| pesto | vocadito-clean | tuned 0.11 | 0.904 | 0.978 | 0.251 | 6.7 | 0.987 |
| pesto | vocadito-pink10 | default 0.5 | 0.866 | 0.827 | 0.086 | 6.7 | 0.898 |
| pesto | vocadito-pink10 | tuned 0.11 | 0.908 | 0.941 | 0.163 | 6.5 | 0.976 |
