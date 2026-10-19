"""
BIPBOP - play a virtual piano floating in the air with your fingertips.

A webcam feed is shown mirrored, with two octaves of piano keys drawn over it.
Hold your hands up to the camera and "press" the keys with your 10 fingertips.
Notes are synthesized in real time with a piano-like tone.

On startup the app picks the lowest-latency audio path available (WASAPI
exclusive -> WDM-KS -> WASAPI shared -> default), so playing feels instant.

Controls:
    ESC / q : quit
    m       : mute / unmute
    space   : pause key display (keeps audio running)
    p       : move the keyboard (center -> top -> bottom)
    h       : toggle help overlay
    l       : Learn mode on/off (tutor guides you through a song)
    [ / ]   : previous / next song in Learn mode
    d       : play the current song so you can hear it
    r       : restart the current song
    k       : skip to the next note
    n       : ask the AI for a song (type a name in the console)

Run:  python air_piano.py
      python air_piano.py --learn              # start in Learn mode
      python air_piano.py --song "Let It Be"   # learn a specific song
      python air_piano.py --list-songs         # show the built-in songs
"""

import math
import os
import sys
import threading
import time
from dataclasses import dataclass, field

import cv2
import mediapipe as mp
import numpy as np
from mediapipe.tasks.python import BaseOptions
from mediapipe.tasks.python.vision import (
    HandLandmarker,
    HandLandmarkerOptions,
    HandLandmarksConnections,
    RunningMode,
    drawing_utils,
    drawing_styles,
)

import tutor  # shared song/lesson library (standard library only)

# ----------------------------------------------------------------- audio ----

DEFAULT_SAMPLE_RATE = 44100

# Per-note level: leaves headroom so a single note is clean, never near clipping
NOTE_PEAK = 0.55
# Master ceiling the limiter aims for, and the knee of the final safety soft-clip
MASTER_CEILING = 0.90
SOFT_KNEE = 0.85


def soft_clip(x: np.ndarray, knee: float = SOFT_KNEE) -> np.ndarray:
    """Transparent below `knee`, gently compresses above it (never a hard edge).

    This is the last line of defence: it turns what would be harsh digital
    clipping into a smooth, piano-soundboard-like squeeze.
    """
    a = np.abs(x)
    over = a > knee
    if np.any(over):
        room = 1.0 - knee
        limited = knee + room * np.tanh((a - knee) / room)
        x = np.where(over, np.sign(x) * limited, x)
    return x.astype(np.float32, copy=False)


def make_piano_note(freq: float, duration: float = 2.5,
                    sr: int = DEFAULT_SAMPLE_RATE) -> np.ndarray:
    """Synthesize a decaying, multi-partial piano-ish tone."""
    n = int(sr * duration)
    t = np.arange(n) / sr
    note = np.zeros(n, dtype=np.float64)

    # Harmonic partials: amplitude, decay rate, slight inharmonicity.
    # Higher partials fade faster, which is what makes a piano sound mellow
    # as it rings out instead of turning into a harsh buzz.
    partials = [
        (1.00, 1.6),
        (0.42, 2.4),
        (0.20, 3.6),
        (0.09, 5.0),
        (0.04, 7.0),
        (0.02, 9.5),
    ]
    for i, (amp, decay) in enumerate(partials):
        ratio = 1.0 + i * 0.0004 * i  # very slight inharmonicity, like real strings
        note += amp * np.exp(-decay * t) * np.sin(2 * np.pi * freq * ratio * t)

    # Soft hammer attack (8 ms) so notes bloom in rather than clicking
    attack = int(0.008 * sr)
    if attack > 0:
        note[:attack] *= np.linspace(0.0, 1.0, attack)

    # Fade the very end so a note never stops mid-cycle (no click)
    release = int(0.06 * sr)
    if release > 0:
        note[-release:] *= np.linspace(1.0, 0.0, release)

    peak = np.max(np.abs(note))
    if peak > 0:
        note = NOTE_PEAK * note / peak
    return note.astype(np.float32)


def list_audio_devices():
    """Print every audio device with its host API (for --list-audio)."""
    try:
        import sounddevice as sd
    except Exception as exc:
        print(f"sounddevice is not available: {exc}")
        return
    print("Output devices (use the index with --audio-device):\n")
    default_out = sd.default.device[1]
    for i, d in enumerate(sd.query_devices()):
        if d["max_output_channels"] > 0:
            api = sd.query_hostapis(d["hostapi"])["name"]
            mark = " <- default" if i == default_out else ""
            print(f"  [{i:2}] {api:26} {d['name']}{mark}")


