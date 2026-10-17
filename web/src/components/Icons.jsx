/* A small, consistent inline icon set (stroke style, 24x24 grid).

   Hand-rolled on purpose: no extra dependency to install, fully tree-shaken,
   and one visual language. Icons inherit `currentColor` and a `className`. */

function Svg({ children, className = "h-5 w-5", ...rest }) {
  return (
    <svg
      viewBox="0 0 24 24"
      className={className}
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
      {...rest}
    >
      {children}
    </svg>
  );
}

export const Keyboard = (p) => (
  <Svg {...p}>
    <rect x="2.5" y="5" width="19" height="14" rx="2" />
    <path d="M7 5v9M12 5v9M17 5v9" />
  </Svg>
);

export const Camera = (p) => (
  <Svg {...p}>
    <path d="M3 8.5A2.5 2.5 0 0 1 5.5 6h1.2l1-1.6h6.6l1 1.6h1.2A2.5 2.5 0 0 1 21 8.5v8A2.5 2.5 0 0 1 18.5 19h-13A2.5 2.5 0 0 1 3 16.5z" />
    <circle cx="12" cy="12.3" r="3.2" />
  </Svg>
);

export const Hand = (p) => (
  <Svg {...p}>
    <path d="M9 11V5.5a1.5 1.5 0 0 1 3 0V11" />
    <path d="M12 11V4.5a1.5 1.5 0 0 1 3 0V11" />
    <path d="M15 11V6.5a1.5 1.5 0 0 1 3 0V14a6 6 0 0 1-6 6h-1a6 6 0 0 1-6-6v-1.5a1.5 1.5 0 0 1 3 0" />
  </Svg>
);

/* a pointing hand (index finger up) - the "touch a key" gesture */
export const HandPoint = (p) => (
  <Svg {...p}>
    <path d="M11.2 12.2V5a1.6 1.6 0 0 1 3.2 0v7.2" />
    <path d="M14.4 12.1V10a1.6 1.6 0 0 1 3.2 0v2.1" />
    <path d="M17.6 12.3v-1.1a1.6 1.6 0 0 1 3.2 0v6.1a4.6 4.6 0 0 1-4.6 4.6h-2.8a4.3 4.3 0 0 1-3-1.3l-3.7-3.7a1.7 1.7 0 0 1 2.4-2.4l1.4 1.4" />
  </Svg>
);

export const Volume2 = (p) => (
  <Svg {...p}>
    <path d="M4 9.5h3l4-3.5v12l-4-3.5H4z" />
    <path d="M15.5 9a4 4 0 0 1 0 6M18 6.5a7.5 7.5 0 0 1 0 11" />
  </Svg>
);

export const VolumeX = (p) => (
  <Svg {...p}>
    <path d="M4 9.5h3l4-3.5v12l-4-3.5H4z" />
    <path d="M16 9.5l4 5M20 9.5l-4 5" />
  </Svg>
);

export const GraduationCap = (p) => (
  <Svg {...p}>
    <path d="M2.5 8.5 12 4.5l9.5 4L12 12.5z" />
    <path d="M6 10.5V15c0 1.4 2.7 2.5 6 2.5s6-1.1 6-2.5v-4.5" />
    <path d="M21.5 8.5V14" />
  </Svg>
);

export const Sliders = (p) => (
  <Svg {...p}>
    <path d="M4 7h9M17 7h3M4 12h3M11 12h9M4 17h11M19 17h1" />
    <circle cx="15" cy="7" r="2" />
    <circle cx="9" cy="12" r="2" />
    <circle cx="17" cy="17" r="2" />
  </Svg>
);

export const Music = (p) => (
  <Svg {...p}>
    <path d="M9 18V6l10-2v12" />
    <circle cx="6.5" cy="18" r="2.5" />
    <circle cx="16.5" cy="16" r="2.5" />
    <path d="M9 10l6.5-1" />
  </Svg>
);

/* The complete key signature used as the decorative hero backdrop (not a UI icon).

   Taken from "B-flat-major g-minor.svg" by Rettinghaus, via Wikimedia Commons,
   licensed CC BY 4.0 - https://commons.wikimedia.org/w/index.php?curid=1722142
   The original builds this from <symbol>/<use> pairs; they are inlined here so
   the component can appear more than once without duplicate element ids. Each
   symbol had a 1000x1000 viewBox scaled into a 720x720 box at (x,y) over an
   inner scale(1,-1), i.e. transform="translate(x y) scale(0.72 -0.72)". */
