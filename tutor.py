"""Songs, lessons and a free-LLM song lookup for the Bipbop tutor.

This module is deliberately standard-library only. It is used by both the
desktop app (air_piano.py) and the local web server (serve.py), and neither of
those should be forced to import mediapipe/opencv just to read a song.

A "lesson" is a short, ordered list of steps. Each step is one note event: one
key for a melody note, or several keys at once for a chord. Every lesson is
validated to sit inside the app's two-octave keyboard (C4..C6), transposed by
whole octaves if needed.

A song is looked up in this order: a built-in first, then anything saved in the
`songs/` folder (see below), then the on-disk cache, and only then a model.

Usage from the command line:

    python tutor.py --list              # built-in and saved songs
    python tutor.py "some song name"    # print a lesson (built-in or LLM)
    python tutor.py --refresh "song"    # ignore the cache and ask again
    python tutor.py --songbook          # what is saved in songs/
    python tutor.py --fetch "Tune name" # save a traditional tune from thesession.org

The `songs/` folder is the offline songbook: drop in .abc (ABC notation), .txt (a
compact melody line) or .json (this app's lesson format) and the song is exact
and needs no model at all. `--fetch` fills it from thesession.org, a free tune
archive that needs no key.

Environment variables (all optional -- the built-in songs need none):

Put them in a `.env` file next to this module (copy `.env.example`), or set them
in your shell -- a real environment variable wins over the file.

    GEMINI_API_KEY / GOOGLE_API_KEY   free Google AI Studio key
    GROQ_API_KEY                      free Groq key
    OPENROUTER_API_KEY                free OpenRouter key
    AIR_PIANO_LLM                     force a provider: gemini|groq|openrouter|ollama
    AIR_PIANO_OLLAMA_MODEL            local model name (default llama3.2)
    AIR_PIANO_LLM_TIMEOUT             seconds to wait for one provider (default 60;
                                      the last one in the chain gets 180)
    AIR_PIANO_OLLAMA_KEEP_ALIVE       how long Ollama keeps the model in memory
                                      (default 30m; a warm model answers much
                                      faster than a cold one)
"""

from __future__ import annotations

import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field


class UnknownSong(ValueError):
    """The model said it does not know the song - much better than inventing one."""


def _load_dotenv() -> None:
    """Read API keys from a `.env` file next to this module, once at import.

    A real environment variable always wins, so `$env:GEMINI_API_KEY=...` in the
    shell still overrides the file. `.env` is in .gitignore, so a key pasted
    there never gets committed; `.env.example` shows the names to use."""
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")
    try:
        with open(path, "r", encoding="utf-8") as fh:
            lines = fh.readlines()
    except OSError:
        return
    for line in lines:
        line = line.strip()
        if line.startswith("export "):
            line = line[len("export "):].strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        name, _, value = line.partition("=")
        name = name.strip()
        value = value.strip().strip('"').strip("'")
        if name and name not in os.environ:
            os.environ[name] = value


_load_dotenv()

# `tunes` sits next to this module; make sure it can be found however tutor.py
# was imported (as a script, or by serve.py / air_piano.py).
_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)
import tunes  # noqa: E402  (a sibling module, standard-library only)

# ---------------------------------------------------------------- keyboard ----

NOTE_NAMES = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]
WHITE_SEMITONES = {0, 2, 4, 5, 7, 9, 11}

# The bipbop shows two octaves plus a final C: MIDI 60 (C4) .. 84 (C6)
KEYBOARD_LO = 60
KEYBOARD_HI = 84

_FLAT_TO_SHARP = {"DB": "C#", "EB": "D#", "GB": "F#", "AB": "G#", "BB": "A#"}

_NOTE_RE = re.compile(r"^([A-Ga-g])([#b]?)(-?\d)$")


def parse_note(text: str) -> str | None:
    """Normalise many spellings of a note to the app's form, e.g. 'db4' -> 'C#4'."""
    m = _NOTE_RE.match(str(text).strip())
    if not m:
        return None
    letter, accidental, octave = m.group(1).upper(), m.group(2), m.group(3)
    name = letter + ("#" if accidental == "#" else "")
    if accidental == "b":
        name = _FLAT_TO_SHARP.get(letter + "B", "")
        if not name:
            return None
    if name not in NOTE_NAMES:
        return None
    return f"{name}{octave}"


def note_to_midi(name: str) -> int | None:
    n = parse_note(name)
    if n is None:
        return None
    letter = n[:-1]
    octave = int(n[-1])
    return NOTE_NAMES.index(letter) + 12 * (octave + 1)


def midi_to_note(midi: int) -> str:
    return f"{NOTE_NAMES[midi % 12]}{midi // 12 - 1}"


def note_freq(name: str) -> float:
    midi = note_to_midi(name)
    if midi is None:
        raise ValueError(f"bad note: {name!r}")
    return 440.0 * 2 ** ((midi - 69) / 12)


def is_white(name: str) -> bool:
    n = parse_note(name)
    if n is None:
        return False
    return NOTE_NAMES.index(n[:-1]) in WHITE_SEMITONES


def slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", str(text).lower()).strip("-") or "song"


# ----------------------------------------------------------------- lesson ----

@dataclass
class Step:
    """One note event: one key for a melody note, or several for a chord."""
    notes: list
    beats: float = 1.0


@dataclass
class Lesson:
    title: str
    tempo: int = 100           # BPM, one beat = a quarter note
    difficulty: str = "beginner"
    steps: list = field(default_factory=list)
    source: str = "builtin"    # builtin | songbook | cache | llm:<provider>
    part: str = ""             # which passage this is, e.g. "chorus" (empty for built-ins)

    @property
    def length(self) -> int:
        return len(self.steps)

    @property
    def display(self) -> str:
        """'Song (chorus)' - the title with the passage, for titles in the UI."""
        return f"{self.title} ({self.part})" if self.part else self.title

    def used_notes(self) -> list:
        seen = []
        for s in self.steps:
            for n in s.notes:
                if n not in seen:
                    seen.append(n)
        return sorted(seen, key=note_to_midi)

    def transposed(self, semitones: int) -> "Lesson":
        if semitones == 0:
            return self
        steps = [Step([midi_to_note(note_to_midi(n) + semitones) for n in s.notes], s.beats)
                 for s in self.steps]
        return Lesson(self.title, self.tempo, self.difficulty, steps, self.source, self.part)

    def to_dict(self) -> dict:
        return {
            "title": self.title,
            "part": self.part,
            "tempo": self.tempo,
            "difficulty": self.difficulty,
            "source": self.source,
            "length": self.length,
            "notes": self.used_notes(),
            "steps": [{"notes": s.notes, "beats": s.beats} for s in self.steps],
        }


def parse_steps(text: str) -> list:
    """Parse a compact melody string into steps.

    Tokens are space separated; '|' is a cosmetic bar line and is ignored.
    'C4' is one beat, 'C4:2' is two beats, 'C4:0.5' half a beat, and
    'C4+E4+G4:2' is a chord held for two beats.
    """
    steps = []
    for token in text.split():
        if token == "|":
            continue
        body, _, beats = token.partition(":")
        notes = []
        for part in body.split("+"):
            n = parse_note(part)
            if n is None:
                raise ValueError(f"bad note {part!r} in melody token {token!r}")
            notes.append(n)
        steps.append(Step(notes, float(beats) if beats else 1.0))
    return steps


def validate_lesson(data: dict, fold: bool = False) -> Lesson:
    """Turn untrusted data (LLM output, a cached file) into a safe Lesson.

    Notes are normalised, out-of-range songs are shifted by whole octaves until
    they fit the keyboard, and anything unplayable is rejected with a clear
    error so the caller can fall back or report it. Pass fold=True for a
    hand-written tune: one note outside the keyboard then moves an octave
    instead of the whole song being thrown away.
    """
    title = str(data.get("title") or "Untitled").strip() or "Untitled"
    # which passage this is - a short label the model was asked for ("chorus")
    part = re.sub(r"\s+", " ", str(data.get("part") or "")).strip().lower()[:24]
    try:
        tempo = int(float(data.get("tempo") or 100))
    except (TypeError, ValueError):
        tempo = 100
    tempo = max(40, min(240, tempo))
    difficulty = str(data.get("difficulty") or "beginner").lower()
    if difficulty not in ("beginner", "intermediate", "advanced"):
        difficulty = "beginner"

    raw_steps = data.get("steps") or []
    if not isinstance(raw_steps, list) or not raw_steps:
        raise ValueError("lesson has no steps")

    steps = []
    for item in raw_steps:
        if not isinstance(item, dict):
            continue
        raw_notes = item.get("notes")
        if isinstance(raw_notes, str):
            raw_notes = [raw_notes]
        if not isinstance(raw_notes, list):
            continue
        notes = []
        for rn in raw_notes:
            n = parse_note(rn)
            if n is not None and n not in notes:
                notes.append(n)
        if not notes:
            continue
        try:
            beats = float(item.get("beats", 1.0))
        except (TypeError, ValueError):
            beats = 1.0
        steps.append(Step(notes, max(0.25, min(8.0, beats))))

    if not steps:
        raise ValueError("lesson has no playable notes")

    # Keep it a *lesson*: cap the length so a runaway model can't produce 500 bars
    steps = steps[:96]

    lesson = Lesson(title, tempo, difficulty, steps,
                    source=str(data.get("source") or "llm"), part=part)
    return _fit_to_keyboard(lesson, fold=fold)


