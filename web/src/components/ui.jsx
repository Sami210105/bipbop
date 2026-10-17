/* Shared design-system primitives.

   Every card, button, badge, sticker and label in the app comes from here so the
   retro-editorial look (thick ink outlines, cream surfaces, pastel accents,
   restrained print shadows) stays consistent and is easy to retune in one place.
   Colours resolve to the tokens declared in index.css. */

const TONES = {
  card: "bg-card text-ink",
  cream: "bg-cream text-ink",
  mist: "bg-mist text-ink",
  coral: "bg-coral text-ink",
  cobalt: "bg-cobalt text-card",
  cobaltSoft: "bg-cobalt-soft text-card",
  mint: "bg-mint text-ink",
  lavender: "bg-lavender text-ink",
  bright: "bg-bright text-ink",
  ink: "bg-ink text-card",
};

export function Card({ accent = "card", className = "", children, ...rest }) {
  return (
    <div className={`rounded-2xl ink-border ${TONES[accent] || TONES.card} ${className}`} {...rest}>
      {children}
    </div>
  );
}

export function SectionLabel({ children, className = "" }) {
  return <div className={`label ${className}`}>{children}</div>;
}

/* sticker-like floating labels; use sparingly, occasional rotation */
export function Sticker({ tone = "bright", rotate = 0, className = "", children }) {
  return (
    <span
      className={`sticker ${TONES[tone] || TONES.bright} ${className}`}
      style={rotate ? { transform: `rotate(${rotate}deg)` } : undefined}
    >
      {children}
    </span>
  );
}

export function Badge({ tone = "mint", className = "", children }) {
  return (
    <span
      className={`inline-flex items-center rounded-full px-2 py-0.5 text-[11px] font-semibold uppercase tracking-wide ink-border-thin ${
        TONES[tone] || TONES.mint
      } ${className}`}
    >
      {children}
    </span>
  );
}

const VARIANTS = {
  primary: "bg-coral text-ink",
  bright: "bg-bright text-ink",
  cobalt: "bg-cobalt text-card",
  outline: "bg-card text-ink",
  ghost: "bg-transparent text-ink",
  ink: "bg-ink text-card",
};

const SIZES = {
  sm: "px-3 py-1.5 text-xs",
  md: "px-4 py-2 text-sm",
  lg: "px-5 py-2.5 text-sm",
};

export function Button({ variant = "primary", size = "md", icon, className = "", children, ...rest }) {
  const Tag = rest.href ? "a" : "button";
  return (
    <Tag
      className={`lift inline-flex items-center justify-center gap-2 rounded-full font-semibold ${
        SIZES[size] || SIZES.md
      } ${VARIANTS[variant] || VARIANTS.primary} ${
        variant === "ghost" ? "" : "ink-border"
      } disabled:cursor-not-allowed disabled:opacity-50 ${className}`}
      {...rest}
    >
      {icon}
      {children}
    </Tag>
  );
}

/* a compact key/value chip used for telemetry and facts */
export function Stat({ label, value, tone = "cream", className = "" }) {
  return (
    <div className={`rounded-xl ${TONES[tone] || TONES.cream} ink-border-thin px-2.5 py-1.5 ${className}`}>
      <div className="text-[10px] font-semibold uppercase tracking-wider text-muted">{label}</div>
      <div className="font-display text-sm font-bold leading-tight text-ink">{value}</div>
    </div>
  );
}
