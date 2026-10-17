"""Static cross-checks for the React + Tailwind web app (no browser needed).

Catches the classic wiring mistakes: a source file that isn't there, an
import from piano-core.js that isn't exported, MediaPipe loaded eagerly (which
would break the offline-only page), or a stale build.
"""
import json
import re
import sys
from pathlib import Path

root = Path(__file__).resolve().parent.parent
web = root / "web"
src = web / "src"

fail = 0


def check(cond, label, extra=""):
    global fail
    print(("  ok   " if cond else "  FAIL ") + label + ("" if cond else f" {extra}"))
    if not cond:
        fail += 1


def read(p: Path) -> str:
    return p.read_text(encoding="utf-8")


print("=== the Vite entry point is in place ===")
index = read(web / "index.html")
check('id="root"' in index, "index.html has a #root element for React")
check('type="module"' in index and "/src/main.jsx" in index,
      "index.html loads /src/main.jsx as a module")

print("\n=== every source file the app needs exists ===")
needed = [
    "package.json",
    "vite.config.js",
    "piano-core.js",
    "src/main.jsx",
    "src/App.jsx",
    "src/index.css",
    "src/components/ui.jsx",
    "src/components/Icons.jsx",
    "src/components/Header.jsx",
    "src/components/Stage.jsx",
    "src/components/Controls.jsx",
    "src/components/SongList.jsx",
    "src/components/TutorPanel.jsx",
    "src/lib/audio.js",
    "src/lib/api.js",
    "src/lib/tracking.js",
    "src/lib/engine.js",
]
for rel in needed:
    check((web / rel).exists(), f"web/{rel}")

print("\n=== Vite config: React + Tailwind + /api proxy ===")
cfg = read(web / "vite.config.js")
check("@vitejs/plugin-react" in cfg, "React plugin configured")
check("@tailwindcss/vite" in cfg, "Tailwind v4 plugin configured")
check('"/api"' in cfg and "127.0.0.1:8000" in cfg, "/api proxied to serve.py in dev")

print("\n=== package.json scripts + devDependencies ===")
pkg = json.loads(read(web / "package.json"))
scripts = pkg.get("scripts", {})
check(scripts.get("dev") == "vite", "npm run dev -> vite")
check(scripts.get("build") == "vite build", "npm run build -> vite build")
devdeps = pkg.get("devDependencies", {})
for dep in ["vite", "@vitejs/plugin-react", "tailwindcss", "@tailwindcss/vite"]:
    check(dep in devdeps, f"devDependency {dep} declared")
check("react" in pkg.get("dependencies", {}), "react is a dependency")

print("\n=== every piano-core import is actually exported ===")
core = read(web / "piano-core.js")
exported = set(re.findall(r'export\s+(?:function|class|const|let)\s+(\w+)', core))
importers = ["src/App.jsx", "src/components/TutorPanel.jsx", "src/lib/engine.js"]
found_any = False
for rel in importers:
    text = read(web / rel)
    for m in re.finditer(r'import\s*\{([^}]+)\}\s*from\s*"[^"]*piano-core\.js"', text, re.S):
        found_any = True
        names = [n.strip() for n in m.group(1).split(",") if n.strip()]
        bad = [n for n in names if n not in exported]
        check(not bad, f"{rel}: {len(names)} core imports resolve", f"missing: {bad}")
check(found_any, "at least one module imports the shared piano-core.js")

print("\n=== Tailwind is wired through CSS ===")
check('@import "tailwindcss"' in read(web / "src/index.css"),
      'src/index.css imports tailwindcss')

print("\n=== MediaPipe is loaded lazily, pinned, and offline-safe ===")
tracking = read(web / "src/lib/tracking.js")
check("import(" in tracking and "vision_bundle.mjs" in tracking,
      "MediaPipe is loaded on demand with a dynamic import")
check("@vite-ignore" in tracking, "dynamic CDN import marked @vite-ignore")
check(not re.search(r'^\s*import\s+.*mediapipe', tracking, re.M | re.I),
      "no top-level MediaPipe import (page still loads when offline)")
check("@mediapipe/tasks-vision@1.1.1" in tracking, "MediaPipe JS pinned to 1.1.1")
check("hand_landmarker/float16/1/hand_landmarker.task" in tracking, "model URL present")

print("\n=== the engine drives the canvas through piano-core ===")
engine = read(web / "src/lib/engine.js")
for name in ["buildKeys", "FingerTracker", "noteFreq"]:
    check(name in engine, f"engine uses {name}() from piano-core")

print("\n=== the computer keyboard plays the piano ===")
check("KEY_MAP" in engine and "C#4" in engine, "engine maps computer keys to notes")
check('"keydown"' in engine and '"keyup"' in engine, "engine listens for keydown/keyup")
check("isTypingTarget" in engine, "typing in a text field never plays a note")
check('startsWith("kbd")' in core, "piano-core keeps held computer keys (releaseStale)")
controls = read(src / "components" / "Controls.jsx")
app = read(src / "App.jsx")
check("onKeyboard" in controls and "onKeyboard" in app,
      "a toggle in Controls turns the computer keyboard on/off")
check("KEYBOARD_LEGEND" in app, "the help card documents the key mapping")

print("\n=== the app talks to the serve.py API ===")
api = read(web / "src/lib/api.js")
check("/api/songs" in api, "api.js fetches /api/songs")
check("/api/lesson" in api, "api.js fetches /api/lesson")

print("\n=== has the app been built? (warning only) ===")
dist_index = web / "dist" / "index.html"
if dist_index.exists():
    check(True, "web/dist/index.html exists (built)")
else:
    print("  warn  web/dist not built yet - run: cd web && npm install && npm run build")

print(f"\n{'FAILED' if fail else 'web wiring looks correct'}")
sys.exit(1 if fail else 0)