def _fit_to_keyboard(lesson: Lesson, fold: bool = False) -> Lesson:
    """Shift by whole octaves so every note fits C4..C6.

    Whole octaves only, so a song stays in its own key: a semitone nudge would
    put it in a key the player never asked for. With fold=True (a tune from
    songs/) the rare note that still will not fit moves an octave to get inside,
    rather than the whole tune being rejected over one low note. Without it
    (model answers) a song needing more than two octaves is rejected, because
    that is a sign the model invented it.
    """
    midis = [note_to_midi(n) for s in lesson.steps for n in s.notes if note_to_midi(n)]
    if not midis:
        raise ValueError("no valid notes")

    shift = 0
    if fold:
        # the octave shift that keeps the most notes playable, nearest first
        choices = [(sum(KEYBOARD_LO <= m + 12 * k <= KEYBOARD_HI for m in midis), -abs(k), k)
                   for k in (-3, -2, -1, 0, 1, 2, 3)]
        shift = 12 * max(choices)[2]
    elif max(midis) > KEYBOARD_HI:
        shift = -12 * ((max(midis) - KEYBOARD_HI + 11) // 12)
    if not fold and min(midis) + shift < KEYBOARD_LO:
        # too wide for two octaves: pull it up as far as it will go
        shift = max(shift, KEYBOARD_LO - min(midis))
    if shift:
        lesson = lesson.transposed(shift)
        midis = [note_to_midi(n) for s in lesson.steps for n in s.notes]

    if fold and (min(midis) < KEYBOARD_LO or max(midis) > KEYBOARD_HI):
        steps = []
        for s in lesson.steps:
            notes = []
            for note in s.notes:
                midi = note_to_midi(note)
                while midi < KEYBOARD_LO:
                    midi += 12
                while midi > KEYBOARD_HI:
                    midi -= 12
                name = midi_to_note(midi)
                if name not in notes:
                    notes.append(name)
            if notes:
                steps.append(Step(notes, s.beats))
        lesson = Lesson(lesson.title, lesson.tempo, lesson.difficulty, steps,
                        lesson.source, lesson.part)
        midis = [note_to_midi(n) for s in lesson.steps for n in s.notes]

    if min(midis) < KEYBOARD_LO or max(midis) > KEYBOARD_HI:
        raise ValueError(
            f"'{lesson.title}' spans more than two octaves "
            f"({midi_to_note(min(midis))}..{midi_to_note(max(midis))})")
    return lesson


# --------------------------------------------------------- built-in songs ----

_BUILTIN_LIST = [
    # -------- beginner: one hand, white keys only -------------------------
    Lesson("Twinkle Twinkle Little Star", 96, "beginner", parse_steps("""
        C4 C4 G4 G4 A4 A4 G4:2 | F4 F4 E4 E4 D4 D4 C4:2 |
        G4 G4 F4 F4 E4 E4 D4:2 | G4 G4 F4 F4 E4 E4 D4:2 |
        C4 C4 G4 G4 A4 A4 G4:2 | F4 F4 E4 E4 D4 D4 C4:2
    """)),
    Lesson("Mary Had a Little Lamb", 104, "beginner", parse_steps("""
        E4 D4 C4 D4 | E4 E4 E4:2 | D4 D4 D4:2 | E4 G4 G4:2 |
        E4 D4 C4 D4 | E4 E4 E4 E4 | D4 D4 E4 D4 | C4:2
    """)),
    Lesson("Hot Cross Buns", 100, "beginner", parse_steps("""
        E4 D4 C4:2 | E4 D4 C4:2 | C4 C4 C4 C4 | D4 D4 D4 D4 | E4 D4 C4:2
    """)),
    Lesson("Jingle Bells", 120, "beginner", parse_steps("""
        E4 E4 E4:2 | E4 E4 E4:2 | E4 G4 C4 D4 E4:4 |
        F4 F4 F4 F4 F4 E4 E4 E4 E4 D4 D4 E4 D4 G4:4
    """)),
    Lesson("Ode to Joy", 100, "beginner", parse_steps("""
        E4 E4 F4 G4 | G4 F4 E4 D4 | C4 C4 D4 E4 | E4:3 D4:1 D4:2 |
        E4 E4 F4 G4 | G4 F4 E4 D4 | C4 C4 D4 E4 | D4:3 C4:1 C4:2
    """)),
    Lesson("Row, Row, Row Your Boat", 100, "beginner", parse_steps("""
        C4 C4 C4 D4 E4:2 | E4 D4 E4 F4 G4:2 |
        C5 C5 C5 G4 G4 G4 E4 E4 E4 C4 C4 C4 | G4 F4 E4 D4 C4:2
    """)),
    Lesson("London Bridge", 104, "beginner", parse_steps("""
        G4:1.5 A4:0.5 G4 F4 E4 F4 G4:2 | D4 E4 F4:2 | E4 F4 G4:2 |
        G4:1.5 A4:0.5 G4 F4 E4 F4 G4:2 | D4 G4 E4 C4:2
    """)),
    Lesson("Frere Jacques", 100, "beginner", parse_steps("""
        C4 D4 E4 C4 | C4 D4 E4 C4 | E4 F4 G4:2 | E4 F4 G4:2 |
        G4 A4 G4 F4 E4 C4 | G4 A4 G4 F4 E4 C4 | C4 G4 C4:2 | C4 G4 C4:2
    """)),
    Lesson("Old MacDonald Had a Farm", 108, "beginner", parse_steps("""
        G4 G4 G4 D4 | E4 E4 D4:2 | B4 B4 A4 A4 | G4:2 D4:2 |
        G4 G4 G4 D4 | E4 E4 D4:2 | B4 B4 A4 A4 | G4:2
    """)),
    Lesson("When the Saints Go Marching In", 116, "intermediate", parse_steps("""
        C4 E4 F4 G4:3 | C4 E4 F4 G4:3 | C4 E4 F4 G4 E4 C4 E4 D4:3 |
        E4 E4 D4 C4 C4 E4 G4:3
    """)),
    Lesson("Happy Birthday", 108, "intermediate", parse_steps("""
        G4:0.5 G4:0.5 A4 G4 C5 B4:2 | G4:0.5 G4:0.5 A4 G4 D5 C5:2 |
        G4:0.5 G4:0.5 G5 E5 C5 B4 A4:2 | F5:0.5 F5:0.5 E5 C5 D5 C5:3
    """)),
    Lesson("Silent Night", 84, "intermediate", parse_steps("""
        G4:1.5 A4:0.5 G4 E4:2 | G4:1.5 A4:0.5 G4 E4:2 |
        D5:2 D5 B4:2 | C5:2 C5 G4:2 | A4:2 A4 C5:2 | B4:2 B4 G4:2
    """)),
    Lesson("Amazing Grace", 84, "intermediate", parse_steps("""
        G4 C5 E5 C5 E5 D5 C5 A4 G4:2 | G4 C5 E5 C5 E5 D5 G5:2
    """)),
    Lesson("Fur Elise", 92, "intermediate", parse_steps("""
        E5 D#5 E5 D#5 E5 B4 D5 C5 A4:2 | C4 E4 A4 B4:2 | E4 G#4 B4 C5:2 |
        E4 E5 D#5 E5 D#5 E5 B4 D5 C5 A4:2
    """)),

    # -------- exercises ---------------------------------------------------
    Lesson("Exercise: C Major Scale", 92, "beginner", parse_steps("""
        C4 D4 E4 F4 G4 A4 B4 C5 | C5 B4 A4 G4 F4 E4 D4 C4:2
    """)),
    Lesson("Exercise: Black Key Walk", 80, "beginner", parse_steps("""
        C#4 D#4 F#4 G#4 A#4:2 | A#4 G#4 F#4 D#4 C#4:2
    """)),
    Lesson("Exercise: C and G Chords", 76, "beginner", parse_steps("""
        C4+E4+G4:4 | G4+B4+D5:4 | C4+E4+G4:4 | G4+B4+D5:4
    """)),
]

BUILTIN = {slug(l.title): l for l in _BUILTIN_LIST}


def list_songs() -> list:
    """Describe the built-in and saved songs for a menu (no LLM needed)."""
    songs = {s: _describe(s, l) for s, l in BUILTIN.items()}
    for s, lesson in songbook_lessons().items():
        songs.setdefault(s, _describe(s, lesson))   # a built-in wins a clash
    return sorted(songs.values(), key=lambda s: s["title"])


def _describe(s: str, lesson: Lesson) -> dict:
    return {"slug": s, "title": lesson.title, "difficulty": lesson.difficulty,
            "tempo": lesson.tempo, "length": lesson.length,
            "notes": lesson.used_notes(), "source": lesson.source}


_STOP = {"the", "a", "an", "of", "in", "on", "my", "to"} | set(tunes.TUNE_TYPES)


def _best_match(title: str, candidates: dict) -> Lesson | None:
    """Fuzzy title search over {slug: Lesson}: exact first, then shared words.

    A distinctive single word is enough ('twinkle' finds Twinkle Twinkle), but a
    vague query is not forced onto an unrelated song.
    """
    want = slug(title)
    if want in candidates:
        return candidates[want]
    words = {w for w in want.split("-") if w and w not in _STOP}
    if not words:
        return None
    best, best_score = None, 0.0
    for s, lesson in candidates.items():
        sw = {w for w in s.split("-") if w and w not in _STOP}
        if not sw:
            continue
        inter = len(words & sw)
        if not inter:
            continue
        score = max(inter / len(words), inter / len(words | sw))
        if want and (want in s or s in want):
            score = max(score, 0.9)
        if score > best_score:
            best, best_score = lesson, score
    return best if best_score >= 0.6 else None


def get_builtin(title: str) -> Lesson | None:
    """Find a built-in song by slug, exact title, or fuzzy word overlap."""
    return _best_match(title, BUILTIN)


# ---------------------------------------------------------------- songbook ----

SONGBOOK_DIR = os.path.join(_HERE, "songs")


def _songbook_data(name: str, text: str) -> dict | None:
    """Turn one saved file into lesson data, or None if the format is unknown.

    .abc   ABC notation (thesession.org, abcnotation.com, the Nottingham set)
    .txt   a compact melody, with an optional '# Title' first line
    .json  this app's own lesson shape
    """
    ext = os.path.splitext(name)[1].lower()
    if ext == ".abc":
        return tunes.parse_abc(text)
    if ext == ".json":
        return json.loads(text)
    if ext in (".txt", ".melody", ".notes"):
        title, melody = "", []
        for line in text.splitlines():
            if line.lstrip().startswith("#"):
                title = title or line.lstrip().lstrip("#").strip()
                continue
            melody.append(line)
        steps = parse_steps("\n".join(melody))
        return {"title": title or os.path.splitext(name)[0],
                "steps": [{"notes": s.notes, "beats": s.beats} for s in steps]}
    return None


def songbook_lessons() -> dict:
    """Every playable file in songs/, keyed by slug. Read fresh on each call.

    The folder is meant to be edited by hand, so a broken or unplayable file is
    skipped rather than fatal: one bad song must not break every lookup.
    """
    found = {}
    try:
        names = sorted(os.listdir(SONGBOOK_DIR))
    except OSError:
        return found
    for name in names:
        try:
            with open(os.path.join(SONGBOOK_DIR, name), "r", encoding="utf-8") as fh:
                data = _songbook_data(name, fh.read())
            if not data:
                continue
            lesson = validate_lesson(data, fold=True)
        except Exception:
            continue
        lesson.source = "songbook"
        found[slug(lesson.title)] = lesson
    return found


def get_songbook(title: str) -> Lesson | None:
    """A song saved in `songs/` - exact notes, found without any model."""
    return _best_match(title, songbook_lessons())


def save_songbook(name: str, key: str, abc: str) -> str:
    """Write a fetched tune into songs/ and return its path."""
    os.makedirs(SONGBOOK_DIR, exist_ok=True)
    path = os.path.join(SONGBOOK_DIR, slug(name) + ".abc")
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(f"T:{name}\nK:{key}\n{abc}\n")
    return path


# ------------------------------------------------------------ LLM lookup ----

CACHE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".cache", "songs")

