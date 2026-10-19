# Bipbop

Play a virtual piano in the air with your webcam. MediaPipe tracks all 10 fingertips, and a key plays a live-synthesized piano note the moment a fingertip enters it. A built-in tutor teaches songs note by note.

## Quick start

**Browser:**
```powershell
python serve.py
```
Open the printed `http://127.0.0.1:8000/`, click **Start playing**, and play. You can also click or tap the keys, or use the computer keyboard (`Z X C V B N M` / `Q W E R T Y U I`).

**Desktop app:**
```powershell
python -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt
.venv\Scripts\python.exe air_piano.py          # add --learn for tutor mode
```

## Tutor

Highlights the next key, waits for you, and keeps score. Press **Listen** (browser) or `d` (desktop) to hear the song first. It ships with 17 hand-checked songs (`--list-songs`).

A lookup goes: built-in, then `songs/` (your own, below), then the cache, then a free AI model (Ollama locally, or `GEMINI_API_KEY` / `GROQ_API_KEY` / `OPENROUTER_API_KEY`; put keys in a gitignored `.env`, see `.env.example`). The model is asked for the most famous passage of the song - chorus, hook or opening phrase - about 20 to 30 notes, and it says so when it does not know the tune. Small local models often get melodies wrong, so use a cloud key for reliability. Set `AIR_PIANO_LLM=off` to disable lookup.

## Your own songs (`songs/`)

Anything in `songs/` is used before the cache and before any model: exact notes, instant, offline. Drop a file in; no rebuild, no restart.

| File | What it is |
|------|------------|
| `*.abc` | ABC notation - the free tune archives: thesession.org, abcnotation.com, the Nottingham dataset |
| `*.txt` | a melody line, e.g. `C4 D4 E4:2 \| F4`, with an optional `# Title` first line |
| `*.json` | this app's own lesson shape: `{"title": "x", "steps": [{"notes": ["C4"], "beats": 1}]}` |

Traditional tunes come straight from thesession.org (free, no key):

```powershell
.venv\Scripts\python.exe tutor.py --fetch "The Irish Washerwoman"
.venv\Scripts\python.exe tutor.py --songbook
```

It only holds Irish and Scottish tunes; anything modern still goes to the model. A tune keeps its own key (it may move by whole octaves to fit C4-C6) and stops on a bar line after 96 notes. Saved songs appear in the app marked **saved**, with a Saved filter.

## Common options

| Flag | Meaning |
|------|---------|
| `--camera N` | pick a camera |
| `--width 1280 --height 720` | bigger picture and keys |
| `--position center/top/bottom` | keyboard placement (`p` cycles live) |
| `--octaves 3` | more keys |
| `--shared` | don't take exclusive control of audio |
| `--song "Name"` | learn a specific song |
| `--list-songs` | list the built-in and saved songs |

Desktop keys: `m` mute, `l` Learn mode, `d` demo, `r` restart, `[` `]` switch song, `k` skip, `q` quit.

## Tips

- Use a well-lit room, with hands 30-60 cm from the camera.
- Quick taps play louder.
- Dim lighting causes lag.

## Structure

- `air_piano.py`: desktop app
- `serve.py`: server and API
- `tutor.py`: songs, the `songs/` folder and AI lookup
- `tunes.py`: ABC parser and the thesession.org fetch
- `web/`: React 19 + Tailwind v4 + Vite UI (`npm run dev` / `npm run build`)
- `songs/`: your own songs (see above)

Tests: `python tests\run_all.py`

## Credits

The key-signature graphic used as the decorative hero backdrop comes from
[B-flat-major g-minor.svg](https://commons.wikimedia.org/wiki/File:B-flat-major_g_minor.svg)
by [Rettinghaus](https://commons.wikimedia.org/wiki/User:Rettinghaus), via Wikimedia Commons,
licensed under [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/).
