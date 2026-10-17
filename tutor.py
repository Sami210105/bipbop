"""Songs, lessons and a free-LLM song lookup for the Bipbop tutor.

This module is deliberately standard-library only. It is used by both the
desktop app (air_piano.py) and the local web server (serve.py), and neither of
those should be forced to import mediapipe/opencv just to read a song.

A "lesson" is a short, ordered list of steps. Each step is one note event: one
key for a melody note, or several keys at once for a chord. Every lesson is
validated to sit inside the app's two-octave keyboard (C4..C6), transposed by
whole octaves if needed.

Usage from the command line:

    python tutor.py --list              # built-in songs
    python tutor.py "some song name"    # print a lesson (built-in or LLM)
    python tutor.py --refresh "song"    # ignore the cache and ask again

Environment variables (all optional -- the built-in songs need none):

    GEMINI_API_KEY / GOOGLE_API_KEY   free Google AI Studio key
    GROQ_API_KEY                      free Groq key
    OPENROUTER_API_KEY                free OpenRouter key
    AIR_PIANO_LLM                     force a provider: gemini|groq|openrouter|ollama
    AIR_PIANO_OLLAMA_MODEL            local model name (default llama3.2)
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
    source: str = "builtin"    # builtin | cache | llm:<provider>

    @property
    def length(self) -> int:
        return len(self.steps)

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
        return Lesson(self.title, self.tempo, self.difficulty, steps, self.source)

    def to_dict(self) -> dict:
        return {
            "title": self.title,
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


def validate_lesson(data: dict) -> Lesson:
    """Turn untrusted data (LLM output, a cached file) into a safe Lesson.

    Notes are normalised, out-of-range songs are shifted by whole octaves until
    they fit the keyboard, and anything unplayable is rejected with a clear
    error so the caller can fall back or report it.
    """
    title = str(data.get("title") or "Untitled").strip() or "Untitled"
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
                    source=str(data.get("source") or "llm"))
    return _fit_to_keyboard(lesson)


def _fit_to_keyboard(lesson: Lesson) -> Lesson:
    """Shift by whole octaves so every note fits C4..C6 (best effort)."""
    midis = [note_to_midi(n) for s in lesson.steps for n in s.notes if note_to_midi(n)]
    if not midis:
        raise ValueError("no valid notes")
    shift = 0
    if max(midis) > KEYBOARD_HI:
        shift = -12 * ((max(midis) - KEYBOARD_HI + 11) // 12)
    if min(midis) + shift < KEYBOARD_LO:
        # too wide for two octaves: pull it up as far as it will go
        shift = max(shift, KEYBOARD_LO - min(midis))
    if shift:
        lesson = lesson.transposed(shift)
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
    """Describe the built-in songs for a menu (no LLM needed)."""
    return [{"slug": s, "title": l.title, "difficulty": l.difficulty,
             "tempo": l.tempo, "length": l.length, "notes": l.used_notes()}
            for s, l in sorted(BUILTIN.items(), key=lambda kv: kv[1].title)]


_STOP = {"the", "a", "an", "of", "in", "on", "my", "to"}


def get_builtin(title: str) -> Lesson | None:
    """Find a built-in song by slug, exact title, or fuzzy word overlap.

    A distinctive single word is enough ('twinkle' finds Twinkle Twinkle), but a
    vague query is not forced onto an unrelated song.
    """
    want = slug(title)
    if want in BUILTIN:
        return BUILTIN[want]
    words = {w for w in want.split("-") if w and w not in _STOP}
    if not words:
        return None
    best, best_score = None, 0.0
    for s, lesson in BUILTIN.items():
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


# ------------------------------------------------------------ LLM lookup ----

CACHE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".cache", "songs")

PROMPT = """You are a piano teacher. Write a beginner-friendly lesson for the melody of the song "{title}".

Return ONLY a JSON object, no prose and no markdown fences, in exactly this shape:
{{"title": "the song title", "tempo": 100, "difficulty": "beginner",
  "steps": [{{"notes": ["C4"], "beats": 1}}, {{"notes": ["C4"], "beats": 1}}]}}

