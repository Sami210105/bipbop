/* Unit tests for web/piano-core.js — run from the project root:
       node tests/test_core.mjs
   (or from anywhere: the import is relative to this file)  */
import {
  parseNote, noteToMidi, noteFreq, isWhite, buildKeys, hit, expand, keyAt,
  FingerTracker, TutorEngine, RELEASE_SLACK_FRAC,
} from "../web/piano-core.js";

let pass = 0, fail = 0;
const ok = (cond, label, extra = "") => {
  if (cond) { pass++; console.log(`  ok   ${label}`); }
  else { fail++; console.log(`  FAIL ${label} ${extra}`); }
};

console.log("=== note parsing / frequency ===");
ok(parseNote("c4") === "C4", "lowercase -> C4");
ok(parseNote("Db4") === "C#4", "flat -> sharp");
ok(parseNote("H4") === null, "invalid rejected");
ok(Math.abs(noteFreq("A4") - 440) < 1e-9, "A4 = 440 Hz");
ok(Math.abs(noteFreq("C4") - 261.6256) < 0.01, "C4 = 261.63 Hz");
ok(noteToMidi("C4") === 60 && noteToMidi("C6") === 84, "C4=60, C6=84");
ok(isWhite("C4") && isWhite("B4") && !isWhite("C#4"), "white/black classification");

console.log("\n=== keyboard layout ===");
for (const [w, h] of [[640, 480], [1280, 720]]) {
  const keys = buildKeys(w, h, "center");
  const whites = keys.filter(k => !k.black);
  const blacks = keys.filter(k => k.black);
  ok(keys.length === 25 && whites.length === 15 && blacks.length === 10,
     `${w}x${h}: 15 white + 10 black`);
  ok(keys.every(k => k.rect[0] >= 0 && k.rect[0] + k.rect[2] <= w
                     && k.rect[1] >= 0 && k.rect[1] + k.rect[3] <= h),
     `${w}x${h}: every key inside the frame`);
  // each black key must be centred on the boundary between the two whites it splits
  const byLabel = new Map(keys.map(k => [k.label, k]));
  const pairs = [["C#4", "C4", "D4"], ["D#4", "D4", "E4"], ["F#4", "F4", "G4"],
                 ["G#4", "G4", "A4"], ["A#4", "A4", "B4"], ["C#5", "C5", "D5"]];
  const allOk = pairs.every(([b, l, r]) => {
    const left = byLabel.get(l), bk = byLabel.get(b);
    const boundary = left.rect[0] + left.rect[2];
    return Math.abs((bk.rect[0] + bk.rect[2] / 2) - boundary) <= 2;
  });
  ok(allOk, `${w}x${h}: black keys sit on the correct boundaries`);
}

console.log("\n=== positions ===");
for (const pos of ["center", "top", "bottom"]) {
  const keys = buildKeys(1280, 720, pos);
  const y0 = Math.min(...keys.map(k => k.rect[1]));
  const y1 = Math.max(...keys.map(k => k.rect[1] + k.rect[3]));
  ok(y0 >= 0 && y1 <= 720, `${pos}: strip ${y0}..${y1} fits the frame`);
}

console.log("\n=== hit testing: every key is reachable, blacks win at the overlap ===");
{
  const keys = buildKeys(1280, 720, "center");
  let misses = 0, wrong = 0;
  for (const k of keys) {
    const cx = k.rect[0] + k.rect[2] / 2, cy = k.rect[1] + k.rect[3] / 2;
    const got = keyAt(keys, cx, cy);
    if (!got) misses++;
    else if (got.label !== k.label) wrong++;
  }
  ok(misses === 0, `no dead key (${misses} misses)`);
  ok(wrong === 0, `centre of each key maps to itself (${wrong} wrong)`);
  const cs = keys.find(k => k.label === "C#4");
  ok(keyAt(keys, cs.rect[0] + cs.rect[2] / 2, cs.rect[1] + cs.rect[3] / 2).label === "C#4",
     "black key wins over the white keys it overlaps");
}

