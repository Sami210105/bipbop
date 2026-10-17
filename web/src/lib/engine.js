/* ==========================================================================
   BipbopEngine — the imperative heart of the page.

   React owns the *chrome* (buttons, panels, tutor text); this class owns the
   things that must run every animation frame: the camera, the hand tracker,
   the keyboard and the canvas paint. React talks to it through a few methods
   and gets events back through callbacks, so a 60 fps loop never causes a
   React re-render.

   All the musical/geometric logic lives in web/piano-core.js (shared with the
   Node tests and kept in step with the desktop app).
   ========================================================================== */

import {
  buildKeys, FingerTracker, HIGHLIGHT_S, FINGERTIP_IDS, noteFreq,
} from "../../piano-core.js";
import { Piano } from "./audio.js";
import { hasHardwareGPU, loadHandLandmarker } from "./tracking.js";

const nowSec = () => performance.now() / 1000;

/* ---------------------------------------------------------------- tuning --
   Two profiles, one per inference backend, selected automatically at start.
   The choice is never shown in the UI — it only decides how large the camera
   frames are and how often the model runs.

   Both aim at the same thing: keep the main thread free enough that the picture
   keeps painting and a note starts the instant a key is touched, while running
   the model as often as the backend can comfortably manage.

   - `duty`   the share of the thread the model may occupy; the pause after
              each run scales with how long that run took
   - `min`/`max` bounds on the time between runs
   - `camW/camH` capture size — MediaPipe resizes to its own model input
              regardless, so a smaller frame costs nothing in accuracy */
const PROFILES = {
  gpu: { camW: 640, camH: 480, duty: 0.85, min: 16, max: 120 },
  cpu: { camW: 480, camH: 360, duty: 0.65, min: 33, max: 200 },
};
const CAM_FPS = 30;

/* ------------------------------------------------------- computer keys --
   The computer keyboard plays the same two octaves, in the usual two-row
   layout: the left hand on the bottom row, the right hand on the home row,
   with the number/top row for the upper sharps.

       Z X C V B N M    C4 D4 E4 F4 G4 A4 B4
       S D   G H J      C#4 D#4  F#4 G#4 A#4
       Q W E R T Y U I  C5 D5 E5 F5 G5 A5 B5 C6
       2 3   5 6 7      C#5 D#5  F#5 G#5 A#5            */
const KEY_MAP = {
  z: "C4", s: "C#4", x: "D4", d: "D#4", c: "E4", v: "F4", g: "F#4",
  b: "G4", h: "G#4", n: "A4", j: "A#4", m: "B4",
  q: "C5", 2: "C#5", w: "D5", 3: "D#5", e: "E5", r: "F5", 5: "F#5",
  t: "G5", 6: "G#5", y: "A5", 7: "A#5", u: "B5", i: "C6",
};
const KEY_FOR_NOTE = Object.fromEntries(
  Object.entries(KEY_MAP).map(([key, note]) => [note, key.toUpperCase()]),
);

/* Typing in a text field (e.g. the song search) must never play notes — but a
   focused slider or button must not block the piano, so only text entry counts. */
const TEXT_INPUT_TYPES = new Set([
  "text", "search", "email", "url", "tel", "password", "number",
]);
function isTypingTarget(el) {
  if (!el || !el.tagName) return false;
  if (el.isContentEditable === true) return true;
  if (el.tagName === "TEXTAREA" || el.tagName === "SELECT") return true;
  if (el.tagName !== "INPUT") return false;
  const type = (el.getAttribute("type") || "text").toLowerCase();
  return TEXT_INPUT_TYPES.has(type);
}