Rules:
- Use scientific pitch notation: C4 is middle C. Flats are written with 'b' (Db4) and sharps with '#' (C#4).
- The player has a two-octave keyboard, C4 up to C6. Keep every note inside that range.
- One object per note event, in playing order. Put notes that sound together (a chord) in the same "notes" list.
- "beats" is the note length: 0.5 = eighth note, 1 = quarter, 2 = half, 4 = whole.
- Give the recognisable main melody, 10 to 40 steps.
- Pick a sensible tempo in beats per minute (usually 70 to 130)."""


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


def _ask_gemini(prompt: str) -> str:
    key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
    model = os.environ.get("AIR_PIANO_GEMINI_MODEL", "gemini-2.0-flash")
    url = (f"https://generativelanguage.googleapis.com/v1beta/models/"
           f"{model}:generateContent?key={key}")
    data = _post_json(url, {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"temperature": 0.4, "responseMimeType": "application/json"},
    }, {})
    return data["candidates"][0]["content"]["parts"][0]["text"]


def _ask_groq(prompt: str) -> str:
    model = os.environ.get("AIR_PIANO_GROQ_MODEL", "llama-3.3-70b-versatile")
    data = _post_json(
        "https://api.groq.com/openai/v1/chat/completions",
        {"model": model, "temperature": 0.4, "messages": [{"role": "user", "content": prompt}]},
        {"Authorization": f"Bearer {os.environ['GROQ_API_KEY']}"})
    return data["choices"][0]["message"]["content"]


def _ask_openrouter(prompt: str) -> str:
    model = os.environ.get("AIR_PIANO_OPENROUTER_MODEL",
                           "meta-llama/llama-3.3-70b-instruct:free")
    data = _post_json(
        "https://openrouter.ai/api/v1/chat/completions",
        {"model": model, "temperature": 0.4, "messages": [{"role": "user", "content": prompt}]},
        {"Authorization": f"Bearer {os.environ['OPENROUTER_API_KEY']}"})
    return data["choices"][0]["message"]["content"]


def _ask_ollama(prompt: str) -> str:
    model = os.environ.get("AIR_PIANO_OLLAMA_MODEL", "llama3.2")
    known = _ollama_models()
    if known and model not in known and f"{model}:latest" not in known:
        raise ValueError(
            f"model '{model}' is not downloaded (have: {', '.join(known) or 'none'}). "
            f"Run 'ollama pull {model}', or set AIR_PIANO_OLLAMA_MODEL to one of those.")
    data = _post_json(
        "http://localhost:11434/api/chat",
        {"model": model, "stream": False, "format": "json",
         "options": {"temperature": 0.4, "num_predict": 1400},
         "messages": [
             {"role": "system",
              "content": "You are a piano teacher. You reply with one JSON object only."},
             {"role": "user", "content": prompt}]},
        {}, timeout=float(os.environ.get("AIR_PIANO_LLM_TIMEOUT", 180)))
    return data["message"]["content"]


_ASK = {"gemini": _ask_gemini, "groq": _ask_groq,
        "openrouter": _ask_openrouter, "ollama": _ask_ollama}


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
            return validate_lesson(json.load(fh))
    except FileNotFoundError:
        return None
    except Exception:
        return None


def write_cache(lesson: Lesson) -> None:
    try:
        os.makedirs(CACHE_DIR, exist_ok=True)
        with open(_cache_path(lesson.title), "w", encoding="utf-8") as fh:
            json.dump(lesson.to_dict(), fh, indent=1)
    except Exception:
        pass


def llm_lesson(title: str, provider: str) -> Lesson:
    """Ask one provider for a lesson and validate it."""
    lesson = validate_lesson(extract_json(_ASK[provider](PROMPT.format(title=title))))
    lesson.source = f"llm:{provider}"
    if not lesson.title or slug(lesson.title) == "untitled":
        lesson.title = title
    return lesson


def find_lesson(title: str, allow_llm: bool = True, refresh: bool = False) -> Lesson:
    """Built-in first, then the on-disk cache, then a free LLM if configured.

    Pass refresh=True to ignore the cache and ask the model again (useful when a
    melody came back wrong -- sampling means a retry can be better).
    Raises LookupError with a helpful message if the song cannot be found and
    no LLM is available.
    """
    title = (title or "").strip()
    if not title:
        raise LookupError("no song name given")

    builtin = get_builtin(title)
    if builtin:
        return builtin

    if not refresh:
        cached = read_cache(title)
        if cached is not None:
            cached.source = "cache"
            return cached

    if not allow_llm:
        raise LookupError(f"'{title}' is not in the built-in song list")

    errors = []
    for provider in available_providers():
        try:
            lesson = llm_lesson(title, provider)
        except Exception as exc:  # network, bad JSON, bad notes -- try the next one
            errors.append(f"{provider}: {exc}")
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
        status["hint"] = "Song lookup ready via " + ", ".join(providers) + "."
    return status


# ------------------------------------------------------------------- main ----

def _print_lesson(lesson: Lesson) -> None:
    print(f"{lesson.title}  ({lesson.difficulty}, {lesson.tempo} BPM, "
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
            print(f"  {s['title']:32} {s['difficulty']:13} "
                  f"{s['tempo']:3} BPM  {s['length']:2} steps")
        status = llm_status()
        print("\nLLM lookup:", "ready via " + ", ".join(status["available"])
              if status["enabled"] else "not configured - " + status["hint"])
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