PROMPT = """You are a piano teacher. Give the most famous passage of the song "{title}" as a beginner piano lesson.

Return ONLY a JSON object, no prose and no markdown fences, in exactly this shape:
{{"title": "the song title", "part": "chorus", "tempo": 100, "difficulty": "beginner",
  "steps": [{{"notes": ["C4"], "beats": 1}}, {{"notes": ["C4"], "beats": 1}}]}}

Rules:
- Use scientific pitch notation: C4 is middle C. Flats are written with 'b' (Db4) and sharps with '#' (C#4).
- The player has a two-octave keyboard, C4 up to C6. Keep every note inside that range.
- One object per note event, in playing order. Put notes that sound together (a chord) in the same "notes" list.
- "beats" is the note length: 0.5 = eighth note, 1 = quarter, 2 = half, 4 = whole.
- Give the passage everybody knows - the chorus, main hook or opening phrase of the tune - and not the
  rest of the song, but play the whole of that passage: aim for 20 to 30 steps. Do not pad it out with
  repeated notes, and do not guess the parts you are unsure of.
- Name that passage in "part", in two or three words (for example "chorus", "main hook", "opening riff").
- Pick a sensible tempo in beats per minute (usually 70 to 130).
- If you do not reliably know this song, say so instead of guessing: return
  {{"title": "{title}", "part": "unknown", "tempo": 100, "steps": []}}."""

