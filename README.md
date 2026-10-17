# Bipbop

Play a virtual piano floating in the air, using just your webcam and your fingertips.

The webcam feed is shown **mirrored** with two octaves of piano keys drawn over it.
The keyboard sits in the **centre** of the frame by default (right where your hands
naturally are) and is drawn semi-transparently, so you can always see your fingertips
landing on it. Press **`p`** at any time to move it to the top or bottom.
MediaPipe hand tracking follows all **10 of your fingertips** in real time - when a fingertip
enters a key, the note plays instantly (a piano tone synthesized live, no sound samples needed).

There is also a **tutor** that teaches you real songs note by note: it highlights the next
key to press, waits for you, keeps score, and can play the tune first so you know how it
goes. It ships with 17 hand-checked songs and can look up **any** song with a free AI model.
The tutor is available both in this desktop app and in the **browser version** (see below).

## Quick start

Two ways to play. The **browser version needs no build step** - the built page is already
included in the repo (`web/dist/`), and MediaPipe loads from a CDN on first play.

### 1. Browser (easiest - just Python)

```powershell
cd D:\air_piano
.venv\Scripts\python.exe serve.py        # or python serve.py (venv not required here)
```

`serve.py` prints a `http://127.0.0.1:8000/` address and opens it. Click **Start camera &
sound**, allow the camera, and play. This uses only the Python standard library, so you
don't need the virtualenv for the browser version.

### 2. Desktop app (needs the one-time setup)

See **Setup** below for creating `.venv` and installing dependencies. Then:

```powershell
cd D:\air_piano
.venv\Scripts\python.exe air_piano.py            # play
.venv\Scripts\python.exe air_piano.py --learn     # start in tutor mode
.venv\Scripts\python.exe air_piano.py --list-songs  # list songs
```

## Setup (already done - for reference or a fresh machine)

```powershell
cd D:\air_piano
python -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt
```

Everything (packages + the 7.8 MB hand-tracking model) lives inside `.venv`, nothing else
clutters the project folder. If the model file is ever missing, the app re-downloads it
into `.venv\models\hand_landmarker.task` automatically on first run.

## Run

```powershell
cd D:\air_piano
.venv\Scripts\python.exe air_piano.py
```

Options:

| Flag | Meaning |
|------|---------|
| `--camera 1` | use a different camera (e.g. an external webcam) |
| `--octaves 3` | show 3 octaves instead of 2 |
| `--position top` | where the keyboard sits: `center` (default), `top`, `bottom` |
| `--width 1280 --height 720` | ask the camera for a bigger picture - bigger keys, easier to hit |
| `--list-audio` | list audio devices and exit |
| `--audio-device "USB"` | pick an output device by index or name |
| `--blocksize 128` | smaller audio buffer, even lower latency |
| `--shared` | don't take exclusive control of the sound device |
| `--learn` | start in Learn mode (the tutor guides you through a song) |
| `--song "Let It Be"` | learn a specific song (built-in, or looked up with a free AI model) |
| `--list-songs` | list the built-in songs and exit |

On startup the app also prints a one-line camera report (resolution, measured frame
rate) and warns you if the picture is too dark or the camera is too slow - those are
the two things that most often make tracking feel laggy.

## Play in your browser (React + Tailwind)

The browser version lives in `web/` and is a **React 19 + Tailwind v4** app built with
**Vite**. It plays the same synthesized sound and has the same tutor as the desktop app;
the hand-tracking code is loaded from a CDN and runs inside the browser,
using the same 7.8 MB model.

```powershell
cd D:\air_piano\web
npm install
npm run build   # only needed if you change the UI; the built page is committed
cd ..
.venv\Scripts\python.exe serve.py
```

It prints a `http://127.0.0.1:8000/` address and opens it. Click **Start camera & sound**,
allow the camera, and play. `serve.py` uses only the Python standard library, so any
Python works - you don't need the virtualenv.

