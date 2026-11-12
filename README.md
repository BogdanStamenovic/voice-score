# voice-score

A local HTTP service that analyzes a singing recording: it tracks the pitch (f0) and reports
cents error against target notes, pitch stability, sustain, range and vibrato. It is the
voice-grading backend of music-trainer (`~/data/music-trainer` on archserver),
listens on `127.0.0.1:3311`, and has no auth (localhost only).

It answers one question, *what did this voice recording actually do*. Deciding whether that
is good enough for a lesson is the trainer's job.

## How it works

```
upload (wav/flac/ogg natively; webm/opus, m4a, mp3 via ffmpeg)
  -> mono float32
  -> pitch tracker (SwiftF0 by default: 135 KB ONNX model, onnxruntime, 16 ms frames)
  -> f0 contour (Hz, NaN where unvoiced)
  -> note windows (from targets: times, beats+tempo, or segmentation + alignment)
  -> per-note metrics + summary
```

Per note:

| Field | Meaning |
|---|---|
| `cents_error` | median of (sung - target) in cents over the steady part (first 100 ms attack excluded); + = sharp |
| `abs_cents_mean`, `within_50c`, `within_25c` | spread of the per-frame error |
| `pass` | `abs(cents_error) <= pass_cents` (default 50) |
| `stability_cents_sd` | SD of the pitch after a 0.25 s moving average: slow wander, **vibrato excluded** |
| `raw_cents_sd` | SD of the raw pitch, vibrato and jitter included |
| `drift_cents` | last third minus first third of the note (smoothed) |
| `sustain_s` | longest stretch where the smoothed pitch stays within `pass_cents` of the target |
| `landed_ratio` | `sustain_s` as a share of the note window: did the voice land on the note and stay (informational, see Glides) |
| `onset_s` | time from the window start to the first voiced frame |
| `octave_offset` | octaves between target and sung note; with `octave_agnostic` (default) the note is scored against the nearest octave |
| `vibrato` | `rate_hz`, `extent_cents` (half peak-to-peak), `periodicity`, `present` (periodicity >= 0.5 and extent >= 15 c, rate searched in 3-9 Hz) |
| `missing` | true when nothing was sung in the window |

Why stability is smoothed: a 40-cent vibrato has a raw SD of ~28 cents, the same as an
untrained singer wobbling. Measured on a synthetic 5.5 Hz / 40 c vibrato with no drift:
raw SD 28 c, smoothed SD 6 c, vibrato reported as 5.49 Hz / 38 c. Vibrato is reported as
vibrato, not penalised as instability.

Summary: voiced seconds, `tempo_ratio` (beats targets only), range (2nd-98th percentile of the smoothed pitch inside detected
notes, so a single glitch frame does not set a record), notes passed, mean |cents error|,
median stability, longest sustain, vibrato across notes.

How note windows are found:

| Targets given as | Window |
|---|---|
| none | notes segmented from the contour (pitch moves > 0.75 semitone for > 60 ms) |
| one target, no times | the whole voiced span |
| several targets, no times | segmented notes aligned to targets in order (monotonic DP; several segments may merge into one target; a skipped target is reported `missing`) |
| `beats` + `tempo_bpm` | laid out from the first voiced onset at the singer's own tempo: one global tempo factor (0.6-1.6x written) is fitted to the sung pitch and reported as `summary.tempo_ratio` (>1 = slower than written). `{"rest": true, "beats": n}` advances time |
| `start`/`end` seconds | used as given |

## HTTP API

Agreed with the music-trainer builder on 2026-11-10; stable within 0.x unless both sides agree.

`GET /health`

```json
{"ok": true, "version": "0.2.1", "trackers": ["swiftf0", "rmvpe"], "default_tracker": "swiftf0"}
```

`POST /analyze`, multipart/form-data:

- `audio`: the recording file. Up to 60 s and 20 MB.
- `params`: JSON string, all optional:

```json
{
  "targets": [{"note": "C4", "beats": 2}, {"midi": 62, "beats": 2}, {"rest": true, "beats": 1}],
  "tempo_bpm": 80,
  "a4_hz": 440,
  "pass_cents": 50,
  "octave_agnostic": true,
  "tracker": "swiftf0",
  "contour": true
}
```

Targets may also be bare strings (`"C4"`) or MIDI numbers (`60`). Notes: `C4` = MIDI 60;
sharps `#`, flats `b`.