PROMPT_VERSION = 3      # bump when PROMPT changes: cached answers from an older prompt are ignored


def _post_json(url: str, payload: dict, headers: dict, timeout: float = 60.0) -> dict:
    body = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=body, method="POST")
    req.add_header("Content-Type", "application/json")
    for k, v in headers.items():
        req.add_header(k, v)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _ollama_models(timeout: float = 0.8) -> list:
    """Model names installed in a local Ollama, or [] if it isn't running."""
    try:
        with urllib.request.urlopen("http://localhost:11434/api/tags", timeout=timeout) as r:
            data = json.loads(r.read().decode("utf-8"))
        return [m.get("name", "") for m in data.get("models", []) if m.get("name")]
    except Exception:
        return []


def _ollama_alive(timeout: float = 0.6) -> bool:
    return bool(_ollama_models(timeout))


def available_providers() -> list:
    """Providers we could use right now, in priority order.

    Set AIR_PIANO_LLM=off to disable song lookup completely (the app then only
    uses the built-in, hand-verified songs).
    """
    forced = os.environ.get("AIR_PIANO_LLM", "").strip().lower()
    if forced in ("off", "none", "0", "false", "no"):
        return []
    have = []
    if os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY"):
        have.append("gemini")
    if os.environ.get("GROQ_API_KEY"):
        have.append("groq")
    if os.environ.get("OPENROUTER_API_KEY"):
        have.append("openrouter")
    if _ollama_alive():
        have.append("ollama")
    if forced in ("gemini", "groq", "openrouter", "ollama"):
        have = [forced] + [h for h in have if h != forced]
    return have


