/**
 * Hand-drawn cartoon octopus chef logo. 8 tentacles, each holding a kitchen tool:
 * whisk, knife, spatula, rolling pin, wooden spoon, frying pan, pot, and ladle.
 *
 * If you want a polished version, drop a PNG/SVG into web/public/ and import it
 * instead — this file exists so the brand mark isn't blocked on design work.
 */
export function Logo({ size = 80 }: { size?: number }) {
  return (
    <svg
      viewBox="0 0 240 240"
      width={size}
      height={size}
      xmlns="http://www.w3.org/2000/svg"
      aria-label="Octocook"
      role="img"
    >
      {/* --- Chef's hat --- */}
      <g fill="#ffffff" stroke="#2a1a4a" strokeWidth="2.2" strokeLinejoin="round">
        <ellipse cx="120" cy="40" rx="34" ry="24" />
        <ellipse cx="92" cy="48" rx="22" ry="20" />
        <ellipse cx="148" cy="48" rx="22" ry="20" />
        <rect x="84" y="62" width="72" height="14" rx="3" />
      </g>
      <line x1="100" y1="32" x2="105" y2="44" stroke="#cbb8e8" strokeWidth="1.4" strokeLinecap="round" />
      <line x1="135" y1="34" x2="140" y2="46" stroke="#cbb8e8" strokeWidth="1.4" strokeLinecap="round" />

      {/* --- Tentacles (drawn behind the head) ---
          Each tentacle is a thick purple stroke curving from the head bottom out
          to a tool position around the perimeter. */}
      <g fill="none" stroke="#8b5cf6" strokeWidth="9" strokeLinecap="round">
        <path d="M82 118 Q40 120 22 158 Q14 178 26 196" />     {/* far left, whisk    */}
        <path d="M90 130 Q55 152 44 188 Q40 208 56 218" />     {/* lower-left, knife  */}
        <path d="M104 138 Q92 178 78 208 Q76 224 92 224" />    {/* near-left, spatula */}
        <path d="M115 142 Q116 178 118 214 Q120 232 130 226" />{/* center-left, pin   */}
        <path d="M125 142 Q124 178 124 214 Q124 232 142 224" />{/* center-right, spoon*/}
        <path d="M136 138 Q150 178 162 208 Q166 224 150 224" />{/* near-right, pan    */}
        <path d="M150 130 Q188 154 198 188 Q200 208 184 218" />{/* lower-right, pot   */}
        <path d="M158 118 Q200 122 218 158 Q226 178 214 196" />{/* far right, ladle   */}
      </g>

      {/* --- Tentacle suckers (a few small accents) --- */}
      <g fill="#a78bfa">
        <circle cx="35" cy="180" r="3" />
        <circle cx="55" cy="200" r="2.5" />
        <circle cx="195" cy="200" r="2.5" />
        <circle cx="205" cy="180" r="3" />
        <circle cx="85" cy="210" r="2.5" />
        <circle cx="155" cy="210" r="2.5" />
      </g>

      {/* --- Head --- */}
      <ellipse cx="120" cy="108" rx="55" ry="46" fill="#8b5cf6" stroke="#5b21b6" strokeWidth="2.4" />
      {/* highlight */}
      <ellipse cx="98" cy="92" rx="11" ry="6" fill="#c4b5fd" opacity="0.55" />

      {/* Eyes */}
      <g>
        <circle cx="103" cy="103" r="6.5" fill="#ffffff" />
        <circle cx="137" cy="103" r="6.5" fill="#ffffff" />
        <circle cx="104" cy="104" r="3.4" fill="#1a1a1a" />
        <circle cx="138" cy="104" r="3.4" fill="#1a1a1a" />
        <circle cx="105.5" cy="102" r="1.2" fill="#ffffff" />
        <circle cx="139.5" cy="102" r="1.2" fill="#ffffff" />
      </g>

      {/* Cheeks */}
      <circle cx="92" cy="120" r="5" fill="#f9a8d4" opacity="0.7" />
      <circle cx="148" cy="120" r="5" fill="#f9a8d4" opacity="0.7" />

      {/* Smile */}
      <path d="M108 124 Q120 134 132 124" fill="none" stroke="#1a1a1a" strokeWidth="2.5" strokeLinecap="round" />

      {/* ---------- Tools at tentacle tips ---------- */}

      {/* Whisk (far left, tip at ~26,196) */}
      <g transform="translate(26 196)" stroke="#3f2570" strokeWidth="1.5" fill="#e9e5f4" strokeLinecap="round">
        <line x1="0" y1="0" x2="-3" y2="10" strokeWidth="2.2" />
        <ellipse cx="-6" cy="-6" rx="6" ry="9" transform="rotate(-30 -6 -6)" fill="none" />
        <line x1="-12" y1="-12" x2="0" y2="0" />
        <line x1="-6" y1="-15" x2="0" y2="0" />
        <line x1="0" y1="-12" x2="0" y2="0" />
      </g>

      {/* Knife (lower-left, tip ~56,218) */}
      <g transform="translate(56 218) rotate(-20)" stroke="#3f2570" strokeWidth="1.4" strokeLinejoin="round">
        <rect x="-3" y="-2" width="12" height="5" rx="1" fill="#5b21b6" />
        <path d="M9 -3 L26 -1 L26 4 L9 4 Z" fill="#e9e5f4" />
      </g>

      {/* Spatula (near-left, tip ~92,224) */}
      <g transform="translate(92 224) rotate(0)" stroke="#3f2570" strokeWidth="1.4" strokeLinejoin="round">
        <rect x="-1.5" y="-2" width="14" height="4" rx="1" fill="#5b21b6" />
        <rect x="11" y="-7" width="14" height="14" rx="2" fill="#e9e5f4" />
      </g>

      {/* Rolling pin (center-left, tip ~130,226) */}
      <g transform="translate(130 226)" stroke="#3f2570" strokeWidth="1.4" strokeLinejoin="round">
        <rect x="-12" y="-3" width="24" height="7" rx="3.5" fill="#e9e5f4" />
        <rect x="-18" y="-1.5" width="6" height="4" rx="1" fill="#5b21b6" />
        <rect x="12" y="-1.5" width="6" height="4" rx="1" fill="#5b21b6" />
      </g>

      {/* Wooden spoon (center-right, tip ~142,224) */}
      <g transform="translate(142 224) rotate(15)" stroke="#3f2570" strokeWidth="1.4" strokeLinejoin="round">
        <rect x="-1.5" y="-2" width="16" height="4" rx="1.5" fill="#b07b3a" />
        <ellipse cx="18" cy="0" rx="6" ry="4.5" fill="#d4a36e" />
      </g>

      {/* Frying pan (near-right, tip ~150,224) */}
      <g transform="translate(150 224) rotate(20)" stroke="#3f2570" strokeWidth="1.4" strokeLinejoin="round">
        <path d="M0 0 L-14 -1 L-14 4 L0 4 Z" fill="#5b21b6" />
        <ellipse cx="-22" cy="1.5" rx="9" ry="6" fill="#2a1a4a" />
        <ellipse cx="-22" cy="-1" rx="9" ry="5" fill="#5b3aa0" />
      </g>

      {/* Pot (lower-right, tip ~184,218) */}
      <g transform="translate(184 218) rotate(-10)" stroke="#3f2570" strokeWidth="1.4" strokeLinejoin="round">
        <rect x="-2" y="-9" width="16" height="11" rx="1.5" fill="#e9e5f4" />
        <line x1="-2" y1="-9" x2="-5" y2="-8" />
        <line x1="14" y1="-9" x2="17" y2="-8" />
        <ellipse cx="6" cy="-10" rx="9" ry="2" fill="#cbb8e8" />
      </g>

      {/* Ladle (far right, tip ~214,196) */}
      <g transform="translate(214 196) rotate(20)" stroke="#3f2570" strokeWidth="1.4" strokeLinejoin="round">
        <line x1="0" y1="0" x2="-2" y2="-14" strokeWidth="2.2" />
        <ellipse cx="-3" cy="-18" rx="7" ry="5.5" fill="#e9e5f4" />
      </g>
    </svg>
  )
}
