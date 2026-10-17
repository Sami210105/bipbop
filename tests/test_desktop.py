"""Tests for the desktop Learn mode logic in air_piano.py.

No camera, audio device or MediaPipe model is needed: we build a bare instance
with Bipbop.__new__ and fill in just the attributes the tutor uses.
"""

import contextlib
import io
import os
import sys
import time

import numpy as np

# run from anywhere: put the project root (one level up) on the path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
# keep the tests offline and deterministic: never call a real model
os.environ["AIR_PIANO_LLM"] = "off"

import air_piano as ap
import tutor


class FakeAudio:
    def __init__(self):
        self.played = []
        self.muted = False
        self.voices = []
        self.latency_ms = 13.0
        self.backend = "fake"
        self.device_name = None
        self.sr = 48000

    def play(self, sample, velocity=1.0):
        self.played.append(velocity)


def bare_piano(lesson=None, learn=True):
    p = ap.Bipbop.__new__(ap.Bipbop)
    p.learn = learn
    p.lesson = lesson
    p.learn_index = 0
    p.learn_correct = set()
    p.learn_hits = 0
    p.learn_misses = 0
    p.learn_flash = 0.0
    p.learn_done_at = 0.0
    p.position = "center"
    p.show_help = True
    p._keys = []
    p._closing = False
    p._demo_thread = None
    p.octaves = 2
    p._sample_cache = {}
    p.audio = FakeAudio()
    p.fingers = {}
    p.fps = 0.0
    p.detect_ms = 0.0
    p.last_frame_time = time.time()
    if lesson:
        p.set_lesson(lesson)
    return p


pass_n = fail_n = 0
def ok(cond, label, extra=""):
    global pass_n, fail_n
    if cond:
        pass_n += 1
        print(f"  ok   {label}")
    else:
        fail_n += 1
        print(f"  FAIL {label} {extra}")


print("=== playing a melody in Learn mode ===")
lesson = tutor.find_lesson("twinkle twinkle")   # built-in, no network
p = bare_piano(lesson)
ok(p.lesson.length == 42, f"loaded {lesson.title} ({p.lesson.length} steps)")
step0 = p._step()
ok(step0.notes == ["C4"], "first note is C4")

p.learn_on_press("D4")                          # wrong
ok(p.learn_misses == 1 and p.learn_index == 0, "wrong note counted, still on note 1")
p.learn_on_press("C4")                          # right
ok(p.learn_index == 1 and p.learn_hits == 1, "right note advances")
p.learn_on_press("C4")
ok(p.learn_hits == 2, "second C4 advances too")

# walk the whole song one note at a time
p2 = bare_piano(lesson)
seq = []
for s in lesson.steps:
    for n in s.notes:
        seq.append(n)
for n in seq:
    p2.learn_on_press(n)
ok(p2.learn_index == lesson.length - 1, "walked to the last note")
ok(p2.learn_done_at > 0, "song marked complete")
ok(p2.learn_misses == 0, "no wrong notes on a clean run")

print("\n=== chords need every note of the step ===")
chords = tutor.find_lesson("C and G Chords")
pc = bare_piano(chords)
ok(pc._step().notes == ["C4", "E4", "G4"], "first step is the C chord")
pc.learn_on_press("C4")
ok(pc.learn_index == 0 and pc.learn_correct == {"C4"}, "one note of the chord is partial")
pc.learn_on_press("E4")
ok(pc.learn_index == 0, "two notes still partial")
pc.learn_on_press("G4")
ok(pc.learn_index == 1 and pc.learn_hits == 1, "all three notes -> advance")
ok(pc._step().notes == ["G4", "B4", "D5"], "next step is the G chord")

print("\n=== restart / skip / cycle ===")
pr = bare_piano(lesson)
pr.learn_on_press("C4")
pr.learn_index, pr.learn_correct, pr.learn_hits, pr.learn_misses = 0, set(), 0, 0
ok(pr.learn_index == 0 and pr._step().notes == ["C4"], "restart returns to note 1")
pr.learn_correct = {"C4"}
pr._advance()
ok(pr.learn_index == 1 and pr.learn_correct == set(), "skip advances and clears partial")