Why a little server instead of just opening the file? Browsers only allow camera access
on `http(s)://` or `localhost`, and the server also keeps any AI key off the page (see
below). Options: `--port 9000`, `--host 0.0.0.0` (share on your network), `--no-browser`.

### Editing the UI (hot reload)

For UI work, run the Vite dev server instead of rebuilding each time:

```powershell
# terminal 1 - the API (songs + AI lookup)
.venv\Scripts\python.exe serve.py --no-browser

# terminal 2 - the UI, with hot reload, at http://localhost:5173
cd web
npm run dev
```

Vite proxies `/api` to `serve.py`, so the page behaves the same and every source change
shows up instantly. Run `npm run build` afterwards to refresh `web/dist`.

The pieces: `web/index.html` (entry), `web/src/main.jsx`, `web/src/App.jsx`
(layout), `web/src/components/` (`Header`, `Stage`, `Controls`, `SongList`,
`TutorPanel`, plus the `ui.jsx` design-system primitives and `Icons.jsx`),
`web/src/lib/` (`engine.js`, `audio.js`, `tracking.js`, `api.js`), and the shared,
unit-tested `web/piano-core.js`.

### Design language

The look is a warm, retro-editorial "scrapbook" system, defined once in
`web/src/index.css` and reused through `web/src/components/ui.jsx`:

- **Palette tokens** (Tailwind v4 `@theme`): cream `#F7F5EA`, card `#FFFDF8`,
  ink `#20232B`, line `#292929`, coral `#FF796D`, cobalt `#3450C9`, mint
  `#A5E9D8`, lavender `#C9B7F4`, bright `#F9EF46`, muted `#77756F`, mist `#E6E3DB`.
- **Type**: Space Grotesk for headings, Inter for body (loaded from Google Fonts
  in `index.html`).
- **Primitives**: `Card`, `Button`, `Badge`, `Sticker`, `SectionLabel`, `Stat` -
  thick ink outlines, rounded corners, restrained print shadows, pastel accents.
- **Interaction**: the `.lift` class (hover lift + hard shadow) and one consistent
  focus ring, both disabled under `prefers-reduced-motion` / for keyboard users.

To retune the whole app, change the tokens in `index.css`; per-component styles
are plain Tailwind utility classes in the `.jsx` files - no separate stylesheet.

No webcam, or a browser that won't cooperate? **Click or tap the keys** - the browser
version also plays with a mouse or touchscreen, so you can try songs and the tutor without
a camera at all. It also degrades gracefully: if the CDN is unreachable it tells you, and
you can still play with the mouse.

### Playing with the computer keyboard

Prefer typing? Every key on the piano also answers to the computer keyboard, in the
usual two-row layout - left hand on the bottom row, right hand on the home row:

```
  Z X C V B N M     C4  D4  E4  F4  G4  A4  B4
  S D   G H J       C#4 D#4  F#4 G#4 A#4
  Q W E R T Y U I   C5  D5  E5  F5  G5  A5  B5  C6
  2 3   5 6 7       C#5 D#5  F#5 G#5 A#5
```

Each mapped letter is printed on its key on screen, so the mapping is always visible.
Keyboard presses play through the same path as fingertips and the mouse, so they count
for the tutor (including chords - hold several keys at once as you would several fingers).
Typing in a text field never plays a note. Turn the input off with the **Computer keys**
switch in Controls (the letters then disappear from the keys). The mapping in
`web/src/lib/engine.js` covers the full two octaves the piano draws (C4-C6).

### Performance (tuned for both fast and slow machines)

Hand tracking is the expensive part, and it decides how responsive the piano feels.
Rather than make the user think about any of that, the app measures its own machine
and adapts, silently. Nothing about the choice is shown in the interface.

- **The backend is chosen deliberately, not guessed.** Asking MediaPipe for its `GPU`
  delegate on a machine with no real GPU silently lands on a software renderer
  (SwiftShader), which is *slower* than the CPU/WASM path. `hasHardwareGPU()` in
  `src/lib/tracking.js` probes the renderer and selects the better one; a failed GPU
  init also downgrades cleanly.