Response for a synthetic C4-D4-E4 phrase sung 20 cents flat with a 5.5 Hz / 40 c vibrato and
0.15 s breaths between notes, hence `tempo_ratio` 1.08 (`targets` with beats, `tempo_bpm` 120,
`contour` false; first note shown):

```json
{
  "version": "0.2.0", "tracker": "swiftf0", "a4_hz": 440.0, "pass_cents": 50.0,
  "octave_agnostic": true, "tempo_bpm": 120.0, "duration_s": 4.55, "hop_s": 0.016, "tracker_ms": 16.4,
  "notes": [{"index": 0, "target_note": "C4", "target_midi": 60, "start": 0.304, "end": 1.376,
             "voiced_ratio": 1.0, "onset_s": 0.0, "sung_note": "C4", "sung_hz": 257.72,
             "cents_error": -26.0, "abs_cents_mean": 30.2, "within_50c": 0.754, "within_25c": 0.474,
             "stability_cents_sd": 5.7, "raw_cents_sd": 29.0, "drift_cents": -1.2, "sustain_s": 1.01,
             "landed_ratio": 0.94, "octave_offset": 0,
             "vibrato": {"present": true, "rate_hz": 5.49, "extent_cents": 37.6, "periodicity": 0.7},
             "pass": true}],
  "summary": {"voiced_s": 3.5,
              "range": {"low_note": "C4", "high_note": "E4", "low_hz": 257.0, "high_hz": 327.2, "semitones": 4.2},
              "notes_targeted": 3, "tempo_ratio": 1.08, "notes_passed": 3, "mean_abs_cents": 23.2,
              "stability_cents_sd": 5.8, "longest_sustain_s": 1.47,
              "vibrato": {"notes_with_vibrato": 3, "rate_hz": 5.49, "extent_cents": 39.5}},
  "labels": {},
  "warnings": []
}
```

With `contour` true (the default) the response also carries
`"contour": {"t": [...], "f0_hz": [... null where unvoiced], "confidence": [...]}`.

`warnings` (human-readable, informational; nothing in the response depends on them):

| Warning | Fires when | Why that threshold |
|---|---|---|
| `clipping` | > 0.1% of samples at full scale | clipped peaks distort the harmonics |
| `low recording level` | median peak of voiced 16 ms frames < -45 dBFS | SwiftF0 treats frames peaking below -60 dBFS as silence; on real takes, grades began shifting 10-15 dB above that gate |
| `noisy recording` | voiced energy < 6 dB above the median unvoiced (background) energy | measured takes at 4-5 dB still tracked correctly, so this is a caution, not a failure |
| `sung in a different octave` | `octave_agnostic` folded at least one note | so the trainer can tell the singer |

| Status | When |
|---|---|
| 200 | analyzed |
| 400 | undecodable audio, bad params, unknown/uninstalled tracker, `beats` without `tempo_bpm` |
| 413 | longer than 60 s or larger than 20 MB |
| 422 | nothing voiced (the trainer shows "no voice detected, try again", not a fail) |

`labels` is empty today. Planned: `falsetto` and `distortion_present`, each carrying
`"confidence": "low"`. There is no distortion *safety* score and there will not be one: no
published method measures that (survey 2026-11-10).

## Browser fallback

`web/voice-score-lite.mjs` runs the same SwiftF0 model on onnxruntime-web with a port of the
same metrics; the trainer vendors it from a pinned `web-v*` tag. Parity with this service is
tested on 20 fixtures. See [web/README.md](web/README.md).

## Glides (V-006) and tempo drift

