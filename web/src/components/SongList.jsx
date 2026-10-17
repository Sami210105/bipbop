/* The built-in song library: pick a tune to load into the tutor.

   This is just the existing song selector given a roomier, editorial treatment —
   a filterable list of rows, not a music-streaming shelf. */

import { memo, useMemo, useState } from "react";
import { Music, Play } from "./Icons";
import { Badge, Card, SectionLabel } from "./ui";

const FILTERS = [
  { id: "all", label: "All" },
  { id: "beginner", label: "Beginner" },
  { id: "intermediate", label: "Intermediate" },
  { id: "exercise", label: "Exercises" },
];

const tone = (difficulty) => (difficulty === "intermediate" ? "lavender" : "mint");

function SongList({ songs, serverOK, activeTitle, onSelect }) {
  const [filter, setFilter] = useState("all");

  const shown = useMemo(() => {
    if (filter === "all") return songs;
    if (filter === "exercise") return songs.filter((s) => /^Exercise:/i.test(s.title));
    return songs.filter((s) => s.difficulty === filter);
  }, [songs, filter]);

  return (
    <Card className="p-4 sm:p-5">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <SectionLabel>Song library</SectionLabel>
          <h2 className="mt-1 font-display text-xl font-bold uppercase tracking-tight sm:text-2xl">
            {songs.length ? `${songs.length} built-in songs` : "Built-in songs"}
          </h2>
        </div>
        <div className="flex flex-wrap gap-1.5">
          {FILTERS.map((f) => (
            <button
              key={f.id}
              type="button"
              aria-pressed={filter === f.id}
              onClick={() => setFilter(f.id)}
              className={`rounded-full px-3 py-1 text-xs font-semibold transition ink-border-thin ${
                filter === f.id ? "bg-cobalt text-card" : "bg-cream text-ink hover:bg-mist"
              }`}
            >
              {f.label}
            </button>
          ))}
        </div>
      </div>

      {!serverOK && (
        <p className="mt-4 rounded-xl bg-bright/60 ink-border-thin px-3 py-2 text-sm">
          Start <code className="font-mono">serve.py</code> to load the song list.
        </p>
      )}

      {serverOK && !songs.length && (
        <p className="mt-4 text-sm text-muted">Loading songs…</p>
      )}

      <ul className="mt-4 grid gap-2 sm:grid-cols-2 xl:grid-cols-3">
        {shown.map((s) => {
          const active = s.title === activeTitle;
          return (
            <li key={s.slug || s.title}>
              <button
                type="button"
                onClick={() => onSelect(s.title)}
                aria-pressed={active}
                className={`lift flex w-full items-center gap-3 rounded-xl p-2.5 text-left ink-border ${
                  active ? "bg-mint" : "bg-card"
                }`}
              >
                <span
                  className={`grid h-10 w-10 shrink-0 place-items-center rounded-xl ink-border-thin ${
                    active ? "bg-card" : "bg-cream"
                  }`}
                >
                  <Music className="h-4 w-4" />
                </span>
                <span className="min-w-0 flex-1">
                  <span className="block truncate font-display text-sm font-bold uppercase tracking-tight">
                    {s.title}
                  </span>
                  <span className="mt-0.5 flex items-center gap-2 text-[11px] text-muted">
                    <Badge tone={tone(s.difficulty)} className="normal-case">{s.difficulty}</Badge>
                    <span>{s.tempo} BPM</span>
                    <span>·</span>
                    <span>{s.length} notes</span>
                  </span>
                </span>
                <span className="grid h-8 w-8 shrink-0 place-items-center rounded-full bg-ink text-card">
                  <Play className="h-3.5 w-3.5" />
                </span>
              </button>
            </li>
          );
        })}
      </ul>
    </Card>
  );
}

/* The library only changes when its own props do, so keep it out of the
   per-press re-renders that App does while you play. */
export default memo(SongList);