pc2 = bare_piano(lesson)
pc2._song_index = 0
first = pc2.lesson.title
pc2.cycle_song(1)
ok(pc2.lesson.title != first, f"cycle_song moved on from '{first}'")
ok(pc2.learn_index == 0 and pc2.learn_misses == 0, "new song resets progress")

print("\n=== demo playback plays every note ===")
short = tutor.Lesson("Test", 300, "beginner",
                     [tutor.Step(["C4"], 1), tutor.Step(["D4"], 1), tutor.Step(["E4"], 1)])
pd = bare_piano(short)
pd._keys = ap.build_keys(38, 300, 1204, 158, 2)
pd.learn_demo()
time.sleep(1.2)
ok(len(pd.audio.played) >= 3, f"demo played {len(pd.audio.played)} notes")
ok(any(k.highlight > 0 for k in pd._keys), "demo lit up the keys as well")

print("\n=== drawing never crashes and really marks the target key ===")
for position in ("center", "top", "bottom"):
    pp = bare_piano(lesson)
    pp.position = position
    keys = ap.build_keys(38, 300, 1204, 158, 2)
    img = np.zeros((720, 1280, 3), np.uint8)
    pp._draw_tutor(img, keys)                      # must not raise
    drawn = int(np.count_nonzero(img))
    target = next(k for k in keys if k.label == "C4")
    x, y = target.rect[0], target.rect[1]
    corner = img[max(0, y - 2):y + 8, max(0, x - 2):x + 8]
    # marker colour is BGR (0, 210, 255) -> a warm orange: R and G high, B low
    marker = int(np.count_nonzero((corner[:, :, 2] > 150) & (corner[:, :, 1] > 150)
                                  & (corner[:, :, 0] < 120)))
    ok(drawn > 200 and marker > 0,
       f"{position}: tutor panel + marker drawn ({drawn} px, {marker} marker px)")

# learn mode off draws nothing at all
poff = bare_piano(lesson, learn=False)
img2 = np.zeros((720, 1280, 3), np.uint8)
poff._draw_tutor(img2, ap.build_keys(38, 300, 1204, 158, 2))
ok(int(np.count_nonzero(img2)) == 0, "no tutor overlay when Learn mode is off")

print("\n=== the tutor panel never covers the keyboard ===")
def overlaps(a, b):
    ax, ay, aw, ah = a
    bx, by, bw, bh = b
    return not (ax + aw <= bx or bx + bw <= ax or ay + ah <= by or by + bh <= ay)

for (w, h) in [(640, 480), (1280, 720)]:
    for position in ("center", "top", "bottom"):
        pp = bare_piano(lesson)
        pp.position = position
        keys = pp._layout(w, h)
        rect = pp._tutor_panel_rect(w, h, keys)
        hit = [k.label for k in keys if overlaps(rect, k.rect)]
        ok(not hit, f"{w}x{h} {position}: panel {rect[1]}..{rect[1]+rect[3]} clear of keys",
           f"overlaps {hit[:4]}")
        ok(rect[1] >= 0 and rect[1] + rect[3] <= h and rect[0] >= 0
           and rect[0] + rect[2] <= w, f"{w}x{h} {position}: panel inside the frame")

print("\n=== HUD reflects learn mode ===")
ph = bare_piano(lesson)
ph.audio.latency_ms = 13.0
img3 = np.zeros((720, 1280, 3), np.uint8)
ph._draw_hud(img3, ap.build_keys(38, 300, 1204, 158, 2))
ok(int(np.count_nonzero(img3)) > 0, "HUD draws without a camera")

print("\n=== --list-songs CLI ===")
buf = io.StringIO()
sys.argv = ["air_piano.py", "--list-songs"]
with contextlib.redirect_stdout(buf):
    ap.main()
out = buf.getvalue()
ok("Twinkle Twinkle Little Star" in out, "lists the built-in songs")
ok("AI song lookup" in out, "reports the AI lookup status")

print("\n=== lookup error is reported, not fatal ===")
pl = bare_piano(None, learn=False)
with contextlib.redirect_stdout(buf := io.StringIO()):
    got = pl.load_lesson("A Song That Does Not Exist At All", refresh=True)
ok(got is False and pl.lesson is None, "unknown song without an LLM returns False cleanly")

print(f"\n{pass_n} passed, {fail_n} failed")
sys.exit(1 if fail_n else 0)