export class BipbopEngine {
  constructor(canvas, video, callbacks = {}) {
    this.canvas = canvas;
    this.video = video;
    this.onPress = callbacks.onPress || (() => {});
    this.onHands = callbacks.onHands || (() => {});
    this.onNotice = callbacks.onNotice || (() => {});
    this.onFrame = callbacks.onFrame || (() => {});

    this.piano = new Piano();
    this.tracker = new FingerTracker();
    this.landmarker = null;

    this.keys = [];
    this.position = "center";
    this.showHands = true;
    this.keyboardOn = true;    // computer keyboard plays the piano
    this._kbd = new Set();     // physical note labels currently held down
    this._kbdAttached = false;

    // Pick a profile once, up front, before the camera opens, so the capture
    // size matches what this machine can actually keep up with. This is an
    // internal detail and is deliberately never surfaced in the UI.
    const accelerated = hasHardwareGPU() !== false;
    this.profile = accelerated ? PROFILES.gpu : PROFILES.cpu;
    this.camW = this.profile.camW;
    this.camH = this.profile.camH;
    this.backend = accelerated ? "gpu" : "cpu";

    this.running = false;
    this.cameraOK = false;
    this.handTs = 0;
    this.fps = 0;
    this.trackMs = 0;
    this.handsSeen = 0;
    this._handsOn = false;

    this.ctx = null;    // cached 2D context
    this.layer = null;  // offscreen static-keyboard layer, blitted each frame

    this._last = 0;
    this._attached = false;
    this._rafId = 0;
    this._detectTimer = 0;
    this._lastVideoTime = -1;
  }

  /* ------------------------------------------------------------- lifecycle */

  async start() {
    await this.piano.start();
    await this.startCamera();
    this.layout();
    this.attachPointer();
    this.attachKeyboard();
    this.running = true;
    this._handsOn = false;
    this.onHands(false);
    this.loadModels();
    this.prewarmAudio();
    this._last = 0;
    this.paintLoop();        // video + keys, every display frame
    this.scheduleDetects();  // hand inference, once per captured frame
  }

  stop() {
    this.running = false;
    this.landmarker = null;
    this.detachKeyboard();
    if (this._rafId) cancelAnimationFrame(this._rafId);
    if (this._detectTimer) clearTimeout(this._detectTimer);
    this._rafId = 0;
    this._detectTimer = 0;
    this._handsOn = false;
    const stream = this.video.srcObject;
    if (stream) {
      stream.getTracks().forEach((t) => t.stop());
      this.video.srcObject = null;
    }
  }

  async startCamera() {
    try {
      const stream = await navigator.mediaDevices.getUserMedia({
        video: {
          width: { ideal: this.camW },
          height: { ideal: this.camH },
          frameRate: { ideal: CAM_FPS, max: 60 },
          facingMode: "user",
        },
        audio: false,
      });
      this.video.srcObject = stream;
      await this.video.play();
      this.cameraOK = true;
    } catch (err) {
      this.cameraOK = false;
      this.onNotice(
        `Camera not available (${err.message}) — click the on-screen keys to play.`,
      );
    }
  }

  async loadModels() {
    try {
      const { landmarker, delegate } = await loadHandLandmarker();
      this.landmarker = landmarker;
      // The loader can only ever downgrade (never upgrade), so on a downgrade
      // shrink the capture with it. Still internal — never shown.
      if (delegate === "cpu" && this.backend !== "cpu") {
        this.backend = "cpu";
        this.profile = PROFILES.cpu;
        this.camW = this.profile.camW;
        this.camH = this.profile.camH;
      }
    } catch (err) {
      this.onNotice(err.message || "Hand tracking could not load — click the keys to play.");
    }
  }

  /* Build the note buffers while the machine is idle, so the very first notes
     don't hitch while a buffer is synthesised on the spot. */
  prewarmAudio() {
    const freqs = [...new Set(this.keys.map((k) => noteFreq(k.label)))];
    this.piano.prewarm(freqs);
  }

  /* -------------------------------------------------------------- settings */

  setPosition(position) {
    this.position = position;
    this.layout();
  }

  setShowHands(show) {
    this.showHands = show;
  }

  /* Turn the computer-keyboard input on or off. The on-screen keys show their
     mapped letters only while it is on, so the layer is repainted here. */
  setKeyboard(on) {
    this.keyboardOn = !!on;
    this.buildLayer();
    if (!this.keyboardOn) this.releaseKeyboard();
  }

