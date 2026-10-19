import json
import os
import sys
import tempfile

# run from anywhere: put the project root (one level up) on the path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
# keep the tests offline and deterministic: never call a real model
os.environ["AIR_PIANO_LLM"] = "off"

import tutor
import tunes

FAILS = []


def ok(label, got, want):
    """One check. Anything that does not match fails the suite."""
    same = got == want
    if not same:
        FAILS.append(label)
    print(f"  {label:30} {'ok' if same else 'FAIL'}  got {got!r}"
          + ("" if same else f"  want {want!r}"))
    return same

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
songs = [s for s in tutor.list_songs() if s["source"] == "builtin"]
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

print("\n=== 9. ABC NOTATION: the free tune archives' format ===")
jig = """X:1
T:Jig test
L:1/8
Q:1/4=120
K:G
|:BGG DGG|BGB dcB|! cAA EAA|cAc edc|]
"""
data = tunes.parse_abc(jig)
ok("title", data["title"], "Jig test")
ok("tempo", data["tempo"], 120)
ok("note count", len(data["steps"]), 24)
ok("first bar", [s["notes"][0] for s in data["steps"][:6]],
   ["B4", "G4", "G4", "D4", "G4", "G4"])
ok("last bar", [s["notes"][0] for s in data["steps"][-6:]],
   ["C5", "A4", "C5", "E5", "D5", "C5"])
ok("key G (F#)", tunes.key_accidentals("G"), {"F": "#"})
ok("key F (Bb)", tunes.key_accidentals("F"), {"B": "b"})
ok("key Bb (Bb Eb)", tunes.key_accidentals("Bb"), {"B": "b", "E": "b"})
ok("key Edor (F# C#)", tunes.key_accidentals("Edor"), {"F": "#", "C": "#"})
ok("key Am (none)", tunes.key_accidentals("Am"), {})
ok("accidentals + rest", [s["notes"][0] for s in tunes.parse_abc("K:D\nA ^A =A z2")["steps"]],
   ["A4", "A#4", "A4"])
ok("octave marks", [s["notes"][0] for s in tunes.parse_abc("K:C\nC, c c' C")["steps"]],
   ["C3", "C5", "C6", "C4"])
ok("chord held", tunes.parse_abc("K:C\n[CEG]2")["steps"],
   [{"notes": ["C4", "E4", "G4"], "beats": 1.0}])
ok("grace notes dropped", [s["notes"][0] for s in tunes.parse_abc("K:C\n{g}A2 {B}c2")["steps"]],
   ["A4", "C5"])
ok("note lengths", [s["beats"] for s in tunes.parse_abc("K:C\nL:1/4\nC C/ C/2 C3/2 C4")["steps"]],
   [1.0, 0.5, 0.5, 1.5, 4.0])
ok("body-only abc (no headers)",
   [s["notes"][0] for s in tunes.parse_abc("|:BGG DGG|", key="Gmajor")["steps"]],
   ["B4", "G4", "G4", "D4", "G4", "G4"])
ok("site match: the tune itself",
   tunes.name_matches("The Irish Washerwoman", "The Irish Washerwoman"), True)
ok("site match: a tune type is not a name",
   tunes.name_matches("Morrison's Jig", "Morrison's"), True)
ok("site match: loose search results are refused",
   tunes.name_matches("Blinding Lights",
                      "St. Stephen's Day Storm! No Lights And No Cold Beer"), False)
ok("first and second endings", [s["notes"][0] for s in
   tunes.parse_abc("K:C\n|:C4 [1 D4 :| [2 E4 ||")["steps"]], ["C4", "D4", "E4"])
ok("inline header is not a note", [s["notes"][0] for s in
   tunes.parse_abc("K:C\nC4 [K:G] D4")["steps"]], ["C4", "D4"])
ok("thick bar line", [s["notes"][0] for s in
   tunes.parse_abc("K:C\nC4 [| D4 |]")["steps"]], ["C4", "D4"])

print("\n=== 10. SONGBOOK: songs/ is used before the cache and the model ===")
book = tempfile.mkdtemp()
tutor.SONGBOOK_DIR = book
files = {
    "morrison.abc": "T:Morrison's Jig\nK:Edor\n|:BEG BGE|\n",
    "melody.txt": "# Hand Written\nC4 D4 E4:2 | F4\n",
    "broken.abc": "T:Broken\nK:G\n||||\n",                     # no notes at all
    "notes.json": json.dumps({"title": "Json Song", "steps": [{"notes": ["G4"], "beats": 2}]}),
    "readme.md": "not a song",
}
for name, text in files.items():
    with open(os.path.join(book, name), "w", encoding="utf-8") as fh:
        fh.write(text)
lessons = tutor.songbook_lessons()
ok("three good files read", sorted(lessons), ["hand-written", "json-song", "morrison-s-jig"])
ok("abc notes", [s.notes[0] for s in lessons["morrison-s-jig"].steps],
   ["B4", "E4", "G4", "B4", "G4", "E4"])
ok("txt notes", [s.notes[0] for s in lessons["hand-written"].steps], ["C4", "D4", "E4", "F4"])
ok("json notes", [s.notes[0] for s in lessons["json-song"].steps], ["G4"])
ok("source is songbook", lessons["morrison-s-jig"].source, "songbook")
ok("broken file skipped", sorted(lessons).count("broken"), 0)
ok("one word finds it", tutor.find_lesson("morrison", allow_llm=False).title,
   "Morrison's Jig")
ok("tune type does not get in the way",
   tutor.find_lesson("Morrison's Jig", allow_llm=False).title, "Morrison's Jig")
ok("find_lesson uses it", tutor.find_lesson("Morrison's Jig", allow_llm=False).source,
   "songbook")
ok("list_songs marks it", [s["source"] for s in tutor.list_songs()
                           if s["slug"] == "morrison-s-jig"], ["songbook"])
low = tunes.parse_abc("T:Low\nK:G\nG2 B,2")          # B, sits below the keyboard
folded = [s.notes[0] for s in tutor.validate_lesson(low, fold=True).steps]
ok("low tune still playable", len(folded), 2)
ok("and every note keeps its pitch class (same key)",
   [tutor.note_to_midi(n) % 12 for n in folded],
   [tutor.note_to_midi("G4") % 12, tutor.note_to_midi("B3") % 12])
ok("as written it would not fit",
   any(tutor.note_to_midi(n) < tutor.KEYBOARD_LO for n in ("G4", "B3")), True)

print("\n" + ("all tutor checks passed" if not FAILS else f"FAILURES: {', '.join(FAILS)}"))
sys.exit(1 if FAILS else 0)