class AudioEngine:
    """Plays note voices through a low-latency sounddevice stream.

    Tries the fastest working configuration first and falls back from there,
    so it works on machines where WASAPI exclusive is unavailable.
    """

    def __init__(self, device=None, blocksize: int = 256, exclusive: bool = True):
        self.voices: list = []  # list of (sample, playback position, gain)
        self.muted = False
        self.backend = None
        self.sr = DEFAULT_SAMPLE_RATE
        self.latency_ms = None
        self.device_name = ""
        self._stream = None
        self._sd = None
        # Master limiter state: keeps chords loud but never harsh. Quiet
        # playing stays untouched, loud chords get squeezed smoothly.
        self._gain = 1.0
        self._release_tau = 0.15  # seconds to ease the gain back up

        try:
            import sounddevice as sd

            self._sd = sd
        except Exception:
            self.backend = "winsound (sounddevice unavailable)"
            self._init_winsound()
            return

        for cand in self._candidates(device, blocksize, exclusive):
            try:
                stream = sd.OutputStream(
                    device=cand["device"],
                    samplerate=cand["sr"],
                    channels=1,
                    dtype="float32",
                    callback=self._callback,
                    blocksize=cand["bs"],
                    latency="low",
                    extra_settings=cand["settings"],
                )
                stream.start()
            except Exception:
                continue
            self._stream = stream
            self.sr = cand["sr"]
            self.backend = f"sounddevice ({cand['label']})"
            self.device_name = sd.query_devices(cand["device"])["name"]
            self.latency_ms = round(
                (stream.latency + cand["bs"] / cand["sr"]) * 1000, 1)
            return

        self.backend = "winsound (no low-latency device)"
        self._init_winsound()

    # ----- configuration search ---------------------------------------------

    def _candidates(self, device, blocksize: int, exclusive: bool) -> list:
        sd = self._sd
        default_out = sd.default.device[1]
        base = default_out
        if device is not None:
            base = self._resolve_device(device)

        name = sd.query_devices(base)["name"]
        native = int(sd.query_devices(base)["default_samplerate"]) or 48000
        rates = []
        for sr in (48000, 44100, native):
            if sr not in rates:
                rates.append(sr)

        def same_name(api_name):
            for i, d in enumerate(sd.query_devices()):
                if d["max_output_channels"] > 0 and d["name"] == name:
                    if sd.query_hostapis(d["hostapi"])["name"] == api_name:
                        return i
            return None

        wasapi, wdmks = same_name("Windows WASAPI"), same_name("Windows WDM-KS")
        cands = []

        if exclusive and wasapi is not None:
            try:
                excl = sd.WasapiSettings(exclusive=True)
            except Exception:
                excl = None
            if excl is not None:
                for sr in rates:
                    cands.append({"device": wasapi, "sr": sr, "bs": blocksize,
                                  "settings": excl, "label": "WASAPI exclusive"})
        if wdmks is not None:
            for sr in rates:
                cands.append({"device": wdmks, "sr": sr, "bs": blocksize,
                              "settings": None, "label": "WDM-KS"})
        if wasapi is not None:
            for sr in rates:
                cands.append({"device": wasapi, "sr": sr, "bs": blocksize,
                              "settings": None, "label": "WASAPI shared"})
        for sr in rates:
            cands.append({"device": base, "sr": sr, "bs": max(blocksize, 512),
                          "settings": None, "label": "default host API"})
        return cands

    def _resolve_device(self, spec):
        if isinstance(spec, int):
            return spec
        for i, d in enumerate(self._sd.query_devices()):
            if d["max_output_channels"] > 0 and str(spec).lower() in d["name"].lower():
                return i
        raise SystemExit(
            f"No output device matching '{spec}'.\nRun with --list-audio to see options.")

    # ----- sounddevice path -------------------------------------------------

    def _callback(self, outdata, frames, time_info, status):
        # Sum every ringing note into one mix
        mix = np.zeros(frames, dtype=np.float32)
        remaining = []
        for sample, pos, gain in self.voices:
            if sample is None:
                continue
            end = pos + frames
            chunk = sample[pos:end]
            mix[: len(chunk)] += chunk * gain
            if end < len(sample):
                remaining.append((sample, end, gain))
        self.voices = remaining

        # Master limiter: only acts when the mix would get too loud, and it
        # eases back up slowly so decaying notes keep their natural ring.
        peak = float(np.max(np.abs(mix))) if frames else 0.0
        target = 1.0 if peak <= MASTER_CEILING else MASTER_CEILING / peak
        prev = self._gain
        if target < prev:
            self._gain = target  # clamp down immediately: no clipping
        else:
            block_s = frames / self.sr
            coef = 1.0 - math.exp(-block_s / self._release_tau)
            self._gain = prev + (target - prev) * coef

        # Ramp the gain across the block so there are no stepping artefacts
        if abs(self._gain - prev) > 1e-4:
            mix *= np.linspace(prev, self._gain, frames, dtype=np.float32)
        else:
            mix *= self._gain

        outdata[:, 0] = soft_clip(mix)

    # ----- winsound fallback ------------------------------------------------

    def _init_winsound(self):
        import tempfile

        self._tmpdir = tempfile.mkdtemp(prefix="bipbop_")
        self._win_cache: dict = {}
        self._busy_until = 0.0

    def _write_wav(self, name: str, data: np.ndarray) -> str:
        import wave

        path = os.path.join(self._tmpdir, name + ".wav")
        pcm = (np.clip(data, -1.0, 1.0) * 32767).astype(np.int16)
        with wave.open(path, "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(self.sr)
            w.writeframes(pcm.tobytes())
        return path

    # ----- public -----------------------------------------------------------

    def play(self, sample: np.ndarray, velocity: float = 1.0):
        """Start a note. `velocity` (0..1) is the strike strength."""
        if self.muted or sample is None:
            return
        velocity = min(1.0, max(0.05, float(velocity)))
        if self._stream is not None:
            self.voices.append((sample, 0, velocity))
        else:
            import winsound

            now = time.time()
            if now < self._busy_until:  # winsound can only play one sound at a time
                return
            scaled = sample if velocity == 1.0 else sample * velocity
            key = round(float(scaled.sum()), 3)
            path = self._win_cache.get(key)
            if path is None:
                path = self._write_wav(f"note_{len(self._win_cache)}", scaled)
                self._win_cache[key] = path
            try:
                winsound.PlaySound(
                    path, winsound.SND_FILENAME | winsound.SND_ASYNC | winsound.SND_NODEFAULT
                )
                self._busy_until = now + len(scaled) / self.sr * 0.9
            except Exception:
                pass

    def close(self):
        if self._stream is not None:
            try:
                self._stream.stop()
                self._stream.close()
            except Exception:
                pass
        if getattr(self, "_tmpdir", None):
            import shutil

            shutil.rmtree(self._tmpdir, ignore_errors=True)


# ------------------------------------------------------------------ model ----

MODEL_URL = ("https://storage.googleapis.com/mediapipe-models/hand_landmarker/"
             "hand_landmarker/float16/latest/hand_landmarker.task")


def resolve_model() -> str:
    """Find the hand-landmarker model: env var -> project -> venv -> download."""
    here = os.path.dirname(os.path.abspath(__file__))
    candidates = [
        os.environ.get("AIR_PIANO_MODEL"),
        os.path.join(here, "models", "hand_landmarker.task"),
        os.path.join(sys.prefix, "models", "hand_landmarker.task"),
    ]
    for path in candidates:
        if path and os.path.isfile(path):
            return path

    target = os.path.join(sys.prefix, "models", "hand_landmarker.task")
    os.makedirs(os.path.dirname(target), exist_ok=True)
    print(f"Downloading hand tracking model -> {target}")
    import urllib.request

    try:
        urllib.request.urlretrieve(MODEL_URL, target)
    except Exception as exc:
        raise SystemExit(
            f"Could not download the hand tracking model: {exc}\n"
            f"Download it manually from:\n  {MODEL_URL}\n"
            f"and save it as:\n  {target}"
        )
    return target


# ------------------------------------------------------------------ keys ----

NOTE_NAMES = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]
WHITE_SEMITONES = {0, 2, 4, 5, 7, 9, 11}  # semitones that are white keys


