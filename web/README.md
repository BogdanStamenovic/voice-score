# voice-score-lite (browser fallback)

`voice-score-lite.mjs` is the in-browser fallback for the voice-score service: the same
SwiftF0 model (`swift-f0.onnx`, 135 KB) on onnxruntime-web, and a line-for-line port of
`voice_score/metrics.py`, so a grade computed in the browser matches the server's.

## What parity means here

`test/parity.mjs` checks, on 20 fixtures (11 synthetic incl. 4 V-006 glides with tempo drift, 9 real-singing excerpts from vocadito):

| Check | Result (web-v0.2.0, 2026-11-10) |
|---|---|
| Metrics on the Python contour (every field of `notes` and `summary`) | identical within rounding (tolerance 0.11 on 1-decimal fields) |
| SwiftF0 contour, onnxruntime-node vs Python onnxruntime, same 16 kHz PCM | voicing agreement 1.0000, max pitch difference 0.000 cents |
| End-to-end `notes_passed` | identical |

The comparator is mutation-tested: changing the onset trim from 100 to 120 ms produces 120
mismatches. What the test does **not** cover: browser resampling. In the browser,
`decodeToMono16k` resamples with `OfflineAudioContext`, not soxr, so contours differ
slightly from the server's for the same upload.

## Use (pin a version)

Vendor a pinned copy from a tag, never `main`:

```bash
git -C ~/data/voice-score show web-v0.2.0:web/voice-score-lite.mjs > vendor/voice-score-lite.mjs
git -C ~/data/voice-score show web-v0.2.0:web/swift-f0.onnx > public/voice-score/swift-f0.onnx
# or https://raw.githubusercontent.com/BogdanStamenovic/voice-score/web-v0.2.0/web/voice-score-lite.mjs
```

```js
import * as ort from "onnxruntime-web";
import { createAnalyzer, decodeToMono16k } from "./vendor/voice-score-lite.mjs";

const vs = await createAnalyzer({ ort, modelUrl: "/voice-score/swift-f0.onnx" });
const pcm = await decodeToMono16k(recordingBlob);       // mono Float32Array, 16 kHz
const result = await vs.analyze(pcm, { targets: [{ note: "C4", beats: 2 }], tempo_bpm: 80 });
```

`result` has the same shape as `POST /analyze` (see the top-level README), with
`tracker: "swiftf0-web"`. Errors are `VoiceScoreError` with `.status` mirroring the HTTP
codes (400 bad input, 413 too long, 422 nothing voiced).

`ort` is passed in rather than imported so the file has no dependencies and works with
whichever onnxruntime-web build the app bundles.

## Test

```bash
npm install                                  # onnxruntime-node, dev only (~720 MB)
../.venv/bin/python test/make-fixtures.py    # from web/, needs the Python package + vocadito
npm test
```

## Limitations

- Only SwiftF0. RMVPE/FCPE are not available in the browser.
- Single-threaded WASM by default; tracking a 60 s recording takes noticeably longer than
  on the server (measured in Node: 4-40 ms for 1-12 s of audio).
- `decodeToMono16k` needs `AudioContext` (browser only). In Node pass a Float32Array.
- Licence: this file MIT; `swift-f0.onnx` MIT (Lars Nieradzik, `LICENSE-swift-f0`).