  setVolume(v) {
    this.piano.setVolume(v);
  }

  setMuted(muted) {
    this.piano.muted = muted;
  }

  get muted() {
    return this.piano.muted;
  }

  get voices() {
    return this.piano.voices;
  }

  /* Play a note by name (used by the tutor's Listen demo). */
  hear(label) {
    const k = this.keys.find((key) => key.label === label);
    if (k) k.highlight = nowSec();
    this.piano.play(noteFreq(label), 0.8);
  }

  /* Mark the keys the learner should press next (the tutor's gold marker). */
  setGuideNotes(labels) {
    const set = new Set(labels || []);
    for (const k of this.keys) k.guide = set.has(k.label);
  }

  /* --------------------------------------------------------------- layout */

  layout() {
    const { canvas, video } = this;
    if (this.cameraOK && video.videoWidth) {
      canvas.width = video.videoWidth;
      canvas.height = video.videoHeight;
    } else if (!canvas.width) {
      canvas.width = this.camW;
      canvas.height = this.camH;
    }
    this.ctx = canvas.getContext("2d");
    this.keys = buildKeys(canvas.width, canvas.height, this.position);
    this.tracker.setKeys(this.keys);
    this.buildLayer();
  }

  /* The keys are mostly static, so paint them once into an offscreen layer and
     blit that each frame. Only the handful of keys that light up and the hand
     dots are redrawn per frame — noticeably less canvas work on a slow
     machine, and the result looks identical. */
  buildLayer() {
    const canvas = this.canvas;
    const layer = this.layer || document.createElement("canvas");
    layer.width = canvas.width;
    layer.height = canvas.height;
    const ctx = layer.getContext("2d");
    ctx.clearRect(0, 0, layer.width, layer.height);
    for (const k of this.keys) {
      const [x, y, kw, kh] = k.rect;
      ctx.globalAlpha = 0.62; // translucent: fingers stay visible
      ctx.fillStyle = k.black ? "#191919" : "#f0f0f0";
      ctx.fillRect(x, y, kw, kh);
      ctx.globalAlpha = 1;

      ctx.lineWidth = k.black ? 1 : 2;
      ctx.strokeStyle = k.black ? "#8a8a8a" : "#3c3c3c";
      ctx.strokeRect(x, y, kw, kh);

      if (!k.black) {
        ctx.fillStyle = "#1a1a1a";
        ctx.font = "600 13px system-ui";
        ctx.fillText(k.name, x + 6, y + kh - 8);
        if (k.name === "C") {
          ctx.fillStyle = "#6b7280";
          ctx.font = "12px system-ui";
          ctx.fillText(String(k.octave), x + 6, y + 18);
        }
      }

      // the computer key that plays this note (shown only while it is enabled)
      if (this.keyboardOn) {
        const hint = KEY_FOR_NOTE[k.label];
        if (hint) {
          ctx.fillStyle = k.black ? "#9aa6b8" : "#8b93a7";
          ctx.font = k.black ? "600 10px system-ui" : "600 11px system-ui";
          ctx.textAlign = "center";
          ctx.fillText(hint, x + kw / 2, y + (k.black ? 15 : 17));
          ctx.textAlign = "start";
        }
      }
    }
    this.layer = layer;
  }

  /* ---------------------------------------------------------------- input */

  /* Every press — from a fingertip, the mouse, or the computer keyboard — goes
     through here, so each one lights the key and reaches the tutor. */
  pressCb = (key, velocity) => {
    key.highlight = nowSec();
    this.piano.play(noteFreq(key.label), velocity);
    this.onPress(key.label, velocity);
  };

