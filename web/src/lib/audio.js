/* ==========================================================================
   Web Audio piano synth - the same recipe as the desktop app.

   Notes are rendered once into small AudioBuffers (a few decaying partials with
   a soft hammer bloom) and replayed through a gentle limiter, so ten-note
   chords stay smooth instead of crackling.
   ========================================================================== */

export class Piano {
  constructor() {
    this.ctx = null;
    this.master = null;
    this.buffers = new Map();
    this.voices = 0;
    this.muted = false;
  }

  async start() {
    if (!this.ctx) {
      const Ctx = window.AudioContext || window.webkitAudioContext;
      this.ctx = new Ctx({ latencyHint: "interactive" });
      this.master = this.ctx.createGain();
      this.master.gain.value = 0.8;
      // A gentle brick wall so big chords stay smooth instead of crackling
      const limiter = this.ctx.createDynamicsCompressor();
      limiter.threshold.value = -6;
      limiter.knee.value = 8;
      limiter.ratio.value = 12;
      limiter.attack.value = 0.003;
      limiter.release.value = 0.15;
      this.master.connect(limiter).connect(this.ctx.destination);
    }
    if (this.ctx.state === "suspended") await this.ctx.resume();
  }

  setVolume(v) {
    if (this.master) this.master.gain.value = v;
  }

  /* Synthesise note buffers ahead of time, a few per idle slot, so the first
     time a key is played it never waits on a buffer being built. */
  prewarm(freqs) {
    if (!this.ctx || !freqs || !freqs.length) return;
    const idle = typeof window !== "undefined" && window.requestIdleCallback
      ? window.requestIdleCallback
      : (cb) => setTimeout(() => cb({ didTimeout: false, timeRemaining: () => 8 }), 1);
    let i = 0;
    const step = (deadline) => {
      while (i < freqs.length && (deadline.didTimeout || (deadline.timeRemaining?.() ?? 0) > 4)) {
        this.bufferFor(freqs[i++]);
      }
      if (i < freqs.length) idle(step);
    };
    idle(step);
  }

  bufferFor(freq) {
    const key = freq.toFixed(2);
    let buf = this.buffers.get(key);
    if (buf) return buf;
    const sr = this.ctx.sampleRate;
    const n = Math.floor(sr * 2.5);
    buf = this.ctx.createBuffer(1, n, sr);
    const d = buf.getChannelData(0);
    const partials = [[1, 1.6], [0.42, 2.4], [0.2, 3.6], [0.09, 5], [0.04, 7], [0.02, 9.5]];
    for (let i = 0; i < n; i++) {
      const t = i / sr;
      let s = 0;
      for (let p = 0; p < partials.length; p++) {
        const [amp, decay] = partials[p];
        const ratio = 1 + p * 0.0004 * p; // a touch of inharmonicity
        s += amp * Math.exp(-decay * t) * Math.sin(2 * Math.PI * freq * ratio * t);
      }
      d[i] = s;
    }
    const atk = Math.floor(0.008 * sr); // soft hammer bloom
    for (let i = 0; i < atk && i < n; i++) d[i] *= i / atk;
    const rel = Math.floor(0.06 * sr); // no click at the tail
    for (let i = 0; i < rel && i < n; i++) d[n - 1 - i] *= i / rel;
    let peak = 0;
    for (let i = 0; i < n; i++) peak = Math.max(peak, Math.abs(d[i]));
    const g = peak > 0 ? 0.55 / peak : 0;
    for (let i = 0; i < n; i++) d[i] *= g;
    this.buffers.set(key, buf);
    return buf;
  }

  play(freq, velocity = 1) {
    if (!this.ctx || this.muted) return;
    const src = this.ctx.createBufferSource();
    src.buffer = this.bufferFor(freq);
    const g = this.ctx.createGain();
    g.gain.value = Math.max(0.05, Math.min(1, velocity));
    src.connect(g).connect(this.master);
    this.voices++;
    src.onended = () => { this.voices = Math.max(0, this.voices - 1); };
    src.start();
  }
}
