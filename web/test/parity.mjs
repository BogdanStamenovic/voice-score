// Parity test: voice-score-lite.mjs vs the Python service on identical inputs.
// 1. metrics: analyzeContour() on the Python SwiftF0 contour must reproduce the Python
//    metrics (numbers within rounding: 0.11 for 1-decimal fields, 0.0011 for 3-decimal).
// 2. tracker: SwiftF0 on onnxruntime-node vs onnxruntime (Python) on the same PCM:
//    voicing agreement and max |cents| difference on frames voiced in both.
// Fixtures: .venv/bin/python web/test/make-fixtures.py
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import * as ort from "onnxruntime-node";
import { analyzeContour, createAnalyzer, parseTargets } from "../voice-score-lite.mjs";

const here = dirname(fileURLToPath(import.meta.url));
const fx = join(here, "fixtures");
const names = JSON.parse(readFileSync(join(fx, "index.json"), "utf8"));
let failures = 0;
const fail = (msg) => {
  failures++;
  console.error("FAIL " + msg);
};

function compare(a, b, path) {
  if (a === null || b === null || typeof a !== "object" || typeof b !== "object") {
    if (typeof a === "number" && typeof b === "number") {
      const tol = Math.max(Math.abs(b) * 1e-9, Number.isInteger(b) && Number.isInteger(a) ? 0 : 0.11);
      if (Math.abs(a - b) > tol) fail(`${path}: js ${a} != py ${b}`);
    } else if (a !== b) fail(`${path}: js ${JSON.stringify(a)} != py ${JSON.stringify(b)}`);
    return;
  }
  if (Array.isArray(b)) {
    if (!Array.isArray(a) || a.length !== b.length) return fail(`${path}: length ${a?.length} != ${b.length}`);
    b.forEach((v, i) => compare(a[i], v, `${path}[${i}]`));
    return;
  }
  for (const k of Object.keys(b)) compare(a[k], b[k], `${path}.${k}`);
  for (const k of Object.keys(a)) if (!(k in b)) fail(`${path}.${k}: extra key in js`);
}

const vs = await createAnalyzer({ ort, model: readFileSync(join(here, "..", "swift-f0.onnx")) });
for (const name of names) {
  const f = JSON.parse(readFileSync(join(fx, `${name}.json`), "utf8"));
  const p = f.params;
  const opt = { a4_hz: p.a4_hz ?? 440, pass_cents: p.pass_cents ?? 50, octave_agnostic: p.octave_agnostic ?? true, tempo_bpm: p.tempo_bpm ?? null };
  const contour = { t: f.contour.t, f0: f.contour.f0.map((v) => (v === null ? NaN : v)) };
  const before = failures;
  const got = analyzeContour(contour, parseTargets(p.targets), opt);
  compare(got, f.expected, `${name}`);

  const buf = readFileSync(join(fx, `${name}.f32`));
  const pcm = new Float32Array(buf.buffer, buf.byteOffset, buf.byteLength / 4);
  const c = await vs.track(pcm);
  if (c.t.length !== contour.t.length) fail(`${name}: contour length js ${c.t.length} != py ${contour.t.length}`);
  let agree = 0, both = 0, maxCents = 0;
  for (let i = 0; i < Math.min(c.t.length, contour.t.length); i++) {
    const a = Number.isFinite(c.f0[i]), b = Number.isFinite(contour.f0[i]);
    if (a === b) agree++;
    if (a && b) (both++), (maxCents = Math.max(maxCents, Math.abs(1200 * Math.log2(c.f0[i] / contour.f0[i]))));
  }
  const voicingAgree = agree / contour.t.length;
  if (voicingAgree < 0.999 || maxCents > 1) fail(`${name}: tracker voicing agreement ${voicingAgree.toFixed(4)}, max diff ${maxCents.toFixed(3)} c`);
  const full = await vs.analyze(pcm, p);
  const nPass = (r) => r.summary.notes_passed;
  if (nPass(full) !== nPass(f.expected_service)) fail(`${name}: end-to-end notes_passed js ${nPass(full)} != py ${nPass(f.expected_service)}`);
  console.log(`${failures === before ? "ok  " : "FAIL"} ${name.padEnd(22)} notes=${got.notes.length} voicing=${voicingAgree.toFixed(4)} maxdiff=${maxCents.toFixed(3)}c track=${full.tracker_ms}ms`);
}
console.log(failures ? `${failures} mismatches` : `all ${names.length} fixtures match`);
process.exit(failures ? 1 : 0);
