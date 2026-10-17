import json
import os
import sys
import tempfile

# run from anywhere: put the project root (one level up) on the path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
# keep the tests offline and deterministic: never call a real model
os.environ["AIR_PIANO_LLM"] = "off"

import tutor

print("=== 1. NOTE PARSING ===")
cases = [("c4", "C4"), ("C#4", "C#4"), ("Db4", "C#4"), ("Bb3", "A#3"),
         ("E5", "E5"), ("g#5", "G#5"), ("H4", None), ("C", None), ("C9", "C9")]
for raw, want in cases:
    got = tutor.parse_note(raw)
    flag = "ok" if got == want else "FAIL"
    print(f"  {raw!r:7} -> {got!r:7} (want {want!r}) {flag}")

print("\n=== 2. FREQUENCIES (spot-check against known pitches) ===")
for name, want in (("A4", 440.0), ("C4", 261.6256), ("C5", 523.2511), ("C6", 1046.502)):
    got = tutor.note_freq(name)
    print(f"  {name}: {got:8.3f} Hz (want {want:8.3f}) "
          f"{'ok' if abs(got - want) < 0.05 else 'FAIL'}")

print("\n=== 3. BUILT-IN LIBRARY: every song playable on C4..C6 ===")
songs = tutor.list_songs()
print(f"  {len(songs)} built-in songs")
bad = []
for s in songs:
    lesson = tutor.BUILTIN[s["slug"]]
    midis = [tutor.note_to_midi(n) for st in lesson.steps for n in st.notes]
    lo, hi = min(midis), max(midis)
    if lo < tutor.KEYBOARD_LO or hi > tutor.KEYBOARD_HI:
        bad.append(s["title"])
    print(f"  {s['title']:32} {s['length']:2} steps  "
          f"range {tutor.midi_to_note(lo):4}-{tutor.midi_to_note(hi):4}  "
          f"{s['difficulty']}")
print("  out of range:", bad or "none")

print("\n=== 4. FUZZY TITLE MATCHING ===")
for q in ("twinkle", "Twinkle Twinkle Little Star", "ode to joy", "jingle",
          "mary had a little", "fur elise", "fur  elise!!", "happy bday",
          "some song that does not exist"):
    lesson = tutor.get_builtin(q)
    print(f"  {q!r:34} -> {lesson.title if lesson else 'not found'}")

print("\n=== 5. VALIDATE: bad model output is cleaned or rejected ===")
tests = {
    "flats + weird spacing": {"title": "X", "tempo": 999, "steps": [
        {"notes": ["Db4"], "beats": 1}, {"notes": "Eb4", "beats": 0.1}]},
    "too high -> transpose down": {"title": "High", "steps": [
        {"notes": ["C7"], "beats": 1}, {"notes": ["E7"], "beats": 1}]},
    "chord": {"title": "Chord", "steps": [{"notes": ["C4", "E4", "G4"], "beats": 4}]},
    "empty": {"title": "Nope", "steps": []},
    "garbage notes": {"title": "Junk", "steps": [{"notes": ["Z9"]}]},
}
for name, data in tests.items():
    try:
        lesson = tutor.validate_lesson(data)
        print(f"  {name:28} -> OK  tempo={lesson.tempo} "
              f"steps={lesson.length} notes={lesson.used_notes()}")
    except ValueError as exc:
        print(f"  {name:28} -> rejected: {exc}")

print("\n=== 6. JSON EXTRACTION from messy model replies ===")
replies = [
    '{"title":"A","steps":[{"notes":["C4"],"beats":1}]}',
    '```json\n{"title":"B","steps":[{"notes":["D4"],"beats":1}]}\n```',
    'Sure! Here is the lesson:\n{"title":"C","steps":[{"notes":["E4"],"beats":1}]}\nHope that helps!',
    'no json here at all',
]
for r in replies:
    try:
        obj = tutor.extract_json(r)
        print(f"  -> {obj.get('title')!r}")
    except ValueError as exc:
        print(f"  -> rejected: {exc}")

print("\n=== 7. CACHE ROUND-TRIP ===")
tmp = tempfile.mkdtemp()
tutor.CACHE_DIR = tmp
lesson = tutor.validate_lesson({"title": "Cache Test", "tempo": 99, "steps": [
    {"notes": ["C4"], "beats": 1}, {"notes": ["G4"], "beats": 0.5}]})
tutor.write_cache(lesson)
back = tutor.read_cache("Cache Test")
print(f"  saved + reloaded: {back.title} / {back.length} steps / tempo {back.tempo}")
print("  find_lesson uses cache (source should be 'cache'):",
      tutor.find_lesson("Cache Test", allow_llm=False).source)

print("\n=== 8. NO LLM -> clear error, built-ins still work ===")
for var in ("GEMINI_API_KEY", "GOOGLE_API_KEY", "GROQ_API_KEY", "OPENROUTER_API_KEY"):
    os.environ.pop(var, None)
print("  detected providers:", tutor.available_providers())
try:
    tutor.find_lesson("Bohemian Rhapsody", allow_llm=False)
except LookupError as exc:
    print("  lookup error:", str(exc)[:110], "...")
print("  partial name resolves to built-in:", tutor.find_lesson("twinkle").title)
print("  llm_status:", {k: v for k, v in tutor.llm_status().items() if k != 'hint'})