def note_freq(name: str, octave: int) -> float:
    semis = NOTE_NAMES.index(name) + 12 * (octave + 1)
    return 440.0 * 2 ** ((semis - 69) / 12)


@dataclass
class Key:
    name: str
    octave: int
    black: bool
    freq: float
    rect: tuple = (0, 0, 0, 0)  # x, y, w, h
    highlight: float = 0.0
    sample: np.ndarray = field(default=None, repr=False)

    @property
    def label(self) -> str:
        return f"{self.name}{self.octave}"


def build_keys(x0: int, y0: int, width: int, height: int, octaves: int = 2) -> list:
    """Lay out `octaves` octaves + a final C.

    White keys are evenly spaced; each black key is centered on the boundary
    between the two white keys it sits between (C# between C and D, and so on).
    """
    whites: list = []
    blacks: list = []  # (number of white keys to its left, key)
    for s in range(12 * octaves + 1):  # +1 gives the final C
        semis = s % 12
        name = NOTE_NAMES[semis]
        octave = 4 + s // 12
        key = Key(name, octave, semis not in WHITE_SEMITONES,
                  note_freq(name, octave))
        if key.black:
            # A black key sits on the right edge of the last white key added
            blacks.append((len(whites), key))
        else:
            whites.append(key)

    ww = width / len(whites)
    bh = height * 0.62
    bw = ww * 0.60

    for i, k in enumerate(whites):
        k.rect = (int(x0 + i * ww), y0, int(ww), height)

    for whites_before, k in blacks:
        boundary = x0 + whites_before * ww
        k.rect = (int(boundary - bw / 2), y0, int(bw), int(bh))

    return whites + [k for _, k in blacks]


# ----------------------------------------------------------------- piano ----

FINGERTIP_IDS = (4, 8, 12, 16, 20)  # thumb..pinky
TRIGGER_COOLDOWN = 0.05    # seconds; stops jittery re-triggering at key edges
RELEASE_SLACK_FRAC = 0.14  # release once the fingertip is this far outside a key
HIT_INSET_FRAC = 0.04      # how far inside a key (fraction of its width) counts
KEYBOARD_POSITIONS = ("center", "top", "bottom")


def lesson_for_listed_song(title: str):
    """The lesson behind a song-list entry: built-in or saved in songs/.

    Never asks a model, so it is safe to call from the render loop. The song list
    includes anything saved in songs/, which get_builtin() alone knows nothing
    about (that would leave Learn mode with no song at all).
    """
    try:
        return tutor.find_lesson(title, allow_llm=False)
    except LookupError:
        return None


@dataclass
class Finger:
    x: int = 0
    y: int = 0
    active: bool = False
    pressed_key: object = None
    prev_x: int = 0
    prev_y: int = 0
    prev_t: float = 0.0
    last_fire: float = 0.0
    velocity: float = 1.0


