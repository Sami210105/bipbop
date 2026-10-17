"""Run the real Bipbop.run() loop with a stubbed camera, hands and audio.

This is the integration test: it executes the actual frame loop (layout, detect,
finger processing, tutor scoring, all the drawing, key handling) without a
camera, so wiring mistakes show up here instead of on the user's screen.
"""

import os
import sys
from types import SimpleNamespace

import numpy as np

# run from anywhere: put the project root (one level up) on the path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
# keep the tests offline and deterministic: never call a real model
os.environ["AIR_PIANO_LLM"] = "off"

import air_piano as ap
import tutor

W, H = 640, 480


class FakeCap:
    def __init__(self, frames=4):
        self.left = frames
        self.released = False

    def isOpened(self):
        return True

    def read(self):
        if self.left <= 0:
            return False, None
        self.left -= 1
        return True, np.zeros((H, W, 3), np.uint8)

    def set(self, *_):
        pass

    def release(self):
        self.released = True


class FakeAudio:
    def __init__(self):
        self.played = []
        self.muted = False
        self.voices = []
        self.latency_ms = 13.0
        self.backend = "fake"
        self.device_name = None
        self.sr = 48000
        self.closed = False

    def play(self, sample, velocity=1.0):
        self.played.append(velocity)

    def close(self):
        self.closed = True


def landmarks_at(x_norm, y_norm):
    """21 hand landmarks; the thumb tip (index 4) sits on the given point."""
    lms = [SimpleNamespace(x=0.5, y=0.5, visibility=1.0, presence=1.0) for _ in range(21)]
    lms[4] = SimpleNamespace(x=x_norm, y=y_norm, visibility=1.0, presence=1.0)
    return lms


class FakeLandmarker:
    def __init__(self, points):
        self.points = points          # list of (x_norm, y_norm) to return per frame
        self.i = 0
        self.closed = False

    def detect_for_video(self, _img, _ts):
        if self.i < len(self.points):
            x, y = self.points[self.i]
            self.i += 1
            return SimpleNamespace(hand_landmarks=[landmarks_at(x, y)])
        return SimpleNamespace(hand_landmarks=[])

    def close(self):
        self.closed = True


def build(frames=4, points=None, learn=True, song="twinkle"):
    p = ap.Bipbop.__new__(ap.Bipbop)
    p.octaves = 2
    p.position = "center"
    p.cam_size = (0, 0)
    p._last_ts_ms = 0
    p.fingers = {i: ap.Finger() for i in range(10)}
    p.show_help = True
    p.paused = False
    p.last_frame_time = ap.time.time()
    p.fps = 0.0
    p.detect_ms = 0.0
    p._sample_cache = {}
    p.learn = learn
    p.lesson = tutor.find_lesson(song) if song else None
    p.learn_index = 0
    p.learn_correct = set()
    p.learn_hits = 0
    p.learn_misses = 0
    p.learn_flash = 0.0
    p.learn_done_at = 0.0
    p.song_spec = song
    p._song_index = -1
    p._pending_lesson = None
    p._pending_song = None
    p._closing = False
    p._demo_thread = None
    p._keys = None
    p.cap = FakeCap(frames)
    p.audio = FakeAudio()
    p.landmarker = FakeLandmarker(points or [])
    return p


def aim_at(key):
    """Normalised coords of the centre of a key, for a 640x480 frame."""
    x, y, w, h = key.rect
    return ((x + w / 2) / W, (y + h / 2) / H)


fail_n = 0
def ok(cond, label, extra=""):
    global fail_n
    print(("  ok   " if cond else "  FAIL ") + label + ("" if cond else f" {extra}"))
    if not cond:
        fail_n += 1


# --- stub out the bits that need real hardware / a window -------------------
ap.cv2.namedWindow = lambda *a, **k: None
ap.cv2.imshow = lambda *a, **k: None
ap.cv2.destroyAllWindows = lambda *a, **k: None
ap.cv2.waitKey = lambda *a, **k: 27          # quit immediately each frame
ap.Bipbop._stdin_listener = lambda self: None   # don't read the test's stdin


print("=== the frame loop runs end to end (learn mode on) ===")
p = build(frames=4, points=[])
try:
    rc = p.run()
    ok(rc == 0, "run() returned 0", f"got {rc}")
except Exception as exc:
    import traceback
    traceback.print_exc()
    ok(False, "run() raised", f"{type(exc).__name__}: {exc}")

ok(p.cap.released and p.audio.closed and p.landmarker.closed, "resources released")
ok(p._keys is not None and len(p._keys) == 25, "keys were laid out for the demo thread")

print("\n=== a fingertip on the first note advances the tutor ===")
# figure out where C4 is for a 640x480 frame
tmp = build(frames=1, points=[], learn=False, song=None)
keys = tmp._layout(W, H)
c4 = next(k for k in keys if k.label == "C4")
px, py = aim_at(c4)

p2 = build(frames=5, points=[(px, py)] * 5, learn=True, song="twinkle")
try:
    p2.run()
except Exception as exc:
    import traceback
    traceback.print_exc()
    ok(False, "run() with a hand raised", f"{type(exc).__name__}: {exc}")
ok(p2.learn_index >= 1, f"learn advanced to note {p2.learn_index + 1}")
ok(p2.learn_hits >= 1, "the correct press was counted as a hit")
ok(len(p2.audio.played) >= 1, "the note actually sounded")

print("\n=== a fingertip on the wrong note is counted wrong ===")
wrong = next(k for k in tmp._layout(W, H) if k.label == "B4")
wp = aim_at(wrong)
p3 = build(frames=5, points=[wp] * 5, learn=True, song="twinkle")
p3.run()
if wrong.label != "C4":
    ok(p3.learn_misses >= 1, f"wrong note ({wrong.label}) recorded ({p3.learn_misses})")
    ok(p3.learn_index == 0, "tutor did not advance on the wrong note")
else:
    ok(False, "test picked C4 by mistake")

print("\n=== Learn mode off: no tutor, notes still play ===")
p4 = build(frames=3, points=[(px, py)] * 3, learn=False, song=None)
p4.run()
ok(p4.learn_index == 0 and p4.learn_hits == 0, "no scoring when Learn mode is off")
ok(len(p4.audio.played) >= 1, "keys still play when Learn mode is off")

print("\n=== a console-requested song is picked up by the loop ===")
p5 = build(frames=3, points=[], learn=False, song=None)
p5._pending_lesson = tutor.find_lesson("ode to joy")
p5.run()
ok(p5.lesson is not None and "Joy" in p5.lesson.title, "pending lesson was loaded")
ok(p5.learn is True, "learning turned on for the requested song")

print(f"\n{'FAILED' if fail_n else 'all run-loop checks passed'}")
sys.exit(1 if fail_n else 0)
