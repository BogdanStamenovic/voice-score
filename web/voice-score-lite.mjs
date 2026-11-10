// voice-score-lite: in-browser fallback for the voice-score service.
//
// Runs the same SwiftF0 ONNX model (135 KB, MIT, github.com/lars76/swift-f0) through
// onnxruntime-web and computes the same metrics as voice_score/metrics.py, so a grade
// computed here matches the server's for the same contour (checked by test/parity.mjs).
// Port of voice_score 0.2.0; keep the two in lockstep (VERSION below).
//
// The caller supplies onnxruntime (`import * as ort from "onnxruntime-web"`) so this file
// has no dependencies and can be vendored as-is.
//
//   const vs = await createAnalyzer({ ort, modelUrl: "/voice-score/swift-f0.onnx" });
//   const pcm = await decodeToMono16k(blob);           // browser only
//   const result = await vs.analyze(pcm, { targets: [{ note: "C4" }] });
//
// `result` has the same shape as POST /analyze on the server, minus server-only fields.

export const VERSION = "0.2.0";

const SR = 16000;
const HOP = 256;
const FRAME_PERIOD = HOP / SR;
const LOOKAHEAD_FRAMES = 10;
const LEFT_FRAMES = 11;
const WINDOW_FRAMES = 1875;
const SILENCE_PEAK = 1e-3;
const FMIN = 50.0;
const FMAX = 2000.0;

const NOTE_NAMES = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"];
const PC = { C: 0, D: 2, E: 4, F: 5, G: 7, A: 9, B: 11 };
const GAP_BRIDGE_S = 0.04;
const MIN_NOTE_S = 0.1;
const ONSET_TRIM_S = 0.1;
const SPLIT_SEMITONES = 0.75;
const SPLIT_HOLD_S = 0.06;
const SMOOTH_S = 0.25;

export class VoiceScoreError extends Error {
  constructor(message, status = 400) {
    super(message);
    this.status = status; // same meaning as the server's HTTP status (422 = nothing voiced)
  }
}

// ---------------------------------------------------------------- numeric helpers

// Python's round(x, nd) on the shortest repr; avoids 1.005 -> 1.0 style drift from x*10^nd.
function r(x, nd = 1) {
  if (x === null || x === undefined || !Number.isFinite(x)) return null;
  return Number(Math.round(Number(x + "e" + nd)) + "e-" + nd);
}
const pyRound = (x) => {
  // Python 3 round(): ties to even
  const f = Math.floor(x);
  const d = x - f;
  if (d > 0.5) return f + 1;
  if (d < 0.5) return f;
  return f % 2 === 0 ? f : f + 1;
};
function median(a) {
  const s = Float64Array.from(a).sort();
  const n = s.length;
  if (n === 0) return NaN;
  return n % 2 ? s[(n - 1) / 2] : (s[n / 2 - 1] + s[n / 2]) / 2;
}
function nanmedian(a) {
  return median(Array.from(a).filter(Number.isFinite));
}
function mean(a) {
  let s = 0;
  for (const v of a) s += v;
  return s / a.length;
}
function std(a) {
  const m = mean(a);
  let s = 0;
  for (const v of a) s += (v - m) ** 2;
  return Math.sqrt(s / a.length);
}
function percentile(a, q) {
  const s = Float64Array.from(a).sort();
  const pos = ((s.length - 1) * q) / 100;
  const lo = Math.floor(pos);
  const hi = Math.min(lo + 1, s.length - 1);
  return s[lo] + (s[hi] - s[lo]) * (pos - lo);
}