- **Two profiles, picked at start** (`PROFILES` in `src/lib/engine.js`). The
  accelerated profile captures `640×480` and paces the model at up to ~60 runs/s; the
  conservative profile captures `480×360` and paces it lower. MediaPipe resizes to its
  own model input either way, so the smaller frame costs nothing in tracking quality.
- **Painting and inference run on separate loops.** The camera picture repaints every
  display frame; inference runs on its own paced timer, so a slow model no longer
  stutters the video.
- **Inference is paced, not flat-out.** The pause after each run scales with how long
  that run took (`duty`), leaving the main thread free so a key you touch starts its
  note without waiting behind the next inference.
- **The static keyboard is cached offscreen** and blitted each frame; only lit keys,
  tutor markers and hand dots are repainted.
- Audio uses an `interactive` latency hint and pre-synthesises its note buffers while
  idle.

## Learn a song (the tutor)

The tutor turns a song into a guided lesson: it marks the next key(s) to play, waits for
you to actually play them, keeps score, and can demonstrate the song first.

**In the browser:** pick a song from the **Song library** and press **Practice**. Press **Listen**
to hear it first. The next key is highlighted in gold on the keyboard and named in words
(for example `C#4 - black key · left half`). Wrong notes flash red and are counted.
**In the desktop app:** press **`l`** to enter Learn mode, **`d`** to hear the song, then
play along with the pulsing gold marker.

You can also **look up any song** that isn't built in. In the browser, type a title in the
"look up any song" box. In the desktop app, type a name into the console (the window you
launched it from) and press Enter, or start with `--song "Let It Be"`.

### Built-in songs

17 hand-verified, public-domain tunes and exercises - all playable on the two-octave
keyboard (C4-C6). See them with:

```powershell
.venv\Scripts\python.exe air_piano.py --list-songs
```

Beginner: Twinkle Twinkle, Mary Had a Little Lamb, Hot Cross Buns, Jingle Bells,
Ode to Joy, Row Row Row Your Boat, London Bridge, Frère Jacques, Old MacDonald.
Intermediate: Happy Birthday, When the Saints, Silent Night, Amazing Grace, Für Elise.
Exercises: C Major Scale, Black Key Walk, C and G Chords.

### AI song lookup (free, optional)

If a song isn't built in, the tutor can ask a free AI model for the notes. It tries, in
order, whatever is configured:

| Provider | How to enable | Notes |
|----------|---------------|-------|
| **Ollama** (local) | just have [Ollama](https://ollama.com) running | free and offline; a small model may get the melody wrong |
| Google Gemini | set `GEMINI_API_KEY` (free key from Google AI Studio) | fast, good at recalling tunes |
| Groq | set `GROQ_API_KEY` (free tier) | fast, good at recalling tunes |
| OpenRouter | set `OPENROUTER_API_KEY` (free models) | has free models |

Examples:

```powershell
# use your local Ollama model (no key, works offline)
.venv\Scripts\python.exe air_piano.py --song "Auld Lang Syne"

# or point a free cloud model at it
$env:GEMINI_API_KEY = "your-key-here"
.venv\Scripts\python.exe serve.py
```

**Be honest about quality:** the app shows the melody and can play it back *before* you
learn it, so you can judge it. Melodies come from the model's own knowledge, and **small
local models regularly get a song wrong** (they may invent a plausible-sounding scale
instead of the real tune). Free cloud models are much more reliable. If a melody is wrong,
press the refresh button in the browser (or re-run the lookup) to try again - answers are cached
in `.cache/songs/`. Hand-checked built-in songs are always exact.

Useful environment variables: `AIR_PIANO_LLM=off` disables lookup entirely (built-in songs
only), `AIR_PIANO_OLLAMA_MODEL=qwen2.5:7b` picks a bigger local model, and
`AIR_PIANO_LLM_TIMEOUT` (seconds) caps a slow lookup.

## Latency (why playing feels instant)

The app probes audio backends on startup and picks the fastest one that works,
then prints what it chose, and the HUD shows live tracking + audio latency:

| Backend | Latency on this machine |
|---------|------------------------|
| WASAPI exclusive | **~13 ms** (chosen by default) |
| WDM-KS (`--shared`) | ~15 ms |
| WASAPI shared | ~27 ms |
| MME (Windows default) | ~105 ms |

Tracking is the other half of the feel, and it is usually the bigger cost: the hand
model takes tens of milliseconds per frame on a laptop CPU (watch the HUD's `track X ms`),
and the camera's own frame rate adds to that. So for the snappiest playing:

- keep the room **well lit** (a dark image makes the camera stretch its exposure and
  drop its frame rate - the app warns you about this on startup);
- close other apps that are using the camera;
- if the window feels small, ask for a bigger picture with `--width 1280 --height 720`
  so the keys are wider and easier to aim at.

Everything is synthesized on the fly, so there is no sample loading or file playback
delay - notes start the moment a fingertip enters a key.

**Note on `--shared`:** the default WASAPI-exclusive mode takes over the sound
device, so other apps (music, video) go silent while the piano runs. Add
`--shared` if you'd rather keep other audio playing - it costs ~2-10 ms.


## Controls

| Key | Action |
|-----|--------|
| `ESC` or `q` | quit |
| `m` | mute / unmute |
| `space` | pause / resume the key display |
| `p` | move the keyboard: centre → top → bottom |
| `h` | toggle help text |
| `l` | Learn mode on/off |
| `d` | play the current song (hear it first) |
| `r` | restart the current song |
| `[` / `]` | previous / next built-in song |
| `k` | skip to the next note |
| type a song name + `Enter` | look up any song (in the console window) |

The HUD (top-left) shows FPS, `track` ms, `audio` ms and the number of notes
currently ringing (`voices`), plus `[LEARN]` while the tutor is on.

### Where the keyboard sits

The default **centre** position puts the keys right where your hands already are, so
you don't have to reach. Because the keys are semi-transparent and your hand skeleton
is drawn *on top* of them, you can always see your fingertips landing.

| Position | When to use it |
|----------|----------------|
| `center` (default) | hands resting naturally in front of you |
| `top` | arm's-length reach, or if you'd rather not have keys under your hands |
| `bottom` | hands stay low; keys out of the way while you gesture |

Press `p` to cycle between them live and keep whichever feels best; start with
`--position top` if you want to begin there.

## Tips for best results

- Sit facing a **well-lit** room; avoid strong backlight (window behind you).
- Hold your hands about **30-60 cm** from the camera, palms facing it.
- Small, quick finger taps feel most like a real piano - and they also play
  **louder** (the app turns fingertip speed into strike strength, so gentle
  drifts stay soft and quick taps ring out).
- All 10 fingers work independently, including the **black keys**, so you can
  play full two-handed chords or fast runs.
- Aiming is easiest with a bigger window: try `--width 1280 --height 720`, which
  roughly doubles the width of every key.

## How the sound blends

Singing 10 notes at once used to clip and turn harsh. The mixer now has proper
gain staging and a master limiter, so chords stay loud but smooth:

- each note is rendered with headroom, then a **limiter** pulls the mix down
  instantly when a big chord lands and **eases back up over ~150 ms**, so
  ringing notes keep their natural decay instead of being squashed;
- a final **soft-clip** (never a hard edge) catches anything left over;
- high partials fade faster than the fundamental, so notes mellow out as they
  ring rather than turning into a buzz;
- every note gets an 8 ms bloom-in and a fade-out, so there are no clicks;
- fingertip wobble at a key edge can no longer machine-gun retriggers
  (a 50 ms cooldown plus a release margin means one press = one note).

The HUD shows `voices: N`, so you can watch 10 notes ring at the same time.


## Troubleshooting

- **No window / camera error** - try `python air_piano.py --camera 1`.
- **Other apps lost their sound** - the app uses WASAPI exclusive mode. Run with
  `--shared` to let other apps play audio too.
- **Sound lags behind your fingers** - run `--list-audio` and pick a device with a
  WASAPI or WDM-KS entry, or lower `--blocksize 128`. Check the HUD's `audio X ms`.
- **Choppy tracking** - the HUD shows `track X ms` and FPS. Close other apps using
  the camera, and avoid dim lighting (long camera exposure adds lag). The startup
  report names the culprit if your picture is too dark or your camera too slow.
- **The window is tiny / keys hard to hit** - run with `--width 1280 --height 720`
  (or try `--camera 1`) to get a bigger picture and wider keys.
- **A key won't sound** - make sure your fingertip is clearly inside the key, then
  lift it off and tap again. Notes deliberately don't repeat until you leave the key.
- **No sound** - check your volume, and look at the HUD: it shows which audio backend
  is active (`sounddevice`, or `winsound` fallback on Windows).
- **Browser page: camera won't start** - allow camera access when prompted, make sure
  you opened the `http://127.0.0.1:.../` address `serve.py` printed (not the file
  directly), and that no other program is holding the camera. Clicking the on-screen
  keys still works without a camera.
- **Browser page: nothing happens / it says it can't load** - the hand-tracking code
  comes from a CDN, so the first load needs internet. Check the browser console (F12).
  You can still play with the mouse.
- **A looked-up song sounds wrong** - the AI guessed it, and small local models often
  do. Press refresh to ask again (a different answer is often better), or set a free
  `GEMINI_API_KEY`/`GROQ_API_KEY` for reliable recall. Built-in songs are hand-checked
  and always correct. `AIR_PIANO_LLM=off` disables lookup entirely.
- **A lookup seems to hang** - a local model can take a minute or more per song; the
  cap is `AIR_PIANO_LLM_TIMEOUT` seconds (default 180). Answers are cached in
  `.cache/songs/`, so the second time is instant.
- **Restart the tutor song** - `r` in the desktop app, or pick the song again in the
  browser.
- **Reinstall from scratch** - delete `.venv` and re-run the setup steps above. To
  remove every trace, also delete `.cache\` (cached AI songs) - nothing else is written
  outside the project folder.

## How it's put together

| File | What it is |
|------|------------|
| `air_piano.py` | the desktop app: camera, hand tracking, keyboard, audio, Learn mode |
| `serve.py` | a tiny standard-library server: serves the built app (`web/dist`) + the JSON API |
| `tutor.py` | the shared song/lesson library: 17 built-in songs + AI lookup + cache |
| `web/` | the browser app: React 19 + Tailwind v4, built with Vite (`npm run dev` / `npm run build`) |
| `web/src/` | `App.jsx`, `components/` (Header, Stage, Controls, SongList, TutorPanel, ui, Icons) and `lib/` (engine, audio, tracking, api) |
| `web/piano-core.js` | the pure keyboard/tutor logic, shared with the desktop app and unit-tested |
| `web/dist/` | the built page that `serve.py` serves (committed to the repo so it runs without `npm build`) |
| `.venv\models\hand_landmarker.task` | the hand-tracking model (downloaded on first run) |
| `.cache/songs/` | lessons looked up with AI, cached so they load instantly next time |

`air_piano.py` and `serve.py` both import `tutor.py`, so the desktop app and the web page
teach exactly the same songs from the same lessons.

## Tests

There is a small test suite in `tests/` (no camera, audio device or internet needed - the
tests never call an AI model):

```powershell
.venv\Scripts\python.exe tests\run_all.py
```

It checks the song library and lookup, the shared keyboard/tutor logic the browser uses,
the desktop Learn mode, and it runs the desktop app's real frame loop with a stubbed camera.
`node tests/test_core.mjs` runs just the browser-logic tests.

## Credits

The key-signature graphic used as the decorative hero backdrop comes from
[B-flat-major g-minor.svg](https://commons.wikimedia.org/wiki/File:B-flat-major_g_minor.svg)
by [Rettinghaus](https://commons.wikimedia.org/wiki/User:Rettinghaus), via Wikimedia Commons,
licensed under [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/).