console.log("\n=== finger tracking: press, hold, release, and loudness ===");
{
  const keys = buildKeys(1280, 720, "center");
  const t = new FingerTracker();
  t.setKeys(keys);
  const fired = [];
  const onPress = (k, v) => fired.push({ label: k.label, v });

  const g = keys.find(k => k.label === "G4");
  const cx = g.rect[0] + g.rect[2] / 2, cy = g.rect[1] + g.rect[3] / 2;

  t.update("h0", cx, cy, 1.0, onPress);
  ok(fired.length === 1 && fired[0].label === "G4", "entering a key fires it once");
  t.update("h0", cx + 1, cy, 1.02, onPress);
  ok(fired.length === 1, "staying on the key does not repeat");

  const slack = Math.max(3, g.rect[2] * RELEASE_SLACK_FRAC);
  t.update("h0", g.rect[0] - slack + 2, cy, 1.05, onPress);
  ok(fired.length === 1, `still held ${(slack - 2).toFixed(1)}px outside the key (hysteresis)`);

  // sliding sideways onto the neighbour plays the neighbour (like a real piano).
  // Keep to the lower half of the white key, where no black key is in the way.
  const wy = g.rect[1] + g.rect[3] - 12;
  t.update("h0", cx, wy, 1.04, onPress);
  t.update("h0", g.rect[0] - slack - 5, wy, 1.06, onPress);
  ok(t.fingers.get("h0").pressed?.label === "F4" && fired.at(-1).label === "F4",
     "sliding left off G4 (below the black keys) plays F4");

  // ...but at mid-height that same x is the black key F#4
  ok(keyAt(keys, g.rect[0] - slack - 5, cy)?.label === "F#4",
     "the black key wins at mid-height");

  // leaving the keyboard entirely releases with nothing held
  t.update("h0", cx, g.rect[1] - 60, 1.1, onPress);
  ok(t.fingers.get("h0").pressed === null, "leaving the keyboard releases the key");

  // jitter right on the edge must not machine-gun
  const e = keys.find(k => k.label === "E4");
  const t2 = new FingerTracker();
  t2.setKeys(keys);
  let n = 0;
  const ex = e.rect[0], ey = e.rect[1] + e.rect[3] / 2;
  for (let i = 0; i < 60; i++) {
    t2.update("j", ex + (i % 3) - 1, ey, 2 + i * 0.001, () => n++);
  }
  ok(n <= 2, `60 jittery frames at the edge -> ${n} note(s)`);

  // loudness follows fingertip speed: same distance, slow vs fast
  const k2 = keys.find(k => k.label === "A4");
  const ax = k2.rect[0] + k2.rect[2] / 2, ay = k2.rect[1] + k2.rect[3] / 2;
  const startX = -100;                          // left of the keyboard, no key hit
  const slow = [];
  const ts = new FingerTracker();
  ts.setKeys(keys);
  ts.update("s", startX, ay, 1.0, () => {});
  ts.update("s", ax, ay, 1.5, (k, v) => slow.push(v));      // 500 px in 0.5 s
  const fast = [];
  const tf = new FingerTracker();
  tf.setKeys(keys);
  tf.update("f", startX, ay, 1.0, () => {});
  tf.update("f", ax, ay, 1.02, (k, v) => fast.push(v));     // 500 px in 20 ms
  ok(slow.length === 1 && fast.length === 1, "both strikes registered once");
  ok(fast[0] > slow[0],
     `fast strike louder (${fast[0].toFixed(2)} > ${slow[0].toFixed(2)})`);
  ok(slow[0] >= 0.55 && slow[0] < 1 && fast[0] === 1, "velocity spans 0.55..1.0");

  // a hand leaving the picture releases its note
  t.releaseStale(new Set());
  ok(t.fingers.size === 0, "lost hand is released");
  t.update("ptr7", cx, cy, 9, onPress);
  t.releaseStale(new Set());
  ok(t.fingers.has("ptr7"), "pointer is NOT released by releaseStale");
  t.releasePointer("ptr7");
  ok(!t.fingers.has("ptr7"), "pointer releases on pointerup");

  // a held computer key behaves like a held fingertip: it strikes once, counts
  // as pressed (for the tutor's chords), and is not cleared by releaseStale —
  // the keyboard releases it on its own keyup
  const t3 = new FingerTracker();
  t3.setKeys(keys);
  const c4 = keys.find((k) => k.label === "C4");
  const c4x = c4.rect[0] + c4.rect[2] / 2;
  const c4y = c4.rect[1] + c4.rect[3] / 2;
  let hits = 0;
  t3.update("kbdC4", c4x, c4y, 12, () => hits++);
  ok(hits === 1, "a computer key strikes its note once");
  ok(t3.anyPressed(), "a held computer key counts as pressed (tutor chords)");
  t3.releaseStale(new Set());
  ok(t3.fingers.has("kbdC4"), "computer key is NOT released by releaseStale");
  t3.releasePointer("kbdC4");
  ok(!t3.fingers.has("kbdC4"), "computer key releases on keyup");
}

console.log("\n=== tutor engine ===");
{
  const lesson = { title: "T", tempo: 100, steps: [
    { notes: ["C4"], beats: 1 },
    { notes: ["E4"], beats: 1 },
    { notes: ["C4", "E4", "G4"], beats: 2 },
  ] };
  const te = new TutorEngine();
  te.load(lesson);
  ok(te.onKeyPressed("C4") === null, "no scoring before practice starts");
  ok(te.startPractice() === true && te.step.notes[0] === "C4", "practice starts at note 1");

  let ev = te.onKeyPressed("D4");
  ok(ev.type === "wrong" && te.misses === 1, "wrong note counted, does not advance");
  ok(te.index === 0, "still on the same note after a wrong press");

  ev = te.onKeyPressed("C4");
  ok(ev.type === "advance" && te.index === 1, "right note advances");

  ev = te.onKeyPressed("E4");
  ok(ev.type === "advance" && te.index === 2, "second note advances");

  ev = te.onKeyPressed("C4");
  ok(ev.type === "partial" && te.correct.size === 1, "chord: first key is partial");
  ev = te.onKeyPressed("E4");
  ok(ev.type === "partial" && te.correct.size === 2, "chord: second key still partial");
  // lifting before completing the chord drops the partial progress
  te.forgetPartialIfLifted(false);
  ok(te.correct.size === 0, "lifting mid-chord resets partial progress");
  te.onKeyPressed("C4");
  te.onKeyPressed("E4");
  ev = te.onKeyPressed("G4");
  ok(ev.type === "complete" && ev.total === 3 && ev.misses === 1 && ev.accuracy === 75,
     `chord completes the song (accuracy ${ev.accuracy}%)`);
  ok(te.mode === null, "practice ends when the song is done");

  // skip
  const te2 = new TutorEngine();
  te2.load(lesson);
  te2.startPractice();
  ok(te2.skip().type === "advance" && te2.index === 1, "skip advances");
}

console.log(`\n${pass} passed, ${fail} failed`);
process.exit(fail ? 1 : 0);
