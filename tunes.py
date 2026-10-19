"""Free, open tune data for Bipbop - no model, no API key, no dependency.

ABC notation is the common language of the free tune archives (thesession.org,
abcnotation.com, the Nottingham dataset), and it is plain text, so a small
standard-library parser is all it takes to get exact notes from it.

parse_abc() returns a plain dict in the same shape the model is asked for:

    {"title": "The Irish Washerwoman", "tempo": 100, "difficulty": "beginner",
     "steps": [{"notes": ["B4"], "beats": 0.5}, ...]}

tutor.py validates that dict exactly like a model answer, so an unplayable tune
is rejected there rather than here. Nothing in this module imports the app.
"""

from __future__ import annotations

import json
import re
import urllib.error
import urllib.parse
import urllib.request

NOTE_NAMES = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]
_LETTER_PC = {"C": 0, "D": 2, "E": 4, "F": 5, "G": 7, "A": 9, "B": 11}
_SHARP_ORDER = ("F", "C", "G", "D", "A", "E", "B")
_FLAT_ORDER = ("B", "E", "A", "D", "G", "C", "F")
# accidentals in the major key with this pitch class (negative = flats)
_MAJOR_ACCIDENTALS = {0: 0, 7: 1, 2: 2, 9: 3, 4: 4, 11: 5, 6: 6,
                      5: -1, 10: -2, 3: -3, 8: -4, 1: -5}
# how far to move a mode's tonic to reach its relative major
_MODE_OFFSET = {"": 0, "maj": 0, "major": 0, "ion": 0, "ionian": 0,
                "dor": 10, "dorian": 10, "phr": 8, "phrygian": 8,
                "lyd": 7, "lydian": 7, "mix": 5, "mixolydian": 5,
                "min": 3, "minor": 3, "m": 3, "aeo": 3, "aeolian": 3,
                "loc": 1, "locrian": 1}

MAX_STEPS = 96          # as many as validate_lesson allows, so a whole short
                        # tune survives; longer ones stop at a bar line
DEFAULT_UNIT = 1 / 8    # ABC's usual L:, in whole notes


def key_accidentals(field: str) -> dict:
    """Which letters the key signature alters, e.g. K:G -> {'F': '#'}."""
    m = re.match(r"\s*([A-Ga-g])([#b]?)", field or "")
    if not m:
        return {}
    letter, accidental = m.group(1).upper(), m.group(2)
    mode = field[m.end():].strip().lower()
    tonic = _LETTER_PC[letter]
    if accidental == "#":
        tonic += 1
    elif accidental == "b":
        tonic -= 1
    offset = _MODE_OFFSET.get(mode)
    if offset is None:                       # e.g. "Gmaj " or "G clef=treble"
        offset = _MODE_OFFSET.get(mode[:3], 0)
    count = _MAJOR_ACCIDENTALS.get((tonic + offset) % 12, 0)
    if count > 0:
        return {name: "#" for name in _SHARP_ORDER[:count]}
    if count < 0:
        return {name: "b" for name in _FLAT_ORDER[:-count]}
    return {}


def _read_note(text: str, i: int, key_acc: dict) -> tuple:
    """Read one ABC note. Returns (name, next_index), name None if not a note."""
    j = i
    accidental = ""
    while j < len(text) and text[j] in "^_=":
        accidental = text[j]                 # ^ sharp, _ flat, = natural
        j += 1
    if j >= len(text) or text[j] not in "ABCDEFGabcdefg":
        return None, i + 1
    letter = text[j].upper()
    octave = 4 if text[j].isupper() else 5
    j += 1
    while j < len(text) and text[j] in "',":
        octave += 1 if text[j] == "'" else -1
        j += 1
    if accidental == "^":
        semis = 1
    elif accidental == "_":
        semis = -1
    elif accidental == "=":
        semis = 0
    else:
        semis = 1 if key_acc.get(letter) == "#" else -1 if key_acc.get(letter) == "b" else 0
    step = _LETTER_PC[letter] + semis
    octave += step // 12                     # B# rolls up, Cb rolls down
    return f"{NOTE_NAMES[step % 12]}{octave}", j


def _read_length(text: str, i: int) -> tuple:
    """Read an ABC length multiplier: G2, G/2, G3/2, G/ -> (factor, index)."""
    j = i
    digits = ""
    while j < len(text) and text[j].isdigit():
        digits += text[j]
        j += 1
    numerator = int(digits) if digits else 1
    denominator = 1
    if j < len(text) and text[j] == "/":
        j += 1
        rest = ""
        while j < len(text) and text[j].isdigit():
            rest += text[j]
            j += 1
        denominator = int(rest) if rest else 2
    return numerator / denominator, j