export function hzToMidi(hz, a4 = 440) {
  return 69 + 12 * Math.log2(hz / a4);
}
export function midiToHz(m, a4 = 440) {
  return a4 * 2 ** ((m - 69) / 12);
}
export function noteToMidi(name) {
  const m = /^\s*([A-Ga-g])([#b♯♭]?)(-?\d+)\s*$/.exec(String(name));
  if (!m) throw new VoiceScoreError(`bad note name '${name}' (expected e.g. C4, F#3, Bb2)`);
  const acc = m[2] === "#" || m[2] === "♯" ? 1 : m[2] === "b" || m[2] === "♭" ? -1 : 0;
  return 12 * (parseInt(m[3], 10) + 1) + PC[m[1].toUpperCase()] + acc;
}
export function midiToNote(m) {
  const n = pyRound(m);
  return `${NOTE_NAMES[((n % 12) + 12) % 12]}${Math.floor(n / 12) - 1}`;
}

function runs(mask) {
  const out = [];
  let s = -1;
  for (let i = 0; i <= mask.length; i++) {
    const v = i < mask.length && mask[i];
    if (v && s < 0) s = i;
    else if (!v && s >= 0) {
      out.push([s, i]);
      s = -1;
    }
  }
  return out;
}

function bridgedVoicing(voiced, hop) {
  const out = Array.from(voiced);
  const maxGap = hop > 0 ? Math.max(1, pyRound(GAP_BRIDGE_S / hop)) : 1;
  for (const [s, e] of runs(voiced.map((v) => !v))) {
    if (s > 0 && e < voiced.length && e - s <= maxGap) for (let i = s; i < e; i++) out[i] = true;
  }
  return out;
}

// ---------------------------------------------------------------- contour

function contourHop(t) {
  if (t.length < 2) return 0;
  const d = [];
  for (let i = 1; i < t.length; i++) d.push(t[i] - t[i - 1]);
  return median(d);
}

function voicedSpans(c, minS = MIN_NOTE_S) {
  const hop = c.hop || 0.01;
  const v = bridgedVoicing(c.f0.map(Number.isFinite), hop);
  return runs(v).filter(([s, e]) => (e - s) * hop >= minS);
}

function interpMidi(c, a4) {
  const m = c.f0.map((f) => (Number.isFinite(f) ? hzToMidi(f, a4) : NaN));
  const good = m.map(Number.isFinite);
  const goodIdx = [];
  good.forEach((g, i) => g && goodIdx.push(i));
  if (goodIdx.length >= 2) {
    const fill = bridgedVoicing(good, c.hop || 0.01).map((b, i) => b && !good[i]);
    for (let i = 0; i < m.length; i++) {
      if (!fill[i]) continue;
      // np.interp over the good samples (fill frames always lie between two good frames)
      let k = 0;
      while (k < goodIdx.length - 1 && goodIdx[k + 1] < i) k++;
      const x0 = goodIdx[k];
      const x1 = goodIdx[Math.min(k + 1, goodIdx.length - 1)];
      m[i] = x1 === x0 ? m[x0] : m[x0] + ((m[x1] - m[x0]) * (i - x0)) / (x1 - x0);
    }
  }
  return m;
}

function segmentNotes(c, a4) {
  const hop = c.hop || 0.01;
  const m = interpMidi(c, a4);
  const hold = Math.max(2, pyRound(SPLIT_HOLD_S / hop));
  const out = [];
  for (const [ss, se] of voicedSpans(c)) {
    const seg = m.slice(ss, se);
    const k = seg.length >= 5 ? 5 : 1;
    const half = Math.floor(k / 2);
    const smooth = seg.map((_, i) => nanmedian(seg.slice(Math.max(0, i - half), i + half + 1)));
    let start = 0;
    let ref = smooth[0];
    let i = 0;
    while (i < smooth.length) {
      if (Math.abs(smooth[i] - ref) > SPLIT_SEMITONES) {
        let j = i;
        while (j < smooth.length && Math.abs(smooth[j] - ref) > SPLIT_SEMITONES) j++;
        if (j - i >= hold) {
          out.push([ss + start, ss + i]);
          start = i;
          ref = median(smooth.slice(i, Math.min(i + hold, smooth.length)));
          i += hold;
          continue;
        }
        i = j;
        continue;
      }
      ref = 0.98 * ref + 0.02 * smooth[i];
      i++;
    }
    out.push([ss + start, se]);
  }
  return out.filter(([s, e]) => (e - s) * hop >= MIN_NOTE_S);
}

// ---------------------------------------------------------------- FFT (radix-2)

function fft(re, im, inverse = false) {
  const n = re.length;
  for (let i = 1, j = 0; i < n; i++) {
    let bit = n >> 1;
    for (; j & bit; bit >>= 1) j ^= bit;
    j ^= bit;
    if (i < j) {
      [re[i], re[j]] = [re[j], re[i]];
      [im[i], im[j]] = [im[j], im[i]];
    }
  }
  for (let len = 2; len <= n; len <<= 1) {
    const ang = ((inverse ? 2 : -2) * Math.PI) / len;
    const wr = Math.cos(ang);
    const wi = Math.sin(ang);
    for (let i = 0; i < n; i += len) {
      let cr = 1;
      let ci = 0;
      for (let k = 0; k < len / 2; k++) {
        const ar = re[i + k + len / 2] * cr - im[i + k + len / 2] * ci;
        const ai = re[i + k + len / 2] * ci + im[i + k + len / 2] * cr;
        re[i + k + len / 2] = re[i + k] - ar;
        im[i + k + len / 2] = im[i + k] - ai;
        re[i + k] += ar;
        im[i + k] += ai;
        const t = cr * wr - ci * wi;
        ci = cr * wi + ci * wr;
        cr = t;
      }
    }
  }
  if (inverse) for (let i = 0; i < n; i++) (re[i] /= n), (im[i] /= n);
}

function bitLength(x) {
  return x <= 0 ? 0 : Math.floor(Math.log2(x)) + 1;
}

// ---------------------------------------------------------------- vibrato

export function vibrato(cents, hop) {
  const none = { present: false, rate_hz: null, extent_cents: null };
  const x = Array.from(cents).filter(Number.isFinite);
  if (hop <= 0 || x.length * hop < 0.6) return none;
  const w = Math.max(3, pyRound(0.3 / hop) | 1);
  const h = Math.floor(w / 2);
  const pad = [...Array(h).fill(x[0]), ...x, ...Array(h).fill(x[x.length - 1])];
  let resid = x.map((v, i) => {
    let s = 0;
    for (let k = 0; k < w; k++) s += pad[i + k];
    return v - s / w;
  });
  if (resid.length > w) resid = resid.slice(h, resid.length - h);
  if (resid.length * hop < 0.4) return none;
  const n = resid.length;
  const nfft = 1 << Math.max(10, bitLength(n * 4 - 1));
  const re = new Float64Array(nfft);
  const im = new Float64Array(nfft);
  for (let i = 0; i < n; i++) re[i] = resid[i] * (n === 1 ? 1 : 0.5 - 0.5 * Math.cos((2 * Math.PI * i) / (n - 1)));
  fft(re, im);
  const nb = nfft / 2 + 1;
  const spec = new Float64Array(nb);
  const freqs = new Float64Array(nb);
  for (let k = 0; k < nb; k++) {
    spec[k] = re[k] ** 2 + im[k] ** 2;
    freqs[k] = k / (nfft * hop);
  }
  let best = -1;
  let total = 0;
  let above = 0;
  for (let k = 0; k < nb; k++) {
    total += spec[k];
    if (freqs[k] > 0.5) above += spec[k];
    if (freqs[k] >= 3 && freqs[k] <= 9 && (best < 0 || spec[k] > spec[best])) best = k;
  }
  if (best < 0 || total <= 0) return none;
  const rate = freqs[best];
  const near = (f) => f >= rate - 1 && f <= rate + 1;
  let nearSum = 0;
  for (let k = 0; k < nb; k++) if (near(freqs[k])) nearSum += spec[k];
  const frac = above > 0 ? nearSum / above : 0;
  // band-limited component of the (unwindowed) residual: sinusoid amplitude = sqrt(2) * rms
  const re2 = new Float64Array(nfft);
  const im2 = new Float64Array(nfft);
  for (let i = 0; i < n; i++) re2[i] = resid[i];
  fft(re2, im2);
  for (let k = 0; k < nfft; k++) {
    const kk = k <= nfft / 2 ? k : nfft - k;
    if (!near(kk / (nfft * hop)) || k === 0 || (k === nfft / 2)) (re2[k] = 0), (im2[k] = 0);
  }
  fft(re2, im2, true);
  let ss = 0;
  for (let i = 0; i < n; i++) ss += re2[i] ** 2;
  const extent = Math.SQRT2 * Math.sqrt(ss / n);
  return {
    present: frac >= 0.5 && extent >= 15,
    rate_hz: r(rate, 2),
    extent_cents: r(extent, 1),
    periodicity: r(frac, 2),
  };
}

export function smooth(x, hop, winS = SMOOTH_S) {
  const w = Math.min(Math.max(1, hop > 0 ? pyRound(winS / hop) : 1), Math.max(1, x.length));
  const off = Math.floor((w - 1) / 2); // np.convolve(mode="same") alignment
  const out = new Array(x.length).fill(NaN);
  for (let i = 0; i < x.length; i++) {
    if (!Number.isFinite(x[i])) continue;
    let num = 0;
    let den = 0;
    for (let j = 0; j < w; j++) {
      const k = i + off - j;
      if (k >= 0 && k < x.length && Number.isFinite(x[k])) (num += x[k]), den++;
    }
    if (den > 0) out[i] = num / den;
  }
  return out;
}

function longestRun(mask, hop) {
  let best = 0;
  for (const [s, e] of runs(bridgedVoicing(mask, hop))) best = Math.max(best, (e - s) * hop);
  return best;
}

// ---------------------------------------------------------------- targets / notes

export function parseTargets(items) {
  return (items || []).map((it, i) => {
    if (typeof it === "number") it = { midi: it };
    else if (typeof it === "string") it = { note: it };
    if (typeof it !== "object" || it === null)
      throw new VoiceScoreError(`targets[${i}] must be an object, note name or MIDI number`);
    const rest = Boolean(it.rest);
    let midi = null;
    if (!rest) {
      if ("midi" in it) midi = pyRound(Number(it.midi));
      else if ("note" in it) midi = noteToMidi(it.note);
      else throw new VoiceScoreError(`targets[${i}] needs 'note', 'midi' or 'rest'`);
      if (!(midi >= 0 && midi <= 127)) throw new VoiceScoreError(`targets[${i}] MIDI ${midi} out of range`);
    }
    const num = (v) => (v === undefined || v === null ? null : Number(v));
    return { midi, name: midi === null ? null : midiToNote(midi), start: num(it.start), end: num(it.end), beats: num(it.beats), rest };
  });
}

function noteMetrics(c, i0, i1, targetMidi, opt) {
  const hop = c.hop || 0.01;
  i0 = Math.max(0, i0);
  i1 = Math.min(c.t.length, i1);
  const mAll = interpMidi(c, opt.a4_hz).slice(i0, Math.max(i0, i1));
  const voiced = mAll.map(Number.isFinite);
  const nVoiced = voiced.filter(Boolean).length;
  const out = {
    start: i1 > i0 ? r(c.t[i0], 3) : null,
    end: i1 > i0 ? r(c.t[i1 - 1] + hop, 3) : null,
    voiced_ratio: r(voiced.length ? nVoiced / voiced.length : 0, 3),
  };
  if (nVoiced * hop < 0.05) {
    return Object.assign(out, {
      sung_note: null, cents_error: null, abs_cents_mean: null, within_50c: null, within_25c: null,
      stability_cents_sd: null, raw_cents_sd: null, drift_cents: null, sustain_s: 0.0, landed_ratio: 0.0, onset_s: null,
      octave_offset: null, vibrato: vibrato([], hop), pass: targetMidi !== null ? false : null, missing: true,
    });
  }
  const voicedIdx = [];
  voiced.forEach((v, i) => v && voicedIdx.push(i));
  out.onset_s = r(voicedIdx[0] * hop, 3);
  const trim = Math.min(pyRound(ONSET_TRIM_S / hop), Math.floor(nVoiced * 0.2));
  const steadyIdx = voicedIdx.slice(trim);
  const steady = steadyIdx.map((i) => mAll[i]);
  const sung = median(steady);
  let octave = 0;
  let ref = targetMidi === null ? sung : targetMidi;
  if (targetMidi !== null && opt.octave_agnostic) {
    octave = pyRound((sung - targetMidi) / 12);
    ref = targetMidi + 12 * octave;
  }
  const cents = steady.map((m) => (m - ref) * 100);
  const smAll = smooth(mAll, hop);
  const half = pyRound(SMOOTH_S / 2 / hop);
  const smSteady = (steadyIdx.length > 3 * half ? steadyIdx.slice(half) : steadyIdx).map((i) => smAll[i]);
  const third = Math.max(1, Math.floor(steady.length / 3));
  const inTol = voiced.map((v, i) => v && Math.abs((smAll[i] - ref) * 100) <= opt.pass_cents);
  const err = median(cents);
  const hasT = targetMidi !== null;
  const absC = cents.map(Math.abs);
  Object.assign(out, {
    sung_note: midiToNote(sung),
    sung_hz: r(midiToHz(sung, opt.a4_hz), 2),
    cents_error: hasT ? r(err) : null,
    abs_cents_mean: hasT ? r(mean(absC)) : null,
    within_50c: hasT ? r(absC.filter((v) => v <= 50).length / absC.length, 3) : null,
    within_25c: hasT ? r(absC.filter((v) => v <= 25).length / absC.length, 3) : null,
    stability_cents_sd: r(std(smSteady.map((v) => v * 100))),
    raw_cents_sd: r(std(cents)),
    drift_cents: r((median(smSteady.slice(-third)) - median(smSteady.slice(0, third))) * 100),
    sustain_s: r(longestRun(inTol, hop), 2),
    landed_ratio: r(longestRun(inTol, hop) / Math.max((i1 - i0) * hop, hop), 3),
    octave_offset: hasT ? octave : null,
    vibrato: vibrato(cents, hop),
    pass: hasT ? Math.abs(err) <= opt.pass_cents : null,
  });
  return out;
}

function rangeOf(c, segs, a4) {
  const m = smooth(c.f0.map((f) => (Number.isFinite(f) ? hzToMidi(f, a4) : NaN)), c.hop || 0.01);
  const vals = [];
  for (const [s, e] of segs) for (let i = s; i < e; i++) if (Number.isFinite(m[i])) vals.push(m[i]);
  if (!vals.length) return { low_note: null, high_note: null, low_hz: null, high_hz: null, semitones: null };
  const lo = percentile(vals, 2);
  const hi = percentile(vals, 98);
  return { low_note: midiToNote(lo), high_note: midiToNote(hi), low_hz: r(midiToHz(lo, a4), 1), high_hz: r(midiToHz(hi, a4), 1), semitones: r(hi - lo, 1) };
}

function align(segMidis, segDurs, targets, octaveAgnostic) {
  const n = segMidis.length;
  const k = targets.length;
  if (n === 0) return targets.map(() => []);
  const cost = (i, j) => {
    let d = segMidis[i] - targets[j];
    if (octaveAgnostic) d -= 12 * pyRound(d / 12);
    return Math.min(Math.abs(d), 3.0) * segDurs[i];
  };
  const skip = 2.0 * median(segDurs);
  const dp = Array.from({ length: n + 1 }, () => new Float64Array(k + 1).fill(Infinity));
  const back = Array.from({ length: n + 1 }, () => new Int32Array(k + 1));
  for (let j = 0; j <= k; j++) dp[0][j] = skip * j;
  for (let i = 1; i <= n; i++) {
    for (let j = 1; j <= k; j++) {
      let best = Infinity;
      let arg = -1;
      if (dp[i - 1][j] < best) (best = dp[i - 1][j]), (arg = j);
      for (let jp = 0; jp < j; jp++) {
        const v = dp[i - 1][jp] + skip * (j - 1 - jp);
        if (v < best) (best = v), (arg = jp);
      }
      dp[i][j] = best + cost(i - 1, j - 1);
      back[i][j] = arg;
    }
  }
  let jend = 0;
  let bestEnd = Infinity;
  for (let j = 0; j <= k; j++) {
    const v = dp[n][j] + skip * (k - j);
    if (v < bestEnd) (bestEnd = v), (jend = j);
  }
  const groups = targets.map(() => []);
  let i = n;
  let j = jend;
  while (i > 0 && j > 0) {
    groups[j - 1].unshift(i - 1);
    j = back[i][j];
    i--;
  }
  return groups;
}

// Global tempo factor (sung beat / written beat) that best lines the sung pitch up with the
// target layout; mirrors metrics._fit_tempo (grid 0.6..1.6 step 0.02, per-window mean of
// min(|cents|, 300) with unvoiced = 300, windows weigh equally, +10*|ln s| prior).
function fitTempo(c, targets, spb, t0, opt) {
  const hop = c.hop || 0.01;
  const m = interpMidi(c, opt.a4_hz);
  const n = m.length;
  let best = Infinity;
  let bestS = 1.0;
  for (let k = 0; k <= 50; k++) {
    const s = 0.6 + k * 0.02;
    let t = t0;
    const costs = [];
    for (const tg of targets) {
      const dur = (tg.beats !== null ? tg.beats : 1) * spb * s;
      if (!tg.rest && tg.midi !== null) {
        const i0 = pyRound(t / hop);
        const i1 = Math.min(n, pyRound((t + dur) / hop));
        let sum = 0;
        let cnt = 0;
        if (i1 > i0) {
          for (let i = i0; i < i1; i++) {
            let d = (m[i] - tg.midi) * 100;
            if (opt.octave_agnostic) d -= 1200 * pyRound(d / 1200);
            sum += Number.isFinite(d) ? Math.min(Math.abs(d), 300) : 300;
            cnt++;
          }
        } else {
          sum = 300;
          cnt = 1;
        }
        costs.push(sum / cnt);
      }
      t += dur;
    }
    if (!costs.length) return 1.0;
    const cost = mean(costs) + 10 * Math.abs(Math.log(s));
    if (cost < best) {
      best = cost;
      bestS = s;
    }
  }
  return bestS;
}

/** Metrics from a contour {t: number[], f0: number[] (NaN = unvoiced)}. Mirrors metrics.analyze. */
export function analyzeContour(contour, targets, opt) {
  const c = { t: contour.t, f0: contour.f0.map((f) => (f === null || !(f > 0) ? NaN : f)) };
  c.hop = contourHop(c.t);
  const hop = c.hop || 0.01;
  const spans = voicedSpans(c);
  if (!spans.length) throw new VoiceScoreError("no voiced audio detected", 422);
  const noteSegs = segmentNotes(c, opt.a4_hz);
  const warnings = [];
  const notes = [];
  const frame = (t) => pyRound(t / hop);
  const tFirst = c.t[spans[0][0]];
  const emit = (idx, tg, i0, i1) =>
    notes.push({ index: idx, target_note: tg.name, target_midi: tg.midi, ...noteMetrics(c, i0, i1, tg.midi, opt) });
  const sung = targets.filter((t) => !t.rest);
  let tempoRatio = null;
  if (!targets.length) {
    noteSegs.forEach(([s, e], idx) =>
      notes.push({ index: idx, target_note: null, target_midi: null, ...noteMetrics(c, s, e, null, opt) }));
  } else if (sung.every((t) => t.start !== null)) {
    targets.forEach((tg, idx) => {
      if (tg.rest) return;
      const end = tg.end !== null ? tg.end : c.t[c.t.length - 1] + hop;
      emit(idx, tg, frame(tg.start || 0), frame(end));
    });
  } else if (targets.some((t) => t.beats !== null)) {
    if (!opt.tempo_bpm) throw new VoiceScoreError("targets use 'beats' but tempo_bpm is missing");
    let spb = 60 / opt.tempo_bpm;
    let t = tFirst;
    tempoRatio = fitTempo(c, targets, spb, tFirst, opt);
    spb *= tempoRatio;
    targets.forEach((tg, idx) => {
      const dur = (tg.beats !== null ? tg.beats : 1) * spb;
      if (!tg.rest) emit(idx, tg, frame(t), frame(t + dur));
      t += dur;
    });
  } else if (sung.length === 1) {
    const idx = targets.findIndex((t) => !t.rest);
    emit(idx, sung[0], spans[0][0], spans[spans.length - 1][1]);
  } else {
    if (!noteSegs.length) throw new VoiceScoreError("no sustained notes detected", 422);
    const m = c.f0.map((f) => (Number.isFinite(f) ? hzToMidi(f, opt.a4_hz) : NaN));
    const meds = noteSegs.map(([s, e]) => nanmedian(m.slice(s, e)));
    const durs = noteSegs.map(([s, e]) => (e - s) * hop);
    const order = [];
    targets.forEach((t, i) => !t.rest && order.push(i));
    const groups = align(meds, durs, order.map((i) => targets[i].midi || 0), opt.octave_agnostic);
    order.forEach((ti, gi) => {
      const g = groups[gi];
      if (g.length) emit(ti, targets[ti], noteSegs[g[0]][0], noteSegs[g[g.length - 1]][1]);
      else emit(ti, targets[ti], 0, 0);
    });
    if (noteSegs.length > order.length * 2)
      warnings.push(`sang ${noteSegs.length} note segments for ${order.length} targets; alignment may be off`);
  }
  const graded = notes.filter((n) => n.cents_error !== null && n.cents_error !== undefined);
  const stab = notes.map((n) => n.stability_cents_sd).filter((v) => v !== null && v !== undefined);
  const vib = notes.map((n) => n.vibrato).filter((v) => v.present);
  const voicedS = spans.reduce((a, [s, e]) => a + (e - s) * hop, 0);
  const summary = {
    voiced_s: r(voicedS, 2),
    range: rangeOf(c, noteSegs, opt.a4_hz),
    notes_targeted: sung.length,
    tempo_ratio: r(tempoRatio, 2),
    notes_passed: notes.filter((n) => n.pass).length,
    mean_abs_cents: graded.length ? r(mean(graded.map((n) => Math.abs(n.cents_error)))) : null,
    stability_cents_sd: stab.length ? r(median(stab)) : null,
    longest_sustain_s: r(Math.max(0, ...notes.map((n) => n.sustain_s || 0)), 2),
    vibrato: {
      notes_with_vibrato: vib.length,
      rate_hz: vib.length ? r(median(vib.map((v) => v.rate_hz)), 2) : null,
      extent_cents: vib.length ? r(median(vib.map((v) => v.extent_cents)), 1) : null,
    },
  };
  if (notes.some((n) => n.octave_offset))
    warnings.push("sung in a different octave than the target on some notes (octave_agnostic=true: scored against the nearest octave)");
  return { notes, summary, warnings };
}

function options(params) {
  const o = {
    a4_hz: Number(params.a4_hz ?? 440),
    pass_cents: Number(params.pass_cents ?? 50),
    octave_agnostic: params.octave_agnostic ?? true,
    tempo_bpm: params.tempo_bpm ? Number(params.tempo_bpm) : null,
  };
  if (!(o.a4_hz >= 380 && o.a4_hz <= 500)) throw new VoiceScoreError("a4_hz must be within 380-500");
  if (!(o.pass_cents > 0)) throw new VoiceScoreError("pass_cents must be positive");
  if (o.tempo_bpm !== null && !(o.tempo_bpm >= 10 && o.tempo_bpm <= 400))
    throw new VoiceScoreError("tempo_bpm must be within 10-400");
  return o;
}

// ---------------------------------------------------------------- SwiftF0

/** Create an analyzer. `ort` is the onnxruntime-web (or -node) module. */
export async function createAnalyzer({ ort, modelUrl, model, sessionOptions } = {}) {
  if (!ort) throw new Error("createAnalyzer needs { ort } (import * as ort from 'onnxruntime-web')");
  const session = await ort.InferenceSession.create(model ?? modelUrl, sessionOptions ?? {});

  async function run(audio) {
    const out = await session.run({
      audio: new ort.Tensor("float32", audio, [1, audio.length]),
      fmin: new ort.Tensor("float32", new Float32Array([FMIN]), []),
      fmax: new ort.Tensor("float32", new Float32Array([FMAX]), []),
    });
    const pitch = Float64Array.from(out.pitch.data);
    const conf = Float64Array.from(out.confidence.data);
    const n = conf.length;
    for (let f = 0; f < n; f++) {
      let peak = 0;
      const end = Math.min((f + 1) * HOP, audio.length);
      for (let i = f * HOP; i < end; i++) peak = Math.max(peak, Math.abs(audio[i]));
      if (peak < SILENCE_PEAK) conf[f] = 0;
    }
    return [pitch, conf];
  }

  /** f0 contour of mono 16 kHz Float32Array: {t, f0 (NaN unvoiced), confidence}. */
  async function track(pcm16k) {
    const n = Math.max(1, Math.floor(pcm16k.length / HOP));
    const pitch = [];
    const conf = [];
    for (let start = 0; start < n; start += WINDOW_FRAMES) {
      const end = Math.min(start + WINDOW_FRAMES, n);
      const left = Math.max(0, start - LEFT_FRAMES);
      const win = end < n ? pcm16k.subarray(left * HOP, (end + LOOKAHEAD_FRAMES) * HOP) : pcm16k.subarray(left * HOP);
      const [p, c] = await run(win);
      for (let i = start - left; i < end - left; i++) pitch.push(p[i]), conf.push(c[i]);
    }
    const t = pitch.map((_, i) => i * FRAME_PERIOD);
    const f0 = pitch.map((p, i) => (conf[i] >= 0.5 ? p : NaN));
    return { t, f0, confidence: conf };
  }

  /** Same contract as POST /analyze (params object, not a JSON string). */
  async function analyze(pcm16k, params = {}) {
    if (!(pcm16k instanceof Float32Array)) throw new VoiceScoreError("audio must be a Float32Array at 16 kHz");
    const duration = pcm16k.length / SR;
    if (duration > 60) throw new VoiceScoreError("audio longer than 60 s", 413);
    if (duration < 0.05) throw new VoiceScoreError("audio shorter than 50 ms");
    const opt = options(params);
    const targets = parseTargets(params.targets);
    const t0 = performance.now();
    const c = await track(pcm16k);
    const ms = performance.now() - t0;
    const res = analyzeContour(c, targets, opt);
    const out = {
      version: VERSION, tracker: "swiftf0-web", a4_hz: opt.a4_hz, pass_cents: opt.pass_cents,
      octave_agnostic: opt.octave_agnostic, tempo_bpm: opt.tempo_bpm, duration_s: r(duration, 3),
      hop_s: r(contourHop(c.t), 5), tracker_ms: r(ms, 1), notes: res.notes, summary: res.summary,
      labels: {}, warnings: [...levelWarnings(pcm16k), ...res.warnings],
    };
    if (params.contour ?? true)
      out.contour = { t: c.t.map((x) => r(x, 4)), f0_hz: c.f0.map((f) => (Number.isFinite(f) ? r(f, 2) : null)), confidence: c.confidence.map((x) => r(x, 3)) };
    return out;
  }

  return { analyze, track, version: VERSION };
}

function levelWarnings(x) {
  const w = [];
  if (!x.length) return w;
  let clipped = 0;
  let ss = 0;
  for (const v of x) {
    if (Math.abs(v) >= 0.999) clipped++;
    ss += v * v;
  }
  if (clipped / x.length > 0.001)
    w.push(`clipping: ${((100 * clipped) / x.length).toFixed(1)}% of samples at full scale; move back from the mic`);
  const db = 20 * Math.log10(Math.max(Math.sqrt(ss / x.length), 1e-9));
  if (db < -50) w.push(`very quiet recording (${db.toFixed(0)} dBFS RMS); pitch may be unreliable`);
  return w;
}

/** Browser helper: decode any recording (Blob/ArrayBuffer) to mono 16 kHz Float32Array. */
export async function decodeToMono16k(input) {
  const buf = input instanceof ArrayBuffer ? input : await input.arrayBuffer();
  const tmp = new AudioContext();
  const decoded = await tmp.decodeAudioData(buf);
  await tmp.close();
  const frames = Math.ceil(decoded.duration * SR);
  const off = new OfflineAudioContext(1, frames, SR);
  const src = off.createBufferSource();
  src.buffer = decoded; // >1 channel is down-mixed by the 1-channel destination
  src.connect(off.destination);
  src.start();
  const rendered = await off.startRendering();
  return rendered.getChannelData(0);
}
