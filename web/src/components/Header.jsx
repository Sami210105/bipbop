import { Keyboard, Volume2, VolumeX } from "./Icons";

const NAV = [
  { href: "#play", label: "Play" },
  { href: "#learn", label: "Learn" },
  { href: "#songs", label: "Songs" },
  { href: "#help", label: "Help" },
];

export default function Header({ muted, onMute }) {
  return (
    <header className="sticky top-0 z-30 border-b-2 border-line bg-cream/85 backdrop-blur">
      <div className="mx-auto flex max-w-6xl items-center gap-3 px-4 py-3">
        <a href="#top" className="flex items-center gap-2.5">
          <span className="grid h-9 w-9 place-items-center rounded-xl bg-coral ink-border hard-shadow-sm">
            <Keyboard className="h-4 w-4" />
          </span>
          <span className="leading-tight">
            <span className="block font-display text-base font-bold uppercase tracking-tight">
              Bipbop
            </span>
            <span className="block text-[10px] uppercase tracking-[0.18em] text-muted">
              Webcam · Tutor
            </span>
          </span>
        </a>

        <nav className="ml-4 hidden items-center gap-1 md:flex" aria-label="Sections">
          {NAV.map((n) => (
            <a
              key={n.href}
              href={n.href}
              className="rounded-full px-3 py-1.5 text-sm font-medium text-ink/80 transition hover:bg-mist"
            >
              {n.label}
            </a>
          ))}
        </nav>

        <div className="ml-auto flex items-center gap-2">
          <button
            type="button"
            onClick={onMute}
            aria-label={muted ? "Unmute" : "Mute"}
            aria-pressed={muted}
            title={muted ? "Unmute" : "Mute"}
            className="lift grid h-9 w-9 place-items-center rounded-full bg-card ink-border"
          >
            {muted ? <VolumeX className="h-4 w-4" /> : <Volume2 className="h-4 w-4" />}
          </button>
        </div>
      </div>
    </header>
  );
}