def _post_cloud(provider: str, model: str, url: str, payload: dict,
                headers: dict, timeout: float) -> dict:
    """POST to a cloud model, turning HTTP errors into something readable.

    Model names get retired, and a stale one answers 404 - say that plainly,
    rather than leaking "HTTP Error 404: Not Found" into the page."""
    try:
        return _post_json(url, payload, headers, timeout=timeout)
    except urllib.error.HTTPError as exc:
        var = "AIR_PIANO_" + provider.upper() + "_MODEL"
        if exc.code == 404:
            raise ValueError(f"model '{model}' is no longer offered by {provider}; "
                             f"set {var} to a current model") from None
        if exc.code in (400, 401, 403):
            body = ""
            try:
                body = exc.read().decode("utf-8", "replace")
            except Exception:
                pass
            reason = ""
            try:  # Gemini/Groq/OpenRouter all nest the useful text in error.message
                reason = (json.loads(body).get("error") or {}).get("message") or ""
            except Exception:
                pass
            if not reason:
                reason = re.sub(r"\s+", " ", body).strip()[:140]
            raise ValueError(f"{provider} refused the request (HTTP {exc.code}"
                             + (f": {reason}" if reason else "") + ")") from None
        raise


def _ask_gemini(prompt: str, timeout: float = 60.0) -> str:
    key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
    # an alias, so a yearly renaming cannot break lookup the way a pinned
    # snapshot does (gemini-2.0-flash was retired and answered 404). The "lite"
    # alias both answers in ~2s and recalled the test melody exactly, where the
    # full flash alias took 22s and got the tune wrong.
    model = os.environ.get("AIR_PIANO_GEMINI_MODEL", "gemini-flash-lite-latest")
    url = (f"https://generativelanguage.googleapis.com/v1beta/models/"
           f"{model}:generateContent?key={key}")
    data = _post_cloud("gemini", model, url, {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"temperature": 0.4, "responseMimeType": "application/json"},
    }, {}, timeout)
    return data["candidates"][0]["content"]["parts"][0]["text"]


def _ask_groq(prompt: str, timeout: float = 60.0) -> str:
    model = os.environ.get("AIR_PIANO_GROQ_MODEL", "llama-3.3-70b-versatile")
    data = _post_cloud("groq", model,
        "https://api.groq.com/openai/v1/chat/completions",
        {"model": model, "temperature": 0.4, "messages": [{"role": "user", "content": prompt}]},
        {"Authorization": f"Bearer {os.environ['GROQ_API_KEY']}"},
        timeout)
    return data["choices"][0]["message"]["content"]


def _ask_openrouter(prompt: str, timeout: float = 60.0) -> str:
    model = os.environ.get("AIR_PIANO_OPENROUTER_MODEL",
                           "meta-llama/llama-3.3-70b-instruct:free")
    data = _post_cloud("openrouter", model,
        "https://openrouter.ai/api/v1/chat/completions",
        {"model": model, "temperature": 0.4, "messages": [{"role": "user", "content": prompt}]},
        {"Authorization": f"Bearer {os.environ['OPENROUTER_API_KEY']}"},
        timeout)
    return data["choices"][0]["message"]["content"]


def _ask_ollama(prompt: str, timeout: float = 60.0) -> str:
    model = os.environ.get("AIR_PIANO_OLLAMA_MODEL", "llama3.2")
    known = _ollama_models()
    if known and model not in known and f"{model}:latest" not in known:
        raise ValueError(
            f"model '{model}' is not downloaded (have: {', '.join(known) or 'none'}). "
            f"Run 'ollama pull {model}', or set AIR_PIANO_OLLAMA_MODEL to one of those.")
    data = _post_json(
        "http://localhost:11434/api/chat",
        {"model": model, "stream": False, "format": "json",
         # keep the weights resident: a cold model has to be read from disk first,
         # which on its own can add several seconds to every lookup
         "keep_alive": os.environ.get("AIR_PIANO_OLLAMA_KEEP_ALIVE", "30m"),
         "options": {"temperature": 0.4, "num_predict": 1400},
         "messages": [
             {"role": "system",
              "content": "You are a piano teacher. You reply with one JSON object only."},
             {"role": "user", "content": prompt}]},
        {}, timeout=timeout)
    return data["message"]["content"]


_ASK = {"gemini": _ask_gemini, "groq": _ask_groq,
        "openrouter": _ask_openrouter, "ollama": _ask_ollama}

CLOUD_PROVIDERS = ("gemini", "groq", "openrouter")
DEFAULT_TIMEOUT = 60.0   # per provider, while another one can still take over
LONE_TIMEOUT = 180.0     # the last provider in the chain - nothing after it to hand over to


def _attempt_timeout(last: bool) -> float:
    """Seconds to give one provider before moving on to the next.

    A provider that has another one behind it gets a short budget, so a slow
    local model hands over to a free cloud model instead of stalling the page.
    The last provider in the chain gets longer, because cutting it off early
    would just lose the lookup. AIR_PIANO_LLM_TIMEOUT overrides both."""
    raw = os.environ.get("AIR_PIANO_LLM_TIMEOUT", "").strip()
    if raw:
        try:
            return max(5.0, float(raw))
        except ValueError:
            pass
    return LONE_TIMEOUT if last else DEFAULT_TIMEOUT