class Bipbop:
    def __init__(self, camera: int = 0, octaves: int = 2, audio_device=None,
                 blocksize: int = 256, exclusive: bool = True,
                 position: str = "center", width: int = 0, height: int = 0,
                 song: str = None, learn: bool = False):
        self.octaves = octaves
        self.position = position if position in KEYBOARD_POSITIONS else "center"
        self.cam_size = (int(width), int(height))
        self.audio = AudioEngine(device=audio_device, blocksize=blocksize,
                                 exclusive=exclusive)

        model = resolve_model()
        self.landmarker = HandLandmarker.create_from_options(
            HandLandmarkerOptions(
                base_options=BaseOptions(model_asset_path=model),
                running_mode=RunningMode.VIDEO,
                num_hands=2,
                min_hand_detection_confidence=0.6,
                min_tracking_confidence=0.5,
            )
        )

        self.fingers = {i: Finger() for i in range(10)}
        self.show_help = True
        self.paused = False
        self.last_frame_time = time.time()
        self.fps = 0.0
        self.detect_ms = 0.0
        self._sample_cache: dict = {}  # freq -> rendered note, shared across frames

        # ---- tutor / learn mode -------------------------------------------
        self.learn = bool(learn)
        self.lesson = None            # a tutor.Lesson, or None
        self.learn_index = 0
        self.learn_correct = set()    # note labels pressed so far for this step
        self.learn_hits = 0
        self.learn_misses = 0
        self.learn_flash = 0.0        # time of the last wrong note (for a red flash)
        self.learn_done_at = 0.0      # time the song was completed
        self.song_spec = song
        self._song_index = -1
        self._pending_lesson = None   # set by the stdin listener, consumed in run()
        self._pending_song = None
        self._closing = False
        self._demo_thread = None

        # Try the low-latency Windows backend first, fall back to the default
        self.cap = cv2.VideoCapture(camera, cv2.CAP_DSHOW)
        if not self.cap.isOpened():
            self.cap.release()
            self.cap = cv2.VideoCapture(camera)
        try:
            self.cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)  # don't queue stale frames
        except Exception:
            pass
        if self.cam_size[0] > 0:
            self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, self.cam_size[0])
        if self.cam_size[1] > 0:
            self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, self.cam_size[1])
        self._last_ts_ms = 0

        # Load the requested song up front (may call a free LLM once)
        if self.song_spec:
            self.load_lesson(self.song_spec)
        elif self.learn:
            self.load_default_song()

    # ------------------------------------------------------------- tutor ----

    def load_default_song(self):
        """Pick a friendly first song when Learn mode turns on."""
        songs = tutor.list_songs()
        if songs:
            self._song_index = 0
            self.set_lesson(lesson_for_listed_song(songs[0]["title"]))

    def load_lesson(self, title: str, refresh: bool = False) -> bool:
        """Fetch a lesson (built-in, saved, cached, or via a free LLM)."""
        if tutor.get_builtin(title) is None and tutor.get_songbook(title) is None:
            print(f"[tutor] looking up '{title}' ... "
                  f"(a local model can take a minute)")
        try:
            lesson = tutor.find_lesson(title, refresh=refresh)
        except LookupError as exc:
            print(f"[tutor] {exc}")
            return False
        self.set_lesson(lesson)
        print(f"[tutor] loaded '{lesson.display}' "
              f"({lesson.length} notes, {lesson.tempo} BPM, {lesson.source})")
        return True

    def set_lesson(self, lesson):
        self.lesson = lesson
        self.learn_index = 0
        self.learn_correct = set()
        self.learn_hits = 0
        self.learn_misses = 0
        self.learn_done_at = 0.0

    def cycle_song(self, step: int):
        songs = tutor.list_songs()
        if not songs:
            return
        self._song_index = (self._song_index + step) % len(songs)
        self.set_lesson(lesson_for_listed_song(songs[self._song_index]["title"]))

    def _step(self):
        if not self.lesson:
            return None
        return self.lesson.steps[self.learn_index] if self.learn_index < len(self.lesson.steps) else None

    def _advance(self):
        self.learn_correct.clear()
        self.learn_index += 1
        if self.lesson and self.learn_index >= len(self.lesson.steps):
            self.learn_index = len(self.lesson.steps) - 1
            self.learn_done_at = time.time()
            total = len(self.lesson.steps)
            acc = round(total / (total + self.learn_misses) * 100)
            print(f"[tutor] Song complete! {total} notes, {self.learn_misses} wrong, {acc}% accuracy")

    def learn_on_press(self, label: str):
        """Score a played note while learning (called for every key press)."""
        step = self._step()
        if step is None or self.learn_done_at:
            return
        if label in step.notes:
            self.learn_correct.add(label)
            if all(n in self.learn_correct for n in step.notes):
                self.learn_hits += 1
                self._advance()
        else:
            self.learn_misses += 1
            self.learn_flash = time.time()

    def learn_demo(self):
        """Play the current song so the learner can hear it first."""
        if not self.lesson or (self._demo_thread and self._demo_thread.is_alive()):
            return
        lesson = self.lesson
        spb = 60.0 / max(1, lesson.tempo)

        def play():
            while not self._closing:
                for step in lesson.steps:
                    if self._closing:
                        return
                    for n in step.notes:
                        for k in getattr(self, "_keys", []):
                            if k.label == n:
                                k.highlight = time.time()
                                self.audio.play(k.sample, 0.85)
                                break
                    time.sleep(max(0.05, step.beats * spb))

        self._demo_thread = threading.Thread(target=play, daemon=True)
        self._demo_thread.start()

    def _stdin_listener(self):
        """Let the user type a song name in the console (any song, via the LLM).

        The lookup happens on this thread so a slow model never stalls the video.
        """
        while not self._closing:
            try:
                line = input()
            except (EOFError, KeyboardInterrupt, ValueError):
                return
            except Exception:
                return
            line = line.strip()
            if not line:
                continue
            print(f"[tutor] looking up '{line}' (this can take a while with a local model) ...")
            try:
                lesson = tutor.find_lesson(line)
            except Exception as exc:
                print(f"[tutor] {exc}")
                continue
            self._pending_lesson = lesson

    def camera_report(self) -> str:
        """Read a few frames and report size/speed/brightness.

        A dark or covered lens is the usual reason hand tracking feels laggy:
        the camera stretches its exposure and the frame rate collapses. Tell the
        user plainly instead of letting them wonder why it feels broken.
        """
        if not self.cap.isOpened():
            return "camera: NOT OPEN"
        frames = []
        t0 = time.time()
        while len(frames) < 5 and time.time() - t0 < 2.5:
            ok, fr = self.cap.read()
            if ok:
                frames.append(fr)
        if not frames:
            return "camera: opened but returned no frames"
        elapsed = time.time() - t0
        h, w = frames[-1].shape[:2]
        fps = len(frames) / elapsed if elapsed > 0 else 0.0
        brightness = float(np.mean([float(f.mean()) for f in frames]))
        report = f"camera: {w}x{h} at ~{fps:.0f} fps"
        if brightness < 12:
            report += ("\n  WARNING: the image is almost black. Light your face/hands "
                       "or uncover the lens -\n  a dark picture makes the camera slow "
                       "and tracking laggy.")
        elif fps < 6:
            report += ("\n  WARNING: the camera is delivering very few frames per "
                       "second.\n  Try --width 640 --height 480, close other apps "
                       "using the camera, and check lighting.")
        return report

    def _layout(self, w: int, h: int) -> list:
        margin = int(w * 0.03)
        kb_w = w - 2 * margin
        kb_h = int(h * 0.22)
        if self.position == "top":
            kb_y = 84  # sits just below the HUD readout
        elif self.position == "center":
            kb_y = (h - kb_h) // 2
        else:  # bottom
            kb_y = h - kb_h - margin
        keys = build_keys(margin, kb_y, kb_w, kb_h, self.octaves)
        # Attach an audio sample to every key (rendered once per pitch, then cached)
        for k in keys:
            k.sample = self._sample_cache.get(k.freq)
            if k.sample is None:
                k.sample = make_piano_note(k.freq, sr=self.audio.sr)
                self._sample_cache[k.freq] = k.sample
        return keys

    @staticmethod
    def _hit(rect, x: int, y: int, inset: int = 0) -> bool:
        rx, ry, rw, rh = rect
        return (rx + inset <= x <= rx + rw - inset
                and ry + inset <= y <= ry + rh - inset)

    @staticmethod
    def _expand(rect, margin: int) -> tuple:
        x, y, w, h = rect
        return (x - margin, y - margin, w + 2 * margin, h + 2 * margin)

    def _process_fingers(self, keys: list, hand_landmarks, hand_index: int, w: int, h: int):
        now = time.time()
        # black keys first: they sit on top of the white keys
        ordered = sorted(keys, key=lambda k: not k.black)

        for fi, tip_id in enumerate(FINGERTIP_IDS):
            idx = hand_index * 5 + fi
            finger = self.fingers[idx]
            lm = hand_landmarks[tip_id]
            x, y = int(lm.x * w), int(lm.y * h)
            finger.x, finger.y, finger.active = x, y, True

            # Fingertip speed since the last frame -> strike strength (dynamics),
            # so quick taps ring out and slow drifts stay soft.
            if finger.prev_t:
                dt = max(1e-3, now - finger.prev_t)
                speed = math.hypot(x - finger.prev_x, y - finger.prev_y) / dt
                finger.velocity = 0.55 + 0.45 * min(1.0, speed / 1500.0)
            finger.prev_x, finger.prev_y, finger.prev_t = x, y, now

            held = finger.pressed_key
            # Release only once the fingertip is clearly off the key, so a
            # wobble right at a key edge doesn't re-trigger the note. The slack
            # scales with key width: on a small key a flat 10px would be wider
            # than the key itself and make it feel sticky.
            if held is not None:
                slack = max(3, int(held.rect[2] * RELEASE_SLACK_FRAC))
                if not self._hit(self._expand(held.rect, slack), x, y):
                    held = None
                    finger.pressed_key = None

            if held is not None:
                continue  # already playing this key: no repeat

            hit_key = None
            for k in ordered:
                inset = max(1, int(k.rect[2] * HIT_INSET_FRAC))
                if self._hit(k.rect, x, y, inset):
                    hit_key = k
                    break

            if hit_key is not None and now - finger.last_fire >= TRIGGER_COOLDOWN:
                hit_key.highlight = now
                self.audio.play(hit_key.sample, finger.velocity)
                finger.last_fire = now
                finger.pressed_key = hit_key
                if self.learn:
                    self.learn_on_press(hit_key.label)

    def _draw_keys(self, img, keys: list, alpha: float = 0.62):
        """Draw the keyboard as a translucent strip so hands stay visible.

        The key fills are blended over the camera image; outlines and labels are
        drawn crisply on top afterwards.
        """
        if not keys:
            return
        now = time.time()
        strip_top = max(0, min(k.rect[1] for k in keys))
        strip_bottom = min(img.shape[0], max(k.rect[1] + k.rect[3] for k in keys))

        overlay = img.copy()
        for k in keys:
            x, y, w, h = k.rect
            lit = (now - k.highlight) < 0.18
            if k.black:
                fill = (0, 200, 255) if lit else (25, 25, 25)
            else:
                fill = (120, 255, 170) if lit else (240, 240, 240)
            cv2.rectangle(overlay, (x, y), (x + w, y + h), fill, -1)

        # Blend only the keyboard strip, not the whole frame
        if strip_bottom > strip_top:
            roi = img[strip_top:strip_bottom]
            cv2.addWeighted(overlay[strip_top:strip_bottom], alpha, roi,
                            1.0 - alpha, 0, dst=roi)

        # Crisp outlines and labels on top of the blend
        for k in keys:
            x, y, w, h = k.rect
            lit = (now - k.highlight) < 0.18
            if k.black:
                cv2.rectangle(img, (x, y), (x + w, y + h), (160, 160, 160), 1)
                if lit:
                    cv2.rectangle(img, (x, y), (x + w, y + h), (0, 230, 255), 2)
                    cv2.putText(img, k.name, (x + 3, y + h - 8),
                                cv2.FONT_HERSHEY_SIMPLEX, 0.42, (255, 255, 255), 1,
                                cv2.LINE_AA)
            else:
                cv2.rectangle(img, (x, y), (x + w, y + h), (60, 60, 60), 2)
                if lit:
                    cv2.rectangle(img, (x, y), (x + w, y + h), (0, 200, 120), 4)
                cv2.putText(img, k.name, (x + 6, y + h - 12),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.5, (25, 25, 25), 1, cv2.LINE_AA)
                if k.name == "C":
                    cv2.putText(img, str(k.octave), (x + 6, y + 22),
                                cv2.FONT_HERSHEY_SIMPLEX, 0.5, (110, 110, 110), 1,
                                cv2.LINE_AA)

    def _tutor_panel_rect(self, w: int, h: int, keys: list) -> tuple:
        """Where the tutor panel goes, chosen to avoid the keyboard and the HUD.

        The keyboard is a full-width strip, so the free space is above or below
        it. Lay the panel out on the side away from the HUD (top-left).
        """
        kb_top = min(k.rect[1] for k in keys) if keys else 0
        kb_bottom = max(k.rect[1] + k.rect[3] for k in keys) if keys else h
        pw = min(460, w - 16)
        ph = 148
        if self.position == "bottom":
            px, py = w - pw - 8, kb_top - ph - 8      # above the keys, right side
        else:
            px, py = 8, kb_bottom + 8                 # below the keys, left side
        px = max(4, min(px, w - pw - 4))
        py = max(4, min(py, h - ph - 4))
        return px, py, pw, ph

    def _draw_tutor(self, img, keys: list):
        """Show the tutor: mark the next key(s) to play and keep score.

        Placed in whichever part of the frame the keyboard is NOT using, so it
        never covers the keys you are aiming at.
        """
        if not self.learn or not self.lesson:
            return
        h, w = img.shape[:2]
        now = time.time()
        step = self._step()
        by_label = {k.label: k for k in keys}

        # pulsing marker on the keys that should be played next
        if step and not self.learn_done_at:
            pulse = 2 + int(2 * (1 + math.sin(now * 6)))
            for n in step.notes:
                k = by_label.get(n)
                if not k:
                    continue
                x, y, kw, kh = k.rect
                cv2.rectangle(img, (x + 1, y + 1), (x + kw - 1, y + kh - 1),
                              (0, 210, 255), pulse + 1)
                size = cv2.getTextSize(n, cv2.FONT_HERSHEY_SIMPLEX, 0.7, 2)[0]
                tx = int(x + (kw - size[0]) / 2)
                ty = max(20, y - 8)
                cv2.putText(img, n, (tx, ty), cv2.FONT_HERSHEY_SIMPLEX, 0.7,
                            (0, 210, 255), 2, cv2.LINE_AA)

        px, py, pw, ph = self._tutor_panel_rect(w, h, keys)
        self._panel(img, px, py, px + pw, py + ph, alpha=0.55)

        total = len(self.lesson.steps)
        next_txt = " ".join(step.notes) if step else "-"
        lines = [
            (f"LEARN: {self.lesson.display}", (0, 255, 200)),
            (f"{self.lesson.difficulty}  {self.lesson.tempo} BPM   "
             f"note {min(self.learn_index + 1, total)}/{total}", (230, 230, 230)),
            (f"next: {next_txt}", (0, 210, 255)),
            (f"right {self.learn_hits}   wrong {self.learn_misses}", (200, 200, 200)),
            ("d hear it  r restart  [ ] song  k skip  l stop", (150, 150, 150)),
        ]
        if self.learn_done_at and now - self.learn_done_at < 6:
            lines[2] = ("SONG COMPLETE!", (0, 255, 120))
        elif self.learn_done_at:
            lines[2] = ("finished - r to play again", (0, 255, 120))

        for i, (text, colour) in enumerate(lines):
            cv2.putText(img, text, (px + 12, py + 28 + i * 26),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.62 if i else 0.68,
                        colour, 2 if i == 0 else 1, cv2.LINE_AA)

        # a quick red flash when a wrong note is played
        if now - self.learn_flash < 0.25:
            cv2.rectangle(img, (0, 0), (w - 1, h - 1), (0, 0, 200), 6)

    def _panel(self, img, x0: int, y0: int, x1: int, y1: int, alpha: float = 0.45):
        """Darken a rectangle so overlaid text stays readable on any position."""
        h, w = img.shape[:2]
        x0, y0 = max(0, x0), max(0, y0)
        x1, y1 = min(w, x1), min(h, y1)
        if x1 <= x0 or y1 <= y0:
            return
        roi = img[y0:y1, x0:x1]
        cv2.addWeighted(roi, 1.0 - alpha, np.zeros_like(roi), alpha, 0, dst=roi)

    def _draw_hud(self, img, keys: list):
        h, w = img.shape[:2]
        now = time.time()
        dt = now - self.last_frame_time
        self.last_frame_time = now
        if dt > 0:
            self.fps = 0.9 * self.fps + 0.1 * (1.0 / dt)

        lat = f"  audio {self.audio.latency_ms:.0f} ms" if self.audio.latency_ms else ""
        active = [k.label for k in keys if (now - k.highlight) < 0.3]
        voices = len(self.audio.voices)
        line1 = (f"FPS: {self.fps:.0f}  track {self.detect_ms:.0f} ms{lat}"
                 f"  voices: {voices}"
                 + ("  [LEARN]" if self.learn else "")
                 + ("  [MUTED]" if self.audio.muted else ""))
        line2 = ("playing: " + " ".join(active)) if active else None

        tw = cv2.getTextSize(line1, cv2.FONT_HERSHEY_SIMPLEX, 0.6, 2)[0][0]
        if line2:
            tw = max(tw, cv2.getTextSize(line2, cv2.FONT_HERSHEY_SIMPLEX, 0.6, 2)[0][0])
        self._panel(img, 4, 4, tw + 22, 74 if line2 else 44)
        cv2.putText(img, line1, (10, 28), cv2.FONT_HERSHEY_SIMPLEX, 0.6,
                    (0, 255, 120), 2, cv2.LINE_AA)
        if line2:
            cv2.putText(img, line2, (10, 56), cv2.FONT_HERSHEY_SIMPLEX, 0.6,
                        (0, 200, 255), 2, cv2.LINE_AA)

        for finger in self.fingers.values():
            if finger.active and finger.pressed_key is not None:
                cv2.circle(img, (finger.x, finger.y), 13, (0, 0, 255), 3)
                cv2.circle(img, (finger.x, finger.y), 4, (0, 0, 255), -1)
            elif finger.active:
                cv2.circle(img, (finger.x, finger.y), 8, (0, 255, 0), 2)

        # In Learn mode the tutor panel carries the controls, so don't stack the
        # generic help on top of it.
        if self.show_help and not self.learn:
            lines = [
                "Hold your hands up to the camera. Press keys with your fingertips.",
                "ESC/q quit  m mute  space pause  p move keys  h help",
                f"keyboard position: {self.position}   (p cycles it)",
            ]
            # keep the help clear of whichever strip the keyboard sits in
            if self.position == "bottom":
                base_y = 96
            else:
                base_y = h - 76
            self._panel(img, 4, base_y - 26, 640, base_y + 24 * len(lines))
            for i, line in enumerate(lines):
                cv2.putText(img, line, (10, base_y + i * 24),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.55, (255, 255, 255), 1,
                            cv2.LINE_AA)

    def _detect(self, frame_bgr, ts_ms: int):
        rgb = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2RGB)
        mp_image = mp.Image(image_format=mp.ImageFormat.SRGB,
                            data=np.ascontiguousarray(rgb))
        return self.landmarker.detect_for_video(mp_image, ts_ms)

    def run(self):
        if not self.cap.isOpened():
            print("ERROR: could not open camera 0. Try: python air_piano.py --camera 1")
            return 1

        window = "Bipbop  (ESC to quit)"
        cv2.namedWindow(window, cv2.WINDOW_NORMAL)
        # Type a song name in this console at any time to load it (AI lookup).
        threading.Thread(target=self._stdin_listener, daemon=True).start()
        try:
            while True:
                ok, frame = self.cap.read()
                if not ok:
                    print("ERROR: failed to read from camera.")
                    break
                # a song requested by the console listener is picked up here,
                # so a slow lookup never stalls the video
                if self._pending_lesson is not None:
                    self.set_lesson(self._pending_lesson)
                    self._pending_lesson = None
                    self.learn = True
                frame = cv2.flip(frame, 1)  # mirror: it feels natural
                h, w = frame.shape[:2]
                keys = self._layout(w, h)
                self._keys = keys  # used by learn_demo() from its own thread

                for f in self.fingers.values():
                    f.active = False

                detected = []
                if not self.paused:
                    ts_ms = max(int(time.monotonic() * 1000), self._last_ts_ms + 1)
                    self._last_ts_ms = ts_ms
                    t0 = time.perf_counter()
                    result = self._detect(frame, ts_ms)
                    self.detect_ms = (time.perf_counter() - t0) * 1000
                    if result.hand_landmarks:
                        for hand_i, hand_lms in enumerate(result.hand_landmarks):
                            self._process_fingers(keys, hand_lms, hand_i, w, h)
                            detected.append(hand_lms)

                for f in self.fingers.values():
                    if not f.active:
                        f.pressed_key = None

                # Keyboard first, then hands over it: with the keyboard in the
                # middle of the frame you can still see your fingertips land.
                self._draw_keys(frame, keys)
                self._draw_tutor(frame, keys)
                for hand_lms in detected:
                    drawing_utils.draw_landmarks(
                        frame, hand_lms, HandLandmarksConnections.HAND_CONNECTIONS,
                        drawing_styles.get_default_hand_landmarks_style(),
                        drawing_styles.get_default_hand_connections_style(),
                    )
                self._draw_hud(frame, keys)
                cv2.imshow(window, frame)

                key = cv2.waitKey(1) & 0xFF
                if key in (27, ord("q")):
                    break
                elif key == ord("m"):
                    self.audio.muted = not self.audio.muted
                elif key == ord(" "):
                    self.paused = not self.paused
                elif key == ord("h"):
                    self.show_help = not self.show_help
                elif key == ord("p"):
                    i = KEYBOARD_POSITIONS.index(self.position)
                    self.position = KEYBOARD_POSITIONS[(i + 1) % len(KEYBOARD_POSITIONS)]
                    print(f"keyboard position: {self.position}")
                elif key == ord("l"):
                    self.learn = not self.learn
                    if self.learn and self.lesson is None:
                        self.load_default_song()
                    print(f"[tutor] learn mode {'on' if self.learn else 'off'}")
                elif key in (ord("["), ord("]")):
                    if self.lesson is None:
                        self.load_default_song()
                    else:
                        self.cycle_song(-1 if key == ord("[") else 1)
                    if self.lesson:
                        print(f"[tutor] song: {self.lesson.display}")
                elif key == ord("d"):
                    self.learn_demo()
                elif key == ord("r"):
                    if self.lesson:
                        self.learn_index = 0
                        self.learn_correct = set()
                        self.learn_hits = 0
                        self.learn_misses = 0
                        self.learn_done_at = 0.0
                        print("[tutor] restarted")
                elif key == ord("k"):
                    if self.learn and self.lesson:
                        self.learn_correct = set()
                        self._advance()
        finally:
            self._closing = True
            self.cap.release()
            cv2.destroyAllWindows()
            self.audio.close()
            self.landmarker.close()
        return 0


