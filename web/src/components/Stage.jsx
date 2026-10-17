/* The live keyboard: the hand-tracking canvas over a mirrored camera feed.

   React only decides whether the "start" overlay is showing and whether hands
   are currently being seen; the canvas and video elements are driven
   imperatively by BipbopEngine. Nothing here reflects the machine's
   capabilities — the status badge is purely about your hands. */

import { Camera } from "./Icons";
import { Button, Card, SectionLabel, Sticker } from "./ui";

function Status({ started, handsOn }) {
  if (!started) return <Sticker tone="mist">idle</Sticker>;
  if (handsOn) return <Sticker tone="mint" rotate={-3}>✋ hands in view</Sticker>;
  return <Sticker tone="coral" rotate={-3}>● live</Sticker>;
}

export default function Stage({ canvasRef, videoRef, started, notice, onStart, handsOn }) {
  return (
    <Card className="p-3 sm:p-4">
      <div className="mb-3 flex items-center gap-2">
        <SectionLabel>Live keyboard</SectionLabel>
        <span className="ml-auto">
          <Status started={started} handsOn={handsOn} />
        </span>
      </div>

      <div className="relative aspect-video w-full overflow-hidden rounded-xl ink-border bg-ink">
        {/* the camera feed is drawn mirrored onto the canvas, so hide the element */}
        <video
          ref={videoRef}
          playsInline
          muted
          autoPlay
          className="pointer-events-none absolute inset-0 h-full w-full opacity-0"
        />
        <canvas ref={canvasRef} className="stage-canvas absolute inset-0" />

        {!started && (
          <div className="absolute inset-0 grid place-items-center bg-ink/80 p-6 text-center">
            <div className="flex max-w-sm flex-col items-center gap-4">
              <span className="grid h-14 w-14 place-items-center rounded-2xl bg-bright ink-border">
                <Camera className="h-6 w-6" />
              </span>
              <h2 className="font-display text-xl font-bold uppercase tracking-tight text-card">
                Allow your camera
              </h2>
              <p className="text-sm leading-relaxed text-card/80">
                Hold your hands up and touch the floating keys with your fingertips. No camera?
                Click the keys with your mouse or tap them.
              </p>
              <Button variant="bright" size="lg" onClick={onStart} icon={<Camera className="h-4 w-4" />}>
                Start camera &amp; sound
              </Button>
            </div>
          </div>
        )}

        {notice && (
          <div
            role="status"
            className="absolute inset-x-3 bottom-3 rounded-xl bg-bright ink-border px-3 py-2 text-sm font-medium text-ink"
          >
            {notice}
          </div>
        )}
      </div>

      {started && (
        <p className="mt-3 text-xs text-muted">
          Hold your hands up and touch the keys with your fingertips — or click them.
        </p>
      )}
    </Card>
  );
}