def _why(exc: Exception, timeout: float) -> str:
    """A short, readable reason an attempt failed."""
    reason = getattr(exc, "reason", None)   # urllib wraps socket errors in URLError
    if isinstance(exc, TimeoutError) or isinstance(reason, TimeoutError):
        return f"no reply within {timeout:.0f}s"
    return f"{type(exc).__name__}: {exc}"


def preload_local_model() -> None:
    """Best-effort warm-up so the first lookup is not slowed by the model load.

    Only worth doing when the local model is the first provider we would ask;
    Ollama then keeps it resident for AIR_PIANO_OLLAMA_KEEP_ALIVE."""
    providers = available_providers()
    if not providers or providers[0] != "ollama":
        return
    try:
        _post_json(
            "http://localhost:11434/api/chat",
            {"model": os.environ.get("AIR_PIANO_OLLAMA_MODEL", "llama3.2"),
             "stream": False,
             "keep_alive": os.environ.get("AIR_PIANO_OLLAMA_KEEP_ALIVE", "30m"),
             "options": {"num_predict": 1},
             "messages": [{"role": "user", "content": "hi"}]},
            {}, timeout=LONE_TIMEOUT)
    except Exception:
        pass    # warming up is a nicety, never a reason to fail


def extract_json(text: str) -> dict:
    """Pull the first JSON object out of a model reply, fences and all."""
    if not text:
        raise ValueError("empty reply")
    cleaned = text.strip()
    cleaned = re.sub(r"^```(?:json)?|```$", "", cleaned, flags=re.MULTILINE).strip()
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        pass
    start = cleaned.find("{")
    depth = 0
    for i in range(start if start >= 0 else 0, len(cleaned)):
        c = cleaned[i]
        if c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0:
                return json.loads(cleaned[start:i + 1])
    raise ValueError("no JSON object in reply")


def _cache_path(title: str) -> str:
    return os.path.join(CACHE_DIR, slug(title) + ".json")


def read_cache(title: str) -> Lesson | None:
    path = _cache_path(title)
    try:
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        if data.get("prompt") != PROMPT_VERSION:
            return None      # saved under an older prompt: ask the model again
        return validate_lesson(data)
    except FileNotFoundError:
        return None
    except Exception:
        return None


def write_cache(lesson: Lesson) -> None:
    try:
        os.makedirs(CACHE_DIR, exist_ok=True)
        with open(_cache_path(lesson.title), "w", encoding="utf-8") as fh:
            json.dump({"prompt": PROMPT_VERSION, **lesson.to_dict()}, fh, indent=1)
    except Exception:
        pass


def llm_lesson(title: str, provider: str, timeout: float = DEFAULT_TIMEOUT) -> Lesson:
    """Ask one provider for the famous passage of a song, and validate it."""
    raw = extract_json(_ASK[provider](PROMPT.format(title=title), timeout))
    if str(raw.get("part", "")).strip().lower() in ("unknown", "none", "n/a"):
        # the model said it does not know the song: better than inventing a tune
        raise UnknownSong("the model does not know this song")
    lesson = validate_lesson(raw)
    lesson.source = f"llm:{provider}"
    if not lesson.title or slug(lesson.title) == "untitled":
        lesson.title = title
    return lesson


def find_lesson(title: str, allow_llm: bool = True, refresh: bool = False) -> Lesson:
    """Built-in, then songs/, then the on-disk cache, then a free LLM.

    Pass refresh=True to ignore the cache and ask the model again (useful when a
    melody came back wrong -- sampling means a retry can be better). A song in
    songs/ is always used as it is: those notes are exact and offline.
    Raises LookupError with a helpful message if the song cannot be found and
    no LLM is available.
    """
    title = (title or "").strip()
    if not title:
        raise LookupError("no song name given")

    builtin = get_builtin(title)
    if builtin:
        return builtin

    saved = get_songbook(title)
    if saved:
        return saved

    if not refresh:
        cached = read_cache(title)
        if cached is not None:
            cached.source = "cache"
            return cached

    if not allow_llm:
        raise LookupError(f"'{title}' is not in the built-in song list")

    providers = available_providers()
    errors = []
    for i, provider in enumerate(providers):
        timeout = _attempt_timeout(i + 1 == len(providers))
        try:
            lesson = llm_lesson(title, provider, timeout)
        except UnknownSong as exc:
            errors.append(f"{provider}: {exc}")
            # A cloud model knows what it knows, so keep asking any *other* cloud
            # model, but never let a small local model invent a melody to fill
            # the gap - that is exactly the made-up tune we want to avoid.
            if not any(p in CLOUD_PROVIDERS for p in providers[i + 1:]):
                break
            continue
        except Exception as exc:  # offline, too slow, bad JSON, bad notes -- next
            errors.append(f"{provider}: {_why(exc, timeout)}")
            continue
        write_cache(lesson)
        return lesson

    if errors:
        raise LookupError(f"could not build a lesson for '{title}' ({'; '.join(errors)})")
    raise LookupError(
        f"'{title}' is not built in, and no free LLM is configured. "
        "Set GEMINI_API_KEY, GROQ_API_KEY or OPENROUTER_API_KEY (or run Ollama "
        "locally), or pick one of the built-in songs.")