# ------------------------------------------------------------------ main ----

def main():
    import argparse

    ap = argparse.ArgumentParser(description="Bipbop - play piano in the air with your fingertips")
    ap.add_argument("--camera", type=int, default=0, help="camera index (default 0)")
    ap.add_argument("--octaves", type=int, default=2, help="number of octaves (default 2)")
    ap.add_argument("--audio-device", default=None,
                    help="output device index or part of its name (see --list-audio)")
    ap.add_argument("--blocksize", type=int, default=256,
                    help="audio block size; smaller = lower latency (default 256)")
    ap.add_argument("--position", choices=KEYBOARD_POSITIONS, default="center",
                    help="where the keyboard sits: center (default), top or bottom. "
                         "Cycle it live with the p key.")
    ap.add_argument("--width", type=int, default=0,
                    help="ask the camera for this frame width (0 = camera default). "
                         "1280 makes the keys bigger/easier to hit on most webcams.")
    ap.add_argument("--height", type=int, default=0,
                    help="ask the camera for this frame height (0 = camera default)")
    ap.add_argument("--shared", action="store_true",
                    help="don't use WASAPI exclusive mode (keeps other apps' audio alive)")
    ap.add_argument("--list-audio", action="store_true", help="list audio devices and exit")
    ap.add_argument("--learn", action="store_true",
                    help="start in Learn mode (the tutor guides you through a song)")
    ap.add_argument("--song", default=None,
                    help="learn this song (built-in name, or any name to look up "
                         "with a free LLM). Implies Learn mode.")
    ap.add_argument("--list-songs", action="store_true",
                    help="list the built-in and saved songs, and exit")
    args = ap.parse_args()

    if args.list_audio:
        list_audio_devices()
        return

    if args.list_songs:
        for s in tutor.list_songs():
            tag = "  (saved)" if s["source"] == "songbook" else ""
            print(f"  {s['title']:34} {s['difficulty']:13} {s['tempo']:3} BPM  "
                  f"{s['length']:2} notes{tag}")
        status = tutor.llm_status()
        if status["enabled"]:
            print(f"\n  AI song lookup ready via: {', '.join(status['available'])}")
            print(f"    {status['hint']}")
        else:
            print(f"\n  AI song lookup: {status['hint']}")
        return

    print("Starting up ...")
    piano = Bipbop(camera=args.camera, octaves=args.octaves,
                     audio_device=args.audio_device, blocksize=args.blocksize,
                     exclusive=not args.shared, position=args.position,
                     width=args.width, height=args.height,
                     song=args.song, learn=args.learn or bool(args.song))
    print(f"Keyboard position: {piano.position} (press p in the app to cycle)")
    print(piano.camera_report())
    print(f"Audio: {piano.audio.backend}")
    if piano.audio.device_name:
        print(f"  device: {piano.audio.device_name}")
    if piano.audio.latency_ms:
        print(f"  output latency: {piano.audio.latency_ms} ms (lower is better)")
    # Render every key's sound once now, so the first presses are instant
    ok, frame = piano.cap.read()
    h, w = (frame.shape[:2] if ok else (720, 1280))
    piano._layout(w, h)
    if piano.learn and piano.lesson is None:
        piano.load_default_song()
    if piano.learn:
        if piano.lesson:
            print(f"Learn mode: '{piano.lesson.display}' "
                  f"({piano.lesson.length} notes). Press d to hear it, then play along.")
            print("  keys: r restart  d hear it  [ ] change song  k skip  l exit learn mode")
        print("  tip: type any song name here and press Enter to load it (AI lookup).")
    else:
        print("Ready! Look at the camera and play. (Press l for Learn mode.)")
    sys.exit(piano.run())


if __name__ == "__main__":
    main()
