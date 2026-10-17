/* ==========================================================================
   Bipbop - browser edition (React + Tailwind)

   React owns the visible chrome and the tutor; BipbopEngine owns the 60 fps
   canvas/camera/tracking loop. The two meet at a handful of callbacks, so the
   animation loop never triggers a React re-render.
   ========================================================================== */

import { useCallback, useEffect, useRef, useState } from "react";
import { TutorEngine } from "../piano-core.js";
import { BipbopEngine } from "./lib/engine.js";
import { fetchLesson, fetchSongs } from "./lib/api.js";
import Header from "./components/Header.jsx";
import Stage from "./components/Stage.jsx";
import Controls from "./components/Controls.jsx";
import SongList from "./components/SongList.jsx";
import TutorPanel from "./components/TutorPanel.jsx";
import { Camera, GraduationCap, HandPoint, KeySignature } from "./components/Icons.jsx";
import { Button, Card, SectionLabel, Stat } from "./components/ui.jsx";

const TIPS = [
  "Sit facing a well-lit room; avoid strong backlight behind you.",
  "Hold your hands about 30-60 cm from the camera, palms toward it.",
  "Quick finger taps play louder; gentle drifts stay soft.",
  "All ten fingers work independently, black keys included.",
  "No webcam? Click or tap the keys with the mouse.",
  "Prefer typing? Every key also plays from the computer keyboard.",
  "A bigger window makes every key easier to hit.",
];

/* The computer-keyboard mapping, mirrored on the on-screen keys. Two octaves,
   left hand on the bottom row, right hand on the home row. */
const KEYBOARD_LEGEND = [
  ["Z", "C4"], ["S", "C#4"], ["X", "D4"], ["D", "D#4"], ["C", "E4"],
  ["V", "F4"], ["G", "F#4"], ["B", "G4"], ["H", "G#4"], ["N", "A4"],
  ["J", "A#4"], ["M", "B4"],
  ["Q", "C5"], ["2", "C#5"], ["W", "D5"], ["3", "D#5"], ["E", "E5"],
  ["R", "F5"], ["5", "F#5"], ["T", "G5"], ["6", "G#5"], ["Y", "A5"],
  ["7", "A#5"], ["U", "B5"], ["I", "C6"],
];

