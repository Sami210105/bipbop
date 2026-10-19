/* The tutor card: look up or practise a song, one note at a time.

   Logic is unchanged from before - only the presentation is restyled. */

import { useState } from "react";
import { isWhite } from "../../piano-core.js";
import {
  GraduationCap, Info, Play, RefreshCw, Search, SkipForward, Sparkles, Square, Target,
} from "./Icons";
import { Badge, Button, Card, SectionLabel, Sticker } from "./ui";

export default function TutorPanel({
  llm, serverOK, busy, message,
  lesson, step, mode, index, misses, total, score, wrongTick,
  onLookup, onRegen, onListen, onPractice, onSkip, onStop,
}) {
  const [query, setQuery] = useState("");

  const submit = () => onLookup(query);
  const practicing = mode === "practice";
  const progress = total ? (index / total) * 100 : 0;
  const progressText = practicing
    ? `Note ${index + 1} of ${total}${misses ? ` · ${misses} wrong` : ""}`
    : `${index + 1} / ${total}`;
  const melody = lesson
    ? lesson.steps.map((s) => s.notes.join("+") + (s.beats !== 1 ? ":" + s.beats : "")).join("  ")
    : "";

  return (
    <Card className="flex flex-col gap-4 p-4 sm:p-5">
      <div className="flex items-center gap-2">
        <GraduationCap className="h-5 w-5" />
        <h2 className="font-display text-xl font-bold uppercase tracking-tight">Learn a song</h2>
        <span className="ml-auto">
          <Sticker tone="bright" rotate={3}>tutor</Sticker>
        </span>
      </div>

      {/* AI lookup */}
      <div className="flex flex-col gap-1.5">
        <SectionLabel>Look up any song</SectionLabel>
        <div className="flex gap-2">
          <div className="relative min-w-0 flex-1">
            <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted" />
            <input
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && submit()}
              placeholder="e.g. Bohemian Rhapsody"
              autoComplete="off"
              aria-label="Song title to look up"
              className="w-full rounded-full bg-card py-2 pl-9 pr-3 text-sm ink-border placeholder:text-muted"
            />
          </div>
          <Button variant="ink" onClick={submit} disabled={busy} icon={<Sparkles className="h-4 w-4" />}>
            {busy ? "…" : "Ask AI"}
          </Button>
        </div>
        {llm?.hint && (
          <details className="text-xs text-muted">
            <summary className="flex cursor-pointer select-none items-center gap-1">
              <Info className="h-3.5 w-3.5" /> How the AI lookup works
            </summary>
            <p className="mt-1 leading-relaxed">{llm.hint}</p>
          </details>
        )}
      </div>

      {message.text && (
        <div
          role="status"
          className={`rounded-xl px-3 py-2 text-sm ink-border-thin ${
            message.kind === "error"
              ? "bg-coral/30"
              : message.kind === "busy"
                ? "bg-bright/60"
                : "bg-mint/50"
          }`}
        >
          {message.text}
        </div>
      )}

      {/* empty state */}
      {!lesson && (
        <div className="rounded-xl bg-cream ink-border-thin px-3 py-6 text-center">
          <p className="text-sm text-muted">
            Pick a song from the library, or ask the AI to find one.
          </p>
        </div>
      )}

      {lesson && (
        <>
          <div className="flex items-start justify-between gap-2">
            <div className="min-w-0">
              <div className="truncate font-display text-lg font-bold uppercase tracking-tight">
                {lesson.title}
                {lesson.part && (
                  <span className="ml-2 align-middle text-[11px] font-bold normal-case tracking-normal text-muted">
                    {lesson.part}
                  </span>
                )}
              </div>
              <div className="mt-1 flex flex-wrap items-center gap-2 text-[11px] text-muted">
                <Badge tone={lesson.difficulty === "intermediate" ? "lavender" : "mint"} className="normal-case">
                  {lesson.difficulty}
                </Badge>
                <span>{lesson.tempo} BPM</span>
                <span>·</span>
                <span>{lesson.length} notes</span>
              </div>
            </div>
            {lesson.source !== "builtin" && (
              <button
                type="button"
                onClick={onRegen}
                title="Ask the model again"
                aria-label="Ask the model again"
                className="lift grid h-9 w-9 shrink-0 place-items-center rounded-full bg-card ink-border"
              >
                <RefreshCw className="h-4 w-4" />
              </button>
            )}
          </div>

          {/* the next notes to play */}
          <div
            key={wrongTick}
            className={`rounded-xl px-4 py-3 ink-border ${
              wrongTick ? "animate-pulse bg-coral/40" : "bg-bright"
            }`}
          >
            <div className="flex items-center gap-1.5 text-[10px] font-semibold uppercase tracking-wider text-ink/70">
              <Target className="h-3.5 w-3.5" /> Play this
            </div>
            <div className="font-display text-2xl font-bold tracking-tight text-ink">
              {step ? step.notes.join("  ") : "-"}
            </div>
          </div>

          {step && (
            <div className="flex flex-wrap gap-1.5">
              {step.notes.map((n) => (
                <span
                  key={n}
                  className={`rounded-md px-2 py-0.5 text-[11px] font-semibold ink-border-thin ${
                    isWhite(n) ? "bg-card text-ink" : "bg-ink text-card"
                  }`}
                >
                  {n} · {isWhite(n) ? "white" : "black"}
                </span>
              ))}
            </div>
          )}

          <div>
            <div className="h-2.5 overflow-hidden rounded-full bg-mist ink-border-thin">
              <div
                className="h-full rounded-full bg-cobalt transition-all"
                style={{ width: `${progress}%` }}
              />
            </div>
            <div className="mt-1 text-xs text-muted">{progressText}</div>
          </div>

          <div className="flex flex-wrap gap-2">
            <Button variant="outline" onClick={onListen} icon={<Play className="h-4 w-4" />}>
              Listen
            </Button>
            <Button
              variant={practicing ? "outline" : "primary"}
              onClick={onPractice}
              icon={<GraduationCap className="h-4 w-4" />}
            >
              {practicing ? "Restart" : "Practice"}
            </Button>
            {practicing && (
              <Button variant="ghost" onClick={onSkip} icon={<SkipForward className="h-4 w-4" />}>
                Skip
              </Button>
            )}
            <Button variant="ghost" onClick={onStop} icon={<Square className="h-4 w-4" />}>
              Stop
            </Button>
          </div>

          {score && (
            <div className="rounded-xl bg-mint/60 px-3 py-2 text-sm ink-border-thin">
              <b>Song complete!</b> {score.total} notes, {score.misses} wrong, {score.accuracy}% accuracy.
            </div>
          )}

          <details className="text-xs text-muted">
            <summary className="cursor-pointer select-none">Melody (as notes)</summary>
            <pre className="mt-1 max-h-32 overflow-auto whitespace-pre-wrap break-words rounded-lg bg-cream px-2 py-1.5 font-mono text-[11px] leading-relaxed ink-border-thin">
              {melody}
            </pre>
          </details>
        </>
      )}

      {!serverOK && (
        <p className="text-xs text-muted">
          The song list needs the local server - run <code className="font-mono">serve.py</code>.
        </p>
      )}
    </Card>
  );
}