music-trainer's V-006 sends slides between chord tones (1-5-1, 1-3-5-3-1, 5-1) as beat-timed
phrases at 60 bpm with `pass_cents` 100 and passes the exercise at a mean note score of 0.6.
`bench/glides.py` renders 594 sung takes of those phrases (glide 0.15-0.8 s, placed before,
across or after the beat; singer's tempo 0.8-1.25x written; vibrato on/off; 25 dB SNR),
tracks them with SwiftF0 and scores them with the trainer's own formula. Results in
`bench/results/glides-*.md`, 2026-11-10.

Estimate error = mean |reported cents_error - true sung error| on correct takes:

| Phrase | rigid grid (0.1.0) | grid scaled to sung span | **tempo fit (0.2.0)** |
|---|---:|---:|---:|
| 1-5-1, tempo 0.8-1.25x | 35.2 c | 5.8 c | **5.0 c** |
| 1-3-5-3-1, tempo 0.8-1.25x | 70.1 c | 7.4 c | **5.1 c** |
| 5-1, tempo 0.8-1.25x | 8.0 c | 4.7 c | **4.2 c** |
| 1-5-1, last note held 2x | 24.9 c | 135.0 c | **3.2 c** |
| 1-3-5-3-1, last note held 2x | 89.8 c | 103.1 c | **3.6 c** |

The rigid grid was the problem, not the glides: on tempo it misread correct takes by 5.7 c,
at 0.8x by 69 c, at 1.25x by 84 c. Scaling the grid to the sung span broke on a held final
note, which singers do all the time. Fitting one tempo factor to the pitch fixed both; a top
note sung a whole tone flat is still reported as -200 c (estimate error 3-4 c), because the
correctly sung notes pin the timing.

Also tried and rejected: aligning segmented notes to targets ignoring beats (as good on
correct takes, but misread a wrong note in 1-3-5-3-1 by 29 c) and excluding moving frames
from each note's estimate (2 c better on synthetic glides, but on vocadito with annotated
note windows it moved the median disagreement with the annotator from 5.0 to 5.2 c and notes
off by more than 50 c from 25 to 31 of 1970).

What voice-score cannot fix: under the lesson's current spec (tolerance 100, pass 0.6) a top
note sung a whole tone flat passes 100% of the time, because one note at 200 c still scores
0.5. That is a lesson-spec question for the trainer; `bench/results/glides-specs.md` has the
pass rates under alternatives. A slow continuous slide that never settles is not reliably
separable from a correct glide by any measure here: its median sits on the target and it
spends about half of each window within 100 c (`landed_ratio` median 0.64 vs 0.94 for
correct takes, but correct takes go down to 0.76).

## Validation on the trainer's user (2026-11-12)

20 real takes recorded in music-trainer on 2026-11-11 (lessons V-001..V-005; an adult male
voice whose lowest sung notes were around 77 Hz), analyzed in place and not kept. Checks:

| Check | Result |
|---|---|
| SwiftF0 vs RMVPE / FCPE, frames ~an octave apart | 0 of 3979 / 0 of 4612 frames, incl. 351 frames below 100 Hz |
| Sub-octave check against an f0 estimated from 200-1500 Hz harmonics only | 0.2% of 1198 frames below 130 Hz; 0 doubled |
| Odd-harmonic energy at the reported f0 (a halved f0 would lack it) | present on every take; frames with strong energy at f0/2: 3 of 1678 |
| Per-note cents, SwiftF0 vs RMVPE / FCPE | 18 graded notes: median difference 4.1 c, max 14.8 c |
| Voicing: SwiftF0-only voiced time / time both others voiced but SwiftF0 not | 0.43 s / 0.08 s of 77.3 s; the 0.38 s on the quietest take shows real harmonics in the spectrogram |
| Re-analysis vs the stored server result | identical on 20/20 |
| Browser module vs server on the same 16 kHz audio | identical: max 0.00 c over 18 notes, same warnings |
| Recording level vs SwiftF0's -60 dBFS silence gate | voiced frames peak at -37.5 dBFS (median), -46.4 (1st pct); turning the takes down shifted grades from -5 to -10 dB and gave "no voice detected" on 2/20 at -20 dB |

What changed because of it (0.2.1): the old warning fired on whole-file RMS < -50 dBFS, so it
flagged 4 takes that tracked perfectly (voice 22-24 dB over the background) and missed one
whose voice was only 4 dB above it. Replaced by the level-margin and noise warnings above:
on these takes it flags exactly the two noisy ones and, when the takes are turned down
10-20 dB, every take whose grade shifted.

Tried and rejected: peak-normalizing before tracking makes results level-invariant from -30
to +20 dB, but 82% of the voiced frames it adds are not confirmed by RMVPE or FCPE and carry
little harmonic structure (amplified background), and it moved one grade by 14 c.

## Install

```bash
ownbox install voice-score
```

That builds `.venv` (uv, Python 3.13, ~150 MB), writes and enables the systemd user unit
`voice-score.service` (127.0.0.1:3311, `MemoryMax=2G`, `CPUQuota=400%`), starts it and waits
for `/health`. It offers to download the optional RMVPE model (362 MB) to
`/mnt/windows/voice-score-data/models`; without a TTY it skips that and says so.
`ownbox update voice-score` re-syncs the venv, rewrites the unit and restarts;
`ownbox uninstall voice-score` stops and removes the unit and asks before deleting models.
The service is stateless, so updates and rollbacks have no data to migrate.
All of install, update, rollback, update again, uninstall, reinstall were exercised on
archserver on 2026-11-10.