def _parse_body(body: str, key_acc: dict, unit: float) -> list:
    """Walk the tune, collecting note events (chords stay together)."""
    steps = []
    bars = []                                # where each bar line fell
    i, n = 0, len(body)
    beat = unit * 4                          # a quarter note is one beat
    while i < n:
        c = body[i]
        if c == "[":
            after = body[i + 1:i + 2]
            if not (after and after in "ABCDEFGabcdefg^_="):
                # not a chord: [1 / [2 are endings, [| is a bar line, [K:G] is
                # an inline header - none of which are notes to play
                if after.isalpha() and body[i + 2:i + 3] == ":":
                    end = body.find("]", i)
                    i = n if end < 0 else end + 1
                else:
                    i += 1
                continue
            end = body.find("]", i)
            end = n if end < 0 else end
            inner, j, notes = body[i + 1:end], 0, []
            while j < len(inner):
                name, j = _read_note(inner, j, key_acc)
                if name:
                    notes.append(name)
            i = end + 1
            if notes:
                length, i = _read_length(body, i)   # [CEG]2: a chord held for two
                steps.append({"notes": notes, "beats": beat * length})
            continue
        if c == "{":                          # grace notes: not beginner material
            end = body.find("}", i)
            i = n if end < 0 else end + 1
            continue
        if c == '"':                          # a "Gm" chord symbol
            end = body.find('"', i + 1)
            i = n if end < 0 else end + 1
            continue
        name, j = _read_note(body, i, key_acc)
        if name:
            length, j = _read_length(body, j)
            steps.append({"notes": [name], "beats": beat * length})
            i = j
            continue
        if c in "|!":                        # a bar line: a good place to stop
            bars.append(len(steps))
        i += 1                               # repeats, ties, decorations
    if len(steps) > MAX_STEPS:
        # cut on a bar line rather than in the middle of a phrase (but never so
        # early that the lesson is a fragment)
        ends = [b for b in bars if MAX_STEPS // 2 <= b <= MAX_STEPS]
        steps = steps[:ends[-1] if ends else MAX_STEPS]
    return steps


def _read_tempo(value: str) -> int | None:
    m = re.search(r"=\s*(\d+)", value) or re.search(r"(\d+)", value)
    return int(m.group(1)) if m else None


def _read_unit(value: str) -> float:
    m = re.match(r"\s*(\d+)\s*/\s*(\d+)", value)
    if m and int(m.group(2)):
        return int(m.group(1)) / int(m.group(2))
    m = re.match(r"\s*(\d+)", value)
    return float(m.group(1)) if m else DEFAULT_UNIT


def parse_abc(text: str, title: str = "", key: str = "") -> dict:
    """ABC notation (with or without headers) -> a lesson dict.

    `title` and `key` seed the parse for body-only ABC, such as the tune text
    thesession.org returns; a K: or T: header in the text still wins."""
    tempo = 100
    unit = DEFAULT_UNIT
    key_acc = key_accidentals(key) if key else {}
    body = []
    for line in text.splitlines():
        m = re.match(r"^\s*([A-Za-z]):\s?(.*)$", line)
        if m:
            field, value = m.group(1).upper(), m.group(2)
            if field == "T" and not title:
                title = value.strip()
            elif field == "Q":
                tempo = _read_tempo(value) or tempo
            elif field == "L":
                unit = _read_unit(value)
            elif field == "K":
                key_acc = key_accidentals(value)
            continue
        body.append(line)
    steps = _parse_body("\n".join(body), key_acc, unit)
    return {"title": title.strip() or "Untitled", "tempo": tempo,
            "difficulty": "beginner", "steps": steps, "source": "songbook"}


# ------------------------------------------------------------------ thesession ----

SEARCH_URL = "https://thesession.org/tunes/search?format=json&q="
TUNE_URL = "https://thesession.org/tunes/%s?format=json"
# Plain and honest. thesession.org sits behind a filter that answers 403 to some
# user-agent strings, so it is worth re-checking if lookups suddenly stop.
UA = {"User-Agent": "air-piano/1.0 (local practice tool, traditional tunes)"}

# Words that name a kind of tune rather than the tune itself: "Morrison's Jig"
# is filed as "Morrison's", and asking for "the Kesh jig" is not asking for a
# different tune than "The Kesh".
TUNE_TYPES = frozenset({
    "jig", "slipjig", "reel", "hornpipe", "polka", "waltz", "slide", "march",
    "strathspey", "mazurka", "fling", "barndance", "highland", "clog", "tune",
})
_QUERY_STOP = frozenset({"the", "a", "an", "of", "in", "on", "my", "song"}) | TUNE_TYPES


class FolkUnavailable(RuntimeError):
    """thesession.org could not be reached, or refused the request."""


def _get_json(url: str, timeout: float) -> dict:
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def name_matches(query: str, name: str) -> bool:
    """Is this tune really the one that was asked for?

    thesession.org searches loosely - "Blinding Lights" came back as an
    unrelated jig - and saving that would put a wrong tune in the songbook
    where nothing could correct it. So every meaningful word of the query has
    to appear in the tune's name (tune types and articles do not count)."""
    wanted = [w for w in re.findall(r"[a-z0-9']+", query.lower())
              if w not in _QUERY_STOP]
    return bool(wanted) and all(w in name.lower() for w in wanted)


def search_folk(title: str, timeout: float = 15.0) -> list:
    """Tunes the site knows under roughly this name, best first."""
    found = _get_json(SEARCH_URL + urllib.parse.quote(title), timeout)
    return found.get("tunes") or []


def fetch_folk(title: str, timeout: float = 15.0) -> tuple | None:
    """Look a traditional tune up on thesession.org - free, no key.

    Returns (name, key, abc_body) for the best match, or None when the site has
    no such tune (which is the usual answer for anything modern). Raises
    FolkUnavailable if the site cannot be reached at all, so the caller can say
    that rather than blaming the song.
    """
    try:
        tunes = search_folk(title, timeout)
        for tune in tunes[:8]:
            name = (tune.get("name") or "").strip()
            if not name or not tune.get("id") or not name_matches(title, name):
                continue
            detail = _get_json(TUNE_URL % tune["id"], timeout)
            settings = detail.get("settings") or []
            setting = settings[0] if settings else {}
            abc = (setting.get("abc") or "").strip()
            if abc:
                return (detail.get("name") or name, setting.get("key") or "C", abc)
    except urllib.error.HTTPError as exc:
        raise FolkUnavailable(f"HTTP {exc.code}") from exc
    except (urllib.error.URLError, OSError, ValueError) as exc:
        raise FolkUnavailable(str(exc)) from exc
    return None