export default function App() {
  const canvasRef = useRef(null);
  const videoRef = useRef(null);
  const engineRef = useRef(null);
  const tutorRef = useRef(new TutorEngine());
  const demoTimers = useRef([]);

  const [, setVersion] = useState(0); // bump to re-render after engine/tutor changes
  const [started, setStarted] = useState(false);
  const [notice, setNotice] = useState("");
  const [handsOn, setHandsOn] = useState(false);
  const [songs, setSongs] = useState([]);
  const [llm, setLlm] = useState(null);
  const [serverOK, setServerOK] = useState(true);
  const [message, setMessage] = useState({ text: "", kind: "" });
  const [score, setScore] = useState(null);
  const [busy, setBusy] = useState(false);
  const [wrongTick, setWrongTick] = useState(0);

  const [position, setPosition] = useState("center");
  const [showHands, setShowHands] = useState(true);
  const [keyboard, setKeyboard] = useState(true);
  const [volume, setVolume] = useState(80);
  const [muted, setMuted] = useState(false);

  /* Push the tutor's current step onto the on-canvas gold markers. */
  const applyGuide = useCallback(() => {
    const tutor = tutorRef.current;
    const step = tutor.step;
    const labels = tutor.mode === "practice" && step ? step.notes : [];
    engineRef.current?.setGuideNotes(labels);
  }, []);

  /* ------------------------------------------------------- the engine */

  useEffect(() => {
    const engine = new BipbopEngine(canvasRef.current, videoRef.current, {
      onPress: (label) => {
        const ev = tutorRef.current.onKeyPressed(label);
        if (!ev) return;
        if (ev.type === "wrong") {
          setWrongTick((t) => t + 1);
          setMessage({
            text: `That was ${ev.pressed} - play ${ev.expected.join(" + ")}`,
            kind: "error",
          });
        } else if (ev.type === "complete") {
          setScore({ total: ev.total, misses: ev.misses, accuracy: ev.accuracy });
          setMessage({ text: "Song complete! Well done.", kind: "ok" });
        }
        applyGuide();
        setVersion((v) => v + 1);
      },
      onFrame: (tracker) => {
        if (tutorRef.current.forgetPartialIfLifted(tracker.anyPressed())) {
          applyGuide();
          setVersion((v) => v + 1);
        }
      },
      onHands: setHandsOn,
      onNotice: (text) => setNotice(text || ""),
    });
    engineRef.current = engine;
    return () => engine.stop();
  }, [applyGuide]);

  /* ------------------------------------------------------- songs + llm */

  const loadSongs = useCallback(async () => {
    try {
      const data = await fetchSongs();
      setSongs(data.songs || []);
      setLlm(data.llm || null);
      setServerOK(true);
    } catch {
      setServerOK(false);
      setSongs([]);
      setLlm({ hint: "Server not reachable. Start serve.py for songs and AI lookup." });
    }
  }, []);

  useEffect(() => {
    loadSongs();
  }, [loadSongs]);

  /* ----------------------------------------------------------- actions */

  const start = async () => {
    const engine = engineRef.current;
    if (!engine) return;
    setNotice("");
    await engine.start();
    engine.setVolume(volume / 100);
    engine.setShowHands(showHands);
    engine.setKeyboard(keyboard);
    setStarted(true);
    applyGuide();
    setVersion((v) => v + 1);
  };

  const lookupSong = useCallback(
    async (title, refresh = false) => {
      const t = (title || "").trim();
      if (!t) {
        setMessage({ text: "Type a song name first.", kind: "error" });
        return;
      }
      setBusy(true);
      setMessage({
        text: `Asking the model about “${t}”… a local model can take a minute.`,
        kind: "busy",
      });
      try {
        const lesson = await fetchLesson(t, refresh);
        tutorRef.current.load(lesson);
        setScore(null);
        applyGuide();
        setVersion((v) => v + 1);
        setMessage({ text: `Loaded “${lesson.title}”. Press Practice, or Listen first.`, kind: "ok" });
      } catch (err) {
        setMessage({ text: err.message, kind: "error" });
      } finally {
        setBusy(false);
      }
    },
    [applyGuide],
  );

  const stopDemo = useCallback(() => {
    demoTimers.current.forEach(clearTimeout);
    demoTimers.current = [];
  }, []);

  const listen = () => {
    const tutor = tutorRef.current;
    const lesson = tutor.lesson;
    const engine = engineRef.current;
    if (!lesson || !engine) return;
    stopDemo();
    tutor.stop();
    tutor.mode = "listen";
    applyGuide();
    setVersion((v) => v + 1);

    const spb = 60 / lesson.tempo;
    let t = 0;
    lesson.steps.forEach((s) => {
      const at = t;
      t += s.beats * spb;
      demoTimers.current.push(
        setTimeout(() => s.notes.forEach((n) => engine.hear(n)), at * 1000),
      );
    });
    demoTimers.current.push(
      setTimeout(() => {
        tutor.mode = null;
        applyGuide();
        setVersion((v) => v + 1);
      }, t * 1000 + 400),
    );
  };

  const practice = () => {
    if (tutorRef.current.startPractice()) {
      setScore(null);
      setMessage({ text: "Practice started - play the highlighted keys.", kind: "ok" });
      applyGuide();
      setVersion((v) => v + 1);
    }
  };

  const skip = () => {
    const ev = tutorRef.current.skip();
    if (ev?.type === "complete") {
      setScore({ total: ev.total, misses: ev.misses, accuracy: ev.accuracy });
    }
    applyGuide();
    setVersion((v) => v + 1);
  };

  const stop = () => {
    stopDemo();
    tutorRef.current.stop();
    setScore(null);
    setMessage({ text: "Stopped.", kind: "" });
    applyGuide();
    setVersion((v) => v + 1);
  };

  const regen = () => {
    const lesson = tutorRef.current.lesson;
    if (lesson) lookupSong(lesson.title, true);
  };

  const changePosition = (p) => {
    setPosition(p);
    engineRef.current?.setPosition(p);
    applyGuide();
    setVersion((v) => v + 1);
  };
  const changeShowHands = (v) => {
    setShowHands(v);
    engineRef.current?.setShowHands(v);
  };
  const changeKeyboard = (v) => {
    setKeyboard(v);
    engineRef.current?.setKeyboard(v);
  };
  const changeVolume = (v) => {
    setVolume(v);
    engineRef.current?.setVolume(v / 100);
  };
  const toggleMute = () => {
    const m = !muted;
    setMuted(m);
    engineRef.current?.setMuted(m);
  };

  /* ------------------------------------------------------------ render */

  const tutor = tutorRef.current;

  return (
    <div className="paper min-h-screen">
      <Header muted={muted} onMute={toggleMute} />

      {/* ------------------------------------------------------- hero */}
      <section id="top" className="mx-auto max-w-6xl scroll-mt-24 px-4 pt-6">
        <div className="hard-shadow relative overflow-hidden rounded-2xl bg-cobalt px-6 py-8 text-card ink-border sm:px-9 sm:py-10">

          <div aria-hidden="true" className="pointer-events-none absolute inset-0">
            <KeySignature className="absolute right-20 top-2 h-68 w-auto text-card/25" />
            {/* the keyboard strip along the bottom */}
            <div className="absolute bottom-0 right-8 hidden items-end gap-1.5 sm:flex">
              {[0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11].map((i) => (
                <span
                  key={i}
                  className={`h-16 w-5 rounded-t-md border-2 border-line ${
                    i % 2 ? "bg-card/85" : "bg-card/25"
                  }`}
                />
              ))}
            </div>
          </div>

          <div className="relative max-w-2xl">
            <h1 className="font-display text-4xl font-bold uppercase leading-[0.92] tracking-tight sm:text-5xl">
              Who needs a piano?
            </h1>
            <p className="mt-3 max-w-xl text-sm leading-relaxed text-card/85 sm:text-base">
              Turn the space in front of your webcam into a virtual piano. Play notes with simple finger gestures, experiment with melodies, and learn your favorite songs one note at a time.
            </p>
            <div className="mt-5 flex flex-wrap gap-2">
              <Button variant="bright" size="lg" onClick={start} icon={<Camera className="h-4 w-4" />}>
                Start playing!
              </Button>
              <Button variant="outline" size="lg" href="#learn" icon={<GraduationCap className="h-4 w-4" />}>
                Learn a song
              </Button>
            </div>
            <div className="mt-6 flex flex-wrap gap-2">
              <Stat label="Keyboard" value="C4-C6" />
              <Stat label="Fingers" value="10" />
              <Stat label="Songs" value="17+" />
            </div>
          </div>
        </div>
      </section>

      {/* ------------------------------------------------- play + learn */}
      <section id="play" className="mx-auto max-w-6xl scroll-mt-24 px-4 py-6">
        <div className="grid gap-4 lg:grid-cols-[2fr_1fr]">
          <div className="flex flex-col gap-4">
            <Stage
              canvasRef={canvasRef}
              videoRef={videoRef}
              started={started}
              notice={notice}
              onStart={start}
              handsOn={handsOn}
            />
          </div>

          <div id="learn" className="flex flex-col gap-4 scroll-mt-24 lg:justify-between">
            <TutorPanel
              llm={llm}
              serverOK={serverOK}
              busy={busy}
              message={message}
              lesson={tutor.lesson}
              step={tutor.step}
              mode={tutor.mode}
              index={tutor.index}
              misses={tutor.misses}
              total={tutor.lesson?.steps.length || 0}
              score={score}
              wrongTick={wrongTick}
              onLookup={(t) => lookupSong(t)}
              onRegen={regen}
              onListen={listen}
              onPractice={practice}
              onSkip={skip}
              onStop={stop}
            />

            <Controls
              position={position}
              onPosition={changePosition}
              showHands={showHands}
              onShowHands={changeShowHands}
              keyboard={keyboard}
              onKeyboard={changeKeyboard}
              volume={volume}
              onVolume={changeVolume}
            />
          </div>
        </div>
      </section>

      {/* -------------------------------------------------------- songs */}
      <section id="songs" className="mx-auto max-w-6xl scroll-mt-24 px-4 pb-6">
        <SongList
          songs={songs}
          serverOK={serverOK}
          activeTitle={tutor.lesson?.title}
          onSelect={lookupSong}
        />
      </section>

      {/* --------------------------------------------------------- help */}
      <section id="help" className="mx-auto max-w-6xl scroll-mt-24 px-4 pb-10">
        <Card accent="cobaltSoft" className="p-4 sm:p-5">
          <div className="flex items-center gap-2">
            <HandPoint className="h-5 w-5" />
            <SectionLabel>
              <span className="text-card/75">How to play</span>
            </SectionLabel>
          </div>
          <ul className="mt-3 grid gap-2 text-sm sm:grid-cols-2">
            {TIPS.map((tip) => (
              <li key={tip} className="flex items-start gap-2">
                <span className="mt-1.5 h-2 w-2 shrink-0 rounded-full bg-bright" aria-hidden="true" />
                <span className="text-card/90">{tip}</span>
              </li>
            ))}
          </ul>

          <div className="mt-4 rounded-xl bg-cream p-3 ink-border-thin">
            <div className="text-[11px] font-semibold uppercase tracking-wider text-muted">
              Computer keyboard
            </div>
            <p className="mt-1 text-sm text-ink/85">
              Press <b>Start camera &amp; sound</b> first, then play with the keyboard left
              hand on the bottom row, right hand on the home row. The letters are printed on
              the keys.
            </p>
            <ul className="mt-2 flex flex-wrap gap-1.5">
              {KEYBOARD_LEGEND.map(([key, note]) => (
                <li
                  key={key}
                  className="inline-flex items-center gap-1 rounded-md bg-card px-1.5 py-0.5 ink-border-thin"
                >
                  <kbd className="font-display text-xs font-bold text-ink">{key}</kbd>
                  <span className="text-[11px] text-muted">{note}</span>
                </li>
              ))}
            </ul>
          </div>
        </Card>

        <p className="mt-6 text-center text-xs text-muted">
          Bipbop - a webcam piano and tutor.
        </p>
        
      </section>
    </div>
  );
}