Manual:

```bash
uv sync --extra dev
.venv/bin/voice-score serve            # or: bash scripts/lifecycle.sh setup
```

## Usage

```bash
voice-score serve [--host 127.0.0.1] [--port 3311]
voice-score analyze take.webm --targets C4,D4,E4 [--beats 2,2,3 --tempo 80] [--tracker rmvpe] [--contour]
voice-score analyze take.wav --params '{"targets":["A3"],"pass_cents":25}'
voice-score trackers
voice-score bench --trackers swiftf0,rmvpe --datasets synth,vocadito --out bench/results
bash scripts/lifecycle.sh status
```

stdout carries only the JSON result; warnings and errors go to stderr. Exit codes: 0 ok,
1 analysis failed (bad audio, nothing voiced), 2 usage error.

Environment: `VOICE_SCORE_HOST`, `VOICE_SCORE_PORT`, `VOICE_SCORE_RMVPE` (model path).

## Trackers and benchmark

Five trackers ran head-to-head on identical inputs (`voice-score bench`, harness in
`src/voice_score/bench.py`, raw numbers in `bench/results/`, run 2026-11-10 on archserver,
Ryzen 5 5600, CPU only):

- **synth**: 45 synthetic phrases with exactly known f0. 3 registers (A2-E3, A3-G4, A4-C6)
  x 3 styles (plain, 5.8 Hz / 50 c vibrato, scoops + jitter) x 5 conditions (clean, white
  noise at 20/10/5 dB SNR, breathy).