const CLEF_GLYPH =
  "M 562,-21 C 562,68 497,129 407,129 414,85 441,-74 462,-194 533,-165 562,-92 562,-21 z M 420,-206 362,123 C 303,109 258,60 258,-1 258,-50 280,-76 319,-100 331,-108 341,-113 341,-122 341,-131 332,-135 324,-135 244,-135 189,-39 189,31 189,125 251,221 342,248 335,289 328,336 319,390 304,375 288,361 271,346 183,270 97,161 97,39 97,-112 219,-212 362,-212 381,-212 400,-210 420,-206 z M 332,822 C 324,791 321,757 321,720 321,678 326,639 332,599 401,667 478,745 478,849 478,918 454,967 439,967 387,967 341,862 332,822 z M 122,-513 C 122,-447 167,-390 237,-390 312,-390 353,-447 353,-501 353,-565 306,-605 259,-612 256,-613 254,-614 254,-616 254,-617 256,-618 257,-619 259,-619 280,-624 304,-624 405,-624 458,-569 458,-465 458,-412 447,-342 428,-246 405,-250 378,-253 349,-253 163,-253 0,-106 0,81 0,281 126,402 217,487 238,504 290,557 291,558 274,670 269,719 269,773 269,857 287,985 351,1061 384,1100 415,1112 422,1112 440,1112 469,1077 493,1026 509,990 537,916 537,825 537,666 464,541 358,430 367,374 377,315 387,255 533,255 640,153 640,2 640,-101 567,-203 469,-235 475,-274 481,-304 484,-324 494,-381 500,-426 500,-465 500,-528 486,-594 432,-632 396,-654 355,-666 308,-666 173,-666 122,-579 122,-513 z";
const FLAT_GLYPH =
  "M 201,79 C 202,71 203,63 203,54 203,13 188,-36 150,-79 96,-140 31,-172 27,-174 25,-175 21,-176 19,-176 11,-176 5,-170 5,-162 L 0,439 C 0,447 6,453 14,453 H 26 C 34,453 40,447 40,439 L 36,118 C 41,124 70,155 120,155 171,155 195,118 201,79 z M 132,40 V 51 C 132,72 129,106 93,106 53,106 38,77 36,68 L 33,-127 C 52,-112 86,-85 103,-59 128,-21 132,25 132,40 z";
const STAFF_LINES = [540, 720, 900, 1080, 1260];

export const KeySignature = ({ className = "h-5 w-5", ...rest }) => (
  <svg
    viewBox="0 0 1340 1800"
    className={className}
    fill="currentColor"
    aria-hidden="true"
    {...rest}
  >
    {STAFF_LINES.map((y) => (
      <polyline
        key={y}
        points={`0,${y} 1340,${y}`}
        fill="none"
        stroke="currentColor"
        strokeWidth="20"
      />
    ))}
    <g transform="translate(80 1080) scale(0.72 -0.72)">
      <path d={CLEF_GLYPH} />
    </g>
    <g transform="translate(650 900) scale(0.72 -0.72)">
      <path d={FLAT_GLYPH} />
    </g>
    <g transform="translate(840 630) scale(0.72 -0.72)">
      <path d={FLAT_GLYPH} />
    </g>
  </svg>
);

export const Search = (p) => (
  <Svg {...p}>
    <circle cx="11" cy="11" r="6.5" />
    <path d="M16 16l4.5 4.5" />
  </Svg>
);

export const Play = (p) => (
  <Svg {...p}>
    <path d="M7 5.5v13l11-6.5z" />
  </Svg>
);

export const Square = (p) => (
  <Svg {...p}>
    <rect x="6" y="6" width="12" height="12" rx="2" />
  </Svg>
);

export const SkipForward = (p) => (
  <Svg {...p}>
    <path d="M6 6l9 6-9 6z" />
    <path d="M18 6v12" />
  </Svg>
);

export const RotateCcw = (p) => (
  <Svg {...p}>
    <path d="M4 12a8 8 0 1 0 2.3-5.6" />
    <path d="M3.5 5v4h4" />
  </Svg>
);

export const Sparkles = (p) => (
  <Svg {...p}>
    <path d="M12 4l1.6 4.4L18 10l-4.4 1.6L12 16l-1.6-4.4L6 10l4.4-1.6z" />
    <path d="M18.5 15.5l.7 1.8 1.8.7-1.8.7-.7 1.8-.7-1.8-1.8-.7 1.8-.7z" />
  </Svg>
);

export const RefreshCw = (p) => (
  <Svg {...p}>
    <path d="M20 11a8 8 0 0 0-13.7-5.3L4 8" />
    <path d="M4 4v4h4" />
    <path d="M4 13a8 8 0 0 0 13.7 5.3L20 16" />
    <path d="M20 20v-4h-4" />
  </Svg>
);

export const Target = (p) => (
  <Svg {...p}>
    <circle cx="12" cy="12" r="8" />
    <circle cx="12" cy="12" r="4" />
    <circle cx="12" cy="12" r="1" fill="currentColor" stroke="none" />
  </Svg>
);

export const Info = (p) => (
  <Svg {...p}>
    <circle cx="12" cy="12" r="8.5" />
    <path d="M12 11v5M12 8h.01" />
  </Svg>
);

export const ChevronDown = (p) => (
  <Svg {...p}>
    <path d="M6 9.5l6 6 6-6" />
  </Svg>
);