def llm_status() -> dict:
    """Small status blob for the web UI."""
    providers = available_providers()
    status = {"available": providers, "enabled": bool(providers), "local_only": False}
    if not providers:
        if os.environ.get("AIR_PIANO_LLM", "").strip().lower() in ("off", "none", "0", "false", "no"):
            status["hint"] = ("Song lookup is turned off (AIR_PIANO_LLM=off). "
                              "The built-in songs still work.")
        else:
            status["hint"] = ("Set GEMINI_API_KEY, GROQ_API_KEY or OPENROUTER_API_KEY, "
                              "or run Ollama locally, to look up any song.")
    elif providers == ["ollama"]:
        status["local_only"] = True
        status["hint"] = ("Looking songs up with your local Ollama model. Small models "
                          "often get a melody wrong -- listen to the preview and press "
                          "Look up again for another attempt. A free cloud key (Gemini "
                          "or Groq) recalls songs far more reliably, and a bigger local "
                          "model helps too (e.g. ollama pull qwen2.5:7b, then set "
                          "AIR_PIANO_OLLAMA_MODEL=qwen2.5:7b).")
    else:
        if os.environ.get("AIR_PIANO_LLM_TIMEOUT", "").strip():
            budget = f"{_attempt_timeout(False):.0f}s"
        else:
            budget = f"{DEFAULT_TIMEOUT:.0f}s, the last one gets {LONE_TIMEOUT:.0f}s"
        status["hint"] = ("Song lookup tries " + " then ".join(providers) +
                          f"; a slow one hands over after {budget}.")
    return status


# ------------------------------------------------------------------- main ----

def _print_lesson(lesson: Lesson) -> None:
    print(f"{lesson.display}  ({lesson.difficulty}, {lesson.tempo} BPM, "
          f"{lesson.length} steps, source: {lesson.source})")
    print("notes used:", " ".join(lesson.used_notes()))
    line = []
    for s in lesson.steps:
        token = "+".join(s.notes)
        if s.beats != 1.0:
            token += f":{s.beats:g}"
        line.append(token)
    text = " ".join(line)
    for i in range(0, len(text), 96):
        print("  " + text[i:i + 96])


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv or argv[0] in ("-h", "--help"):
        print(__doc__)
        return 0
    if argv[0] == "--list":
        for s in list_songs():
            tag = "  (saved)" if s["source"] == "songbook" else ""
            print(f"  {s['title']:32} {s['difficulty']:13} "
                  f"{s['tempo']:3} BPM  {s['length']:2} steps{tag}")
        status = llm_status()
        if status["enabled"]:
            print("\nLLM lookup: ready via " + ", ".join(status["available"]))
            print("            " + status["hint"])
        else:
            print("\nLLM lookup: not configured - " + status["hint"])
        return 0

    if argv[0] == "--songbook":
        lessons = songbook_lessons()
        if not lessons:
            print(f"nothing saved yet in {SONGBOOK_DIR}")
            print("add a .abc/.txt/.json file there, or run: "
                  'python tutor.py --fetch "The Irish Washerwoman"')
            return 0
        for s, lesson in sorted(lessons.items(), key=lambda kv: kv[1].title):
            print(f"  {lesson.title:32} {lesson.difficulty:13} "
                  f"{lesson.tempo:3} BPM  {lesson.length:2} steps")
        print(f"\n{len(lessons)} saved song(s) in {SONGBOOK_DIR}")
        return 0

    if argv[0] == "--fetch":
        name = " ".join(argv[1:]).strip()
        if not name:
            print('error: give a tune name, e.g. --fetch "The Irish Washerwoman"',
                  file=sys.stderr)
            return 1
        try:
            got = tunes.fetch_folk(name)
        except tunes.FolkUnavailable as exc:
            print(f"error: could not reach thesession.org ({exc}). "
                  "It is a free community site, so try again later.",
                  file=sys.stderr)
            return 1
        if not got:
            closest = ""
            try:
                others = [t.get("name") for t in tunes.search_folk(name) if t.get("name")]
                closest = others[0] if others else ""
            except Exception:
                pass
            print(f"error: thesession.org has no traditional tune matching '{name}'"
                  + (f" (the closest it has is '{closest}')" if closest else "")
                  + ". It only holds Irish and Scottish tunes.", file=sys.stderr)
            return 1
        song, key, abc = got
        path = save_songbook(song, key, abc)
        lesson = get_songbook(song)
        steps = f"{lesson.length} steps" if lesson else "unplayable, file kept"
        print(f"saved {song} [{key}] as {path} ({steps})")
        return 0

    title = " ".join(argv)
    refresh = False
    if title.startswith("--refresh "):
        refresh, title = True, title[len("--refresh "):]
    try:
        lesson = find_lesson(title, refresh=refresh)
    except LookupError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    _print_lesson(lesson)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