- **vocadito**: 40 real solo-singing excerpts with annotated f0 and notes (CC BY 4.0,
  [zenodo 5578807](https://zenodo.org/records/5578807)), clean and with pink noise at 10 dB SNR.
  Not redistributed here; the bench downloads nothing, it reads
  `/mnt/windows/voice-score-data/dl/vocadito`.

Metrics: **OA** overall accuracy (frames correctly unvoiced, or voiced and within 50 cents),
**RPA** raw pitch accuracy on annotated-voiced frames, **VFA** voicing false alarm (pitch
reported where the annotation has none), **note error** = |median tracker pitch - median
annotated pitch| per annotated note, i.e. the error a tracker adds to the grade.

### Real singing, voicing threshold tuned per tracker

Each tracker's own default voicing threshold makes the comparison unfair (FCPE's default
voices 33-65% of unvoiced frames). So each threshold was tuned for OA on the 20 odd-numbered
vocadito tracks and scored on the 20 even-numbered ones:

| Tracker | Threshold (default -> tuned) | OA clean | OA +noise | RPA clean | VFA clean | Note error, median | Notes within 25 c |
|---|---|---:|---:|---:|---:|---:|---:|
| RMVPE (ONNX) | 0.03 -> 0.69 | **0.944** | **0.945** | 0.945 | 0.060 | **1.8 c** | 0.979 |
| SwiftF0 | 0.5 -> 0.68 | 0.936 | 0.941 | 0.950 | 0.094 | 2.8 c | 0.989 |
| FCPE | 0.006 -> 0.6 | 0.935 | 0.941 | 0.951 | 0.100 | 2.2 c | 0.982 |
| PESTO | 0.5 -> 0.11 | 0.904 | 0.908 | 0.978 | 0.251 | 6.7 c | 0.987 |
| pYIN | 0.5 -> 0.056 | 0.805 | 0.807 | 0.840 | 0.259 | 5.1 c | 0.913 |

At the defaults as shipped, on the same held-out tracks: SwiftF0 OA 0.930, RMVPE 0.881,
FCPE 0.879, PESTO 0.880, pYIN 0.723.

### Registers and noise (synthetic, default thresholds, RPA)

| Tracker | low A2-E3 | mid A3-G4 | high A4-C6 | clean | 5 dB SNR | breathy |
|---|---:|---:|---:|---:|---:|---:|
| SwiftF0 | 0.985 | 0.992 | 0.979 | 0.987 | 0.982 | 0.986 |
| FCPE | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 |
| RMVPE | 0.999 | 1.000 | **0.862** | 0.976 | 0.944 | 0.946 |
| pYIN | 0.997 | 0.996 | 0.919 | 0.998 | 0.868 | 0.998 |
| PESTO | 0.990 | 1.000 | 0.823 | 0.959 | 0.919 | 0.927 |

RMVPE's high-register loss is octave errors (P95 error 1200 cents). The signals are synthetic
and RMVPE was trained on real voices, so this may overstate the problem, but vocadito has
little material above A4 to check it on.

### Speed and footprint (idle machine, 10 vocadito tracks = 222 s of audio)

| Tracker | Real-time factor | 60 s clip | Model load | Extra install |
|---|---:|---:|---:|---|
| SwiftF0 | 0.0033 | 0.22 s | 0.06 s | none (135 KB model, onnxruntime) |
| FCPE | 0.0067 | 0.51 s | 0.95 s | torch (~760 MB) + torchfcpe |
| RMVPE (ONNX) | 0.022 | 1.50 s | 0.51 s | 362 MB model, no new packages |
| pYIN | 0.027 | 1.55 s | - | librosa + numba/llvmlite (~200 MB) |
| PESTO | 0.029 | 1.93 s | 1.12 s | torch (~760 MB), LGPL |

### Decision: SwiftF0 stays the default

Tuned, RMVPE leads SwiftF0 by 0.4-0.8 points of OA and 1 cent of per-note error. Against a
50-cent pass threshold, a 1-cent difference cannot change a grade. SwiftF0 is the most
accurate tracker at its shipped threshold, holds up in the high register where RMVPE makes
octave errors, is 7x faster than RMVPE with a model 2700x smaller, and is the exact model the
browser fallback runs (parity is tested). FCPE ties SwiftF0 tuned and is perfect on the
synthetic set, but needs torch: a 760 MB dependency for no measurable gain on real singing.

What was adopted from the benchmark: RMVPE, available as the opt-in `"tracker": "rmvpe"` when
its model is present, now uses the tuned threshold 0.69 instead of RVC's 0.03. SwiftF0's
tuned threshold (0.68) was **not** adopted: +0.6 points OA for -1.5 points RPA is inside the
noise of a 20-track tuning set, and it would split server and browser behaviour.

Reproduce:

```bash
uv venv /mnt/offload/voice-score/bench-venv -p 3.13
VIRTUAL_ENV=/mnt/offload/voice-score/bench-venv uv pip install -e '.[bench]' \
    --index-url https://download.pytorch.org/whl/cpu --extra-index-url https://pypi.org/simple \
    --index-strategy unsafe-best-match
bash scripts/fetch-models.sh                 # RMVPE
bench/run-parallel.sh                        # ~20 min; pYIN and FCPE's 12-threshold grid are slowest
/mnt/offload/voice-score/bench-venv/bin/python bench/speed.py
```

## Limitations

- **Metrics are a screen, not a verdict.** On real singing the default tracker's per-note
  error against human annotation has a median of ~3 cents but a long tail (frame-level P95
  ~23 cents); a 50-cent pass threshold absorbs this, a 10-cent one would not.
- **Results depend on recording level near the bottom.** SwiftF0 drops frames whose peak is
  below -60 dBFS. On real takes, grades started shifting when turned down 5-10 dB from a
  typical laptop-mic level and "no voice detected" appeared at -20 dB. The service warns
  (`low recording level`) but does not compensate; normalizing gain was tried and made
  things worse (see Validation).
- **No technique classification.** Chest/head/mix/belt are not detected. Published 10-class
  accuracy is ~66% (VocalSet) with no public weights; not worth grading on.
- **Falsetto and distortion labels do not exist yet** (`labels` is empty).
- **Polyphony is not handled.** Singing over a piano or backing track that is picked up by
  the mic will confuse the tracker; record the voice alone (headphones for the reference).
- **Untimed multi-note alignment can be wrong** when the singer adds or drops many notes;
  a warning is emitted when there are more than twice as many sung segments as targets.
  Use `beats` + `tempo_bpm` for phrases.
- **Octave-agnostic by default.** A man matching a piano C5 an octave down passes; set
  `octave_agnostic: false` for range or register drills where the octave matters.
- **Range is percentile-based** (2nd-98th), so the extreme notes of a very short siren may
  be clipped.
- **Single-user, localhost, no auth, no queue.** Concurrent requests run in FastAPI's
  thread pool.
- Synthetic test signals are additive harmonics with a crude vowel filter; trackers trained
  on real voices can behave differently on them (see RMVPE's high-register octave errors).
