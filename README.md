# Bipbop

Play a virtual piano in the air with your webcam. MediaPipe tracks all 10 fingertips, and a key plays a live-synthesized piano note the moment a fingertip enters it. A built-in tutor teaches songs note by note.

## Quick start

**Browser:**
```powershell
python serve.py
```
Open the printed `http://127.0.0.1:8000/`, click **Start palying**, and play. You can also click or tap the keys, or use the computer keyboard (`Z X C V B N M` / `Q W E R T Y U I`).

**Desktop app:**
```powershell
python -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt
.venv\Scripts\python.exe air_piano.py          # add --learn for tutor mode
```

## Tutor

Highlights the next key, waits for you, and keeps score. Press **Listen** (browser) or `d` (desktop) to hear the song first. It ships with 17 hand-checked songs (`--list-songs`). Any other song can be looked up with a free AI model (Ollama locally, or `GEMINI_API_KEY` / `GROQ_API_KEY` / `OPENROUTER_API_KEY`). Small local models often get melodies wrong, so use a cloud key for reliability. Set `AIR_PIANO_LLM=off` to disable lookup.

## Common options

| Flag | Meaning |
|------|---------|
| `--camera N` | pick a camera |
| `--width 1280 --height 720` | bigger picture and keys |
| `--position center/top/bottom` | keyboard placement (`p` cycles live) |
| `--octaves 3` | more keys |
| `--shared` | don't take exclusive control of audio |
| `--song "Name"` | learn a specific song |

Desktop keys: `m` mute, `l` Learn mode, `d` demo, `r` restart, `[` `]` switch song, `k` skip, `q` quit.

## Tips

- Use a well-lit room, with hands 30-60 cm from the camera.
- Quick taps play louder.
- Dim lighting causes lag.

## Structure

- `air_piano.py`: desktop app
- `serve.py`: server and API
- `tutor.py`: songs and AI lookup
- `web/`: React 19 + Tailwind v4 + Vite UI (`npm run dev` / `npm run build`)

Tests: `python tests\run_all.py`