  attachPointer() {
    if (this._attached) return;
    this._attached = true;
    const canvas = this.canvas;
    canvas.style.touchAction = "none";

    const toCanvas = (e) => {
      const r = canvas.getBoundingClientRect();
      return [
        ((e.clientX - r.left) / r.width) * canvas.width,
        ((e.clientY - r.top) / r.height) * canvas.height,
      ];
    };

    canvas.addEventListener("pointerdown", (e) => {
      canvas.setPointerCapture(e.pointerId);
      const [x, y] = toCanvas(e);
      this.tracker.update("ptr" + e.pointerId, x, y, nowSec(), this.pressCb);
    });
    canvas.addEventListener("pointermove", (e) => {
      if (!this.tracker.fingers.has("ptr" + e.pointerId)) return;
      const [x, y] = toCanvas(e);
      this.tracker.update("ptr" + e.pointerId, x, y, nowSec(), this.pressCb);
    });
    const end = (e) => this.tracker.releasePointer("ptr" + e.pointerId);
    canvas.addEventListener("pointerup", end);
    canvas.addEventListener("pointercancel", end);
  }

  /* -------------------------------------------------------- computer keys */

  attachKeyboard() {
    if (this._kbdAttached) return;
    this._kbdAttached = true;
    window.addEventListener("keydown", this.onKeyDown);
    window.addEventListener("keyup", this.onKeyUp);
    window.addEventListener("blur", this.releaseKeyboard);
  }

  detachKeyboard() {
    window.removeEventListener("keydown", this.onKeyDown);
    window.removeEventListener("keyup", this.onKeyUp);
    window.removeEventListener("blur", this.releaseKeyboard);
    this._kbdAttached = false;
    this.releaseKeyboard();
  }

  /* Let go of every note still held on the keyboard (e.g. the window lost
     focus mid-chord). */
  releaseKeyboard = () => {
    for (const label of this._kbd) this.tracker.releasePointer("kbd" + label);
    this._kbd.clear();
  };

  onKeyDown = (e) => {
    if (!this.keyboardOn || !this.running) return;
    if (e.ctrlKey || e.altKey || e.metaKey) return;   // leave shortcuts alone
    if (isTypingTarget(e.target)) return;             // typing must not play
    const label = KEY_MAP[e.key.length === 1 ? e.key.toLowerCase() : e.key];
    if (!label) return;
    e.preventDefault();                               // the key belongs to the piano
    if (e.repeat || this._kbd.has(label)) return;     // one note per physical press
    const k = this.keys.find((key) => key.label === label);
    if (!k) return;
    const [x, y, w, h] = k.rect;
    this._kbd.add(label);
    // Route through the tracker at the key's centre, exactly like a fingertip
    // or the mouse, so a held key counts as "pressed" for the tutor's chords.
    this.tracker.update("kbd" + label, x + w / 2, y + h / 2, nowSec(), this.pressCb);
  };

  onKeyUp = (e) => {
    const label = KEY_MAP[e.key.length === 1 ? e.key.toLowerCase() : e.key];
    if (!label || !this._kbd.has(label)) return;
    this._kbd.delete(label);
    this.tracker.releasePointer("kbd" + label);
  };

  /* -------------------------------------------------------------- tracking */

  detectHands() {
    const { video, canvas } = this;
    if (!this.landmarker || !this.cameraOK || video.readyState < 2) return;
    // infer only on genuinely new frames (rAF can outrun the camera)
    if (video.currentTime === this._lastVideoTime) return;
    this._lastVideoTime = video.currentTime;

    const ts = Math.max(performance.now(), this.handTs + 1);
    this.handTs = ts;

    const t0 = performance.now();
    let result;
    try {
      result = this.landmarker.detectForVideo(video, ts);
    } catch {
      this.landmarker = null; // stop hammering a broken detector
      return;
    }
    this.trackMs = performance.now() - t0;

    const hands = result.landmarks || [];
    this.handsSeen = hands.length;
    const on = hands.length > 0;
    if (on !== this._handsOn) {
      this._handsOn = on;
      this.onHands(on);
    }
    const seen = new Set();
    hands.forEach((hand, hi) => {
      FINGERTIP_IDS.forEach((tip, fi) => {
        const lm = hand[tip];
        if (!lm) return;
        const id = `${hi}-${fi}`;
        seen.add(id);
        // mirrored, like the video
        this.tracker.update(
          id, (1 - lm.x) * canvas.width, lm.y * canvas.height, nowSec(), this.pressCb,
        );
      });
    });
    this.tracker.releaseStale(seen);
  }

