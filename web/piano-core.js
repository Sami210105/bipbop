/* ==========================================================================
   Bipbop - core logic (no DOM, no network, no audio device)

   Everything in here is pure or self-contained so it can be unit tested in
   Node as well as used by the browser app (app.js) and kept honest against
   the desktop version in air_piano.py.
   ========================================================================== */

export const NOTE_NAMES = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"];
export const WHITE_SEMITONES = new Set([0, 2, 4, 5, 7, 9, 11]);
export const FINGERTIP_IDS = [4, 8, 12, 16, 20];

// Interaction tuning - must match air_piano.py so both feel the same
export const TRIGGER_COOLDOWN = 0.05;   // seconds between note starts per finger
export const RELEASE_SLACK_FRAC = 0.14; // release once this far outside the key
export const HIT_INSET_FRAC = 0.04;     // must be this far inside the key to press
export const HIGHLIGHT_S = 0.18;        // how long a key stays lit

/* ------------------------------------------------------------ music theory */

const NOTE_RE = /^([A-Ga-g])([#b]?)(-?\d)$/;
const FLAT = { DB: "C#", EB: "D#", GB: "F#", AB: "G#", BB: "A#" };

export function parseNote(text) {
  const m = NOTE_RE.exec(String(text).trim());
  if (!m) return null;
  const letter = m[1].toUpperCase();
  let name = letter + (m[2] === "#" ? "#" : "");
  if (m[2] === "b") name = FLAT[letter + "B"] || "";
  if (!NOTE_NAMES.includes(name)) return null;
  return name + m[3];
}

export function noteToMidi(n) {
  const p = parseNote(n);
  if (!p) return null;
  return NOTE_NAMES.indexOf(p.slice(0, -1)) + 12 * (parseInt(p.slice(-1), 10) + 1);
}

export function noteFreq(n) {
  const midi = noteToMidi(n);
  return midi == null ? 440 : 440 * 2 ** ((midi - 69) / 12);
}

export function isWhite(n) {
  const p = parseNote(n);
  return !!p && WHITE_SEMITONES.has(NOTE_NAMES.indexOf(p.slice(0, -1)));
}

/* -------------------------------------------------------- keyboard layout */

export function buildKeys(w, h, position, octaves = 2) {
  const margin = Math.round(w * 0.03);
  const kbW = w - 2 * margin;
  const kbH = Math.round(h * 0.22);
  let kbY;
  if (position === "top") kbY = Math.round(h * 0.10);
  else if (position === "bottom") kbY = h - kbH - margin;
  else kbY = Math.round((h - kbH) / 2);

  const whites = [];
  const blacks = [];
  for (let s = 0; s < 12 * octaves + 1; s++) {   // +1 gives the final C
    const semi = s % 12;
    const name = NOTE_NAMES[semi];
    const octave = 4 + Math.floor(s / 12);
    const key = { label: name + octave, name, octave, black: !WHITE_SEMITONES.has(semi),
                  rect: [0, 0, 0, 0], highlight: 0, guide: false };
    if (key.black) blacks.push({ key, whitesBefore: whites.length });
    else whites.push(key);
  }
  const ww = kbW / whites.length;
  whites.forEach((k, i) => {
    k.rect = [Math.round(margin + i * ww), kbY, Math.round(ww), kbH];
  });
  const bh = Math.round(kbH * 0.62);
  const bw = Math.round(ww * 0.6);
  blacks.forEach(({ key, whitesBefore }) => {
    const boundary = margin + whitesBefore * ww;   // sits on the boundary it follows
    key.rect = [Math.round(boundary - bw / 2), kbY, bw, bh];
  });
  return whites.concat(blacks.map(b => b.key));
}

export function hit(rect, x, y, inset = 0) {
  const [rx, ry, rw, rh] = rect;
  return x >= rx + inset && x <= rx + rw - inset &&
         y >= ry + inset && y <= ry + rh - inset;
}

export function expand(rect, m) {
  const [x, y, w, h] = rect;
  return [x - m, y - m, w + 2 * m, h + 2 * m];
}

export function keyAt(keys, x, y) {
  // black keys sit on top of the white ones, so test them first
  for (const k of keys) {
    if (k.black && hit(k.rect, x, y, Math.max(1, k.rect[2] * HIT_INSET_FRAC))) return k;
  }
  for (const k of keys) {
    if (!k.black && hit(k.rect, x, y, Math.max(1, k.rect[2] * HIT_INSET_FRAC))) return k;
  }
  return null;
}

/* --------------------------------------------------------- finger tracking */

/* A "finger" is a tracked fingertip or the mouse/touch pointer. Both use the
   same rules: press when a fingertip enters a key, hold until it clearly
   leaves, and turn movement speed into loudness. */
export class FingerTracker {
  constructor() {
    this.keys = [];
    this.fingers = new Map();
  }

  setKeys(keys) { this.keys = keys; }

  update(id, x, y, now, onPress) {
    let f = this.fingers.get(id);
    if (!f) f = { prevX: x, prevY: y, prevT: 0, lastFire: 0, velocity: 1, pressed: null, active: true };

    if (f.prevT) {
      const dt = Math.max(0.001, now - f.prevT);
      const speed = Math.hypot(x - f.prevX, y - f.prevY) / dt;
      f.velocity = 0.55 + 0.45 * Math.min(1, speed / 1500);   // quick tap = louder
    }
    f.prevX = x; f.prevY = y; f.prevT = now; f.active = true;
    f.x = x; f.y = y;

    if (f.pressed) {
      const slack = Math.max(3, f.pressed.rect[2] * RELEASE_SLACK_FRAC);
      if (!hit(expand(f.pressed.rect, slack), x, y)) f.pressed = null;
    }

    let fired = null;
    if (!f.pressed && now - f.lastFire >= TRIGGER_COOLDOWN) {
      const k = keyAt(this.keys, x, y);
      if (k) {
        f.pressed = k;
        f.lastFire = now;
        fired = k;
      }
    }
    this.fingers.set(id, f);
    if (fired && onPress) onPress(fired, f.velocity, id);
    return fired;
  }

  /* Called once per frame with the set of fingertip ids seen this frame, so a
     hand that leaves the picture releases its notes. Pointers and computer
     keys release on their own events instead. */
  releaseStale(seen) {
    for (const [id, f] of [...this.fingers]) {
      if (id.startsWith("ptr") || id.startsWith("kbd")) continue;
      if (!seen.has(id)) {
        f.active = false;
        f.pressed = null;
        this.fingers.delete(id);
      }
    }
  }

  anyPressed() {
    for (const [, f] of this.fingers) if (f.pressed) return true;
    return false;
  }

  releasePointer(id) { this.fingers.delete(id); }
}

/* ------------------------------------------------------------ tutor engine */

export class TutorEngine {
  constructor() {
    this.lesson = null;
    this.index = 0;
    this.mode = null;          // null | "practice"
    this.correct = new Set();
    this.misses = 0;
    this.hits = 0;
  }

  load(lesson) {
    this.lesson = lesson;
    this.index = 0;
    this.mode = null;
    this.reset();
  }
  reset() { this.correct.clear(); this.misses = 0; this.hits = 0; }

  startPractice() {
    if (!this.lesson || !this.lesson.steps.length) return false;
    this.mode = "practice";
    this.index = 0;
    this.reset();
    return true;
  }
  stop() { this.mode = null; this.correct.clear(); }

  get step() {
    if (!this.lesson) return null;
    return this.lesson.steps[this.index] || null;
  }

  /* Returns a description of what happened so the UI can react:
     {type:"partial"|"wrong"|"advance"|"complete"} or null. */
  onKeyPressed(label) {
    if (this.mode !== "practice" || !this.step) return null;
    const step = this.step;

    if (step.notes.includes(label)) {
      this.correct.add(label);
      if (step.notes.every(n => this.correct.has(n))) {
        this.hits++;
        return this.advance();
      }
      return { type: "partial", expected: [...step.notes], have: [...this.correct] };
    }
    this.misses++;
    return { type: "wrong", expected: [...step.notes], pressed: label };
  }

  advance() {
    this.correct.clear();
    this.index++;
    if (this.index >= this.lesson.steps.length) {
      this.mode = null;
      const total = this.lesson.steps.length;
      const accuracy = Math.round((total / (total + this.misses)) * 100);
      this.index = total - 1;
      return { type: "complete", total, misses: this.misses, accuracy };
    }
    return { type: "advance", index: this.index, step: this.step };
  }

  skip() { return this.mode === "practice" ? this.advance() : null; }

  /* A chord only counts while it is held: lifting every finger drops partial
     progress, so the learner has to land the chord together. */
  forgetPartialIfLifted(anyPressed) {
    if (this.mode === "practice" && !anyPressed && this.correct.size) {
      this.correct.clear();
      return true;
    }
    return false;
  }
}
