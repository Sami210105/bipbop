/* Keyboard settings: where the keys sit, whether to draw hands, whether the
   computer keyboard plays, and volume. */

import { Sliders, Volume2 } from "./Icons";
import { Card, SectionLabel } from "./ui";

const POSITIONS = ["center", "top", "bottom"];

export default function Controls({
  position, onPosition, showHands, onShowHands, keyboard, onKeyboard, volume, onVolume,
}) {
  return (
    <Card className="p-4">
      <div className="mb-3 flex items-center gap-2">
        <Sliders className="h-4 w-4 text-muted" />
        <SectionLabel>Controls</SectionLabel>
      </div>

      <div className="flex flex-wrap items-center gap-x-6 gap-y-4">
        <div className="flex flex-col gap-1.5">
          <span className="text-xs font-medium text-muted">Keyboard position</span>
          <div className="inline-flex overflow-hidden rounded-full bg-cream ink-border-thin">
            {POSITIONS.map((p) => (
              <button
                key={p}
                type="button"
                aria-pressed={position === p}
                onClick={() => onPosition(p)}
                className={`px-3 py-1.5 text-xs font-semibold capitalize transition ${
                  position === p ? "bg-ink text-card" : "text-ink hover:bg-mist"
                }`}
              >
                {p}
              </button>
            ))}
          </div>
        </div>

        <div className="flex flex-col gap-1.5">
          <span className="text-xs font-medium text-muted">Hand guide</span>
          <button
            type="button"
            role="switch"
            aria-checked={showHands}
            onClick={() => onShowHands(!showHands)}
            className="lift inline-flex items-center gap-2 rounded-full bg-card ink-border px-3 py-1.5 text-sm font-medium"
          >
            <span
              className={`relative h-5 w-9 rounded-full ink-border-thin transition ${
                showHands ? "bg-mint" : "bg-mist"
              }`}
            >
              <span
                className={`absolute top-0.5 h-3.5 w-3.5 rounded-full bg-ink transition-all ${
                  showHands ? "left-[18px]" : "left-0.5"
                }`}
              />
            </span>
            {showHands ? "Shown" : "Hidden"}
          </button>
        </div>

        <div className="flex flex-col gap-1.5">
          <span className="text-xs font-medium text-muted">Computer keys</span>
          <button
            type="button"
            role="switch"
            aria-checked={keyboard}
            onClick={() => onKeyboard(!keyboard)}
            className="lift inline-flex items-center gap-2 rounded-full bg-card ink-border px-3 py-1.5 text-sm font-medium"
          >
            <span
              className={`relative h-5 w-9 rounded-full ink-border-thin transition ${
                keyboard ? "bg-mint" : "bg-mist"
              }`}
            >
              <span
                className={`absolute top-0.5 h-3.5 w-3.5 rounded-full bg-ink transition-all ${
                  keyboard ? "left-[18px]" : "left-0.5"
                }`}
              />
            </span>
            {keyboard ? "On" : "Off"}
          </button>
        </div>

        <div className="flex flex-col gap-1.5">
          <span className="text-xs font-medium text-muted">Volume</span>
          <label className="flex items-center gap-2">
            <Volume2 className="h-4 w-4 text-muted" />
            <input
              type="range"
              min="0"
              max="100"
              value={volume}
              onChange={(e) => onVolume(Number(e.target.value))}
              aria-label="Volume"
              className="w-32 accent-cobalt sm:w-44"
            />
            <span className="w-8 text-right font-display text-xs font-bold text-muted">{volume}</span>
          </label>
        </div>
      </div>
    </Card>
  );
}