  /* ------------------------------------------------------------- painting */

  draw() {
    const canvas = this.canvas;
    const ctx = this.ctx || (this.ctx = canvas.getContext("2d"));
    const w = canvas.width;
    const h = canvas.height;
    const now = nowSec();

    ctx.clearRect(0, 0, w, h);
    const video = this.video;
    if (this.cameraOK && video.readyState >= 2) {
      ctx.save();
      ctx.translate(w, 0);
      ctx.scale(-1, 1); // mirror: it feels natural
      ctx.drawImage(video, 0, 0, w, h);
      ctx.restore();
    } else {
      ctx.fillStyle = "#0b0f14";
      ctx.fillRect(0, 0, w, h);
    }

    if (this.layer) ctx.drawImage(this.layer, 0, 0); // the static keyboard

    for (const k of this.keys) {
      const [x, y, kw, kh] = k.rect;
      const lit = now - k.highlight < HIGHLIGHT_S;

      if (lit) {
        // a translucent wash over the key, then the label again so it stays crisp
        ctx.globalAlpha = 0.62;
        ctx.fillStyle = k.black ? "#28c9ff" : "#78ffaa";
        ctx.fillRect(x, y, kw, kh);
        ctx.globalAlpha = 1;
        ctx.fillStyle = k.black ? "#003344" : "#1a1a1a";
        ctx.font = k.black ? "600 11px system-ui" : "600 13px system-ui";
        ctx.fillText(k.name, x + (k.black ? 3 : 6), y + kh - (k.black ? 6 : 8));
      }

      if (k.guide) { // the tutor's "press this next" marker
        const pulse = 2 + 2 * Math.sin(now * 6);
        ctx.strokeStyle = "#ffd166";
        ctx.lineWidth = 3 + pulse;
        ctx.strokeRect(x + 2, y + 2, kw - 4, kh - 4);
        ctx.fillStyle = "#ffd166";
        ctx.font = "700 15px system-ui";
        ctx.textAlign = "center";
        ctx.fillText(k.label, x + kw / 2, y - 6);
        ctx.textAlign = "start";
      }
    }

    if (this.showHands) {
      for (const [id, f] of this.tracker.fingers) {
        if (!f.active || id.startsWith("kbd")) continue; // keys light up instead
        ctx.beginPath();
        ctx.arc(f.x ?? 0, f.y ?? 0, f.pressed ? 12 : 7, 0, Math.PI * 2);
        ctx.strokeStyle = f.pressed ? "#ff4d4d" : "#4ade80";
        ctx.lineWidth = 3;
        ctx.stroke();
        if (f.pressed) {
          ctx.fillStyle = "#ff4d4d";
          ctx.fill();
        }
      }
    }
  }

  /* Painting and inference run on two separate loops on purpose. Inference is
     synchronous and can take tens of milliseconds; if it shared a loop with
     painting, the whole picture would stutter at the model's rate. Here the
     video keeps repainting at the display rate while hand inference runs on
     its own paced timer — so input stays responsive and the picture stays
     smooth even when the model is slow. */

  paintLoop = () => {
    if (!this.running) return;
    const now = performance.now();
    const dt = (now - (this._last || now)) / 1000;
    this._last = now;
    if (dt > 0) this.fps = 0.9 * this.fps + 0.1 * (1 / dt);

    this.draw();

    this._rafId = requestAnimationFrame(this.paintLoop);
  };

  scheduleDetects() {
    if (!this.running) return;
    const p = this.profile;
    const cycle = Math.min(p.max, Math.max(p.min, this.trackMs / p.duty));
    const gap = Math.max(0, cycle - this.trackMs);
    this._detectTimer = setTimeout(() => {
      if (!this.running) return;
      this.detectHands();
      this.onFrame(this.tracker);
      this.scheduleDetects();
    }, gap);
  }
}
