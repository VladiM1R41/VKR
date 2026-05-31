type NewscopeLogoProps = {
  className?: string
  title?: string
}

export function NewscopeLogo({ className = '', title = 'Newscope' }: NewscopeLogoProps) {
  return (
    <svg
      className={className}
      width="640"
      height="640"
      viewBox="0 0 640 640"
      fill="none"
      xmlns="http://www.w3.org/2000/svg"
      role="img"
      aria-label={title}
    >
      <defs>
        <radialGradient
          id="newscope-planet-gradient"
          cx="0"
          cy="0"
          r="1"
          gradientUnits="userSpaceOnUse"
          gradientTransform="translate(266 242) rotate(52) scale(236)"
        >
          <stop stopColor="#EAF4FF" />
          <stop offset="0.38" stopColor="#78B7FF" />
          <stop offset="0.78" stopColor="#2563EB" />
          <stop offset="1" stopColor="#123C98" />
        </radialGradient>
        <linearGradient id="newscope-ring-gradient" x1="95" y1="450" x2="550" y2="190" gradientUnits="userSpaceOnUse">
          <stop stopColor="#D7ECFF" stopOpacity="0.1" />
          <stop offset="0.18" stopColor="#D7ECFF" stopOpacity="0.86" />
          <stop offset="0.56" stopColor="#60A5FA" />
          <stop offset="0.86" stopColor="#1D4ED8" />
          <stop offset="1" stopColor="#A7D8FF" stopOpacity="0.22" />
        </linearGradient>
        <linearGradient id="newscope-scope-gradient" x1="370" y1="198" x2="520" y2="348" gradientUnits="userSpaceOnUse">
          <stop stopColor="#FFFFFF" />
          <stop offset="0.42" stopColor="#93C5FD" />
          <stop offset="1" stopColor="#2563EB" />
        </linearGradient>
        <filter
          id="newscope-soft-shadow"
          x="67"
          y="82"
          width="506"
          height="478"
          filterUnits="userSpaceOnUse"
          colorInterpolationFilters="sRGB"
        >
          <feDropShadow dx="0" dy="28" stdDeviation="30" floodColor="#0F2E73" floodOpacity="0.3" />
        </filter>
      </defs>

      <g filter="url(#newscope-soft-shadow)">
        <ellipse
          cx="320"
          cy="320"
          rx="242"
          ry="73"
          transform="rotate(-24 320 320)"
          stroke="url(#newscope-ring-gradient)"
          strokeWidth="34"
          strokeLinecap="round"
        />
        <ellipse cx="320" cy="320" rx="194" ry="194" fill="url(#newscope-planet-gradient)" />
        <path
          d="M159 373C212 321 257 287 322 254C378 226 435 210 498 207"
          stroke="#F8FBFF"
          strokeOpacity="0.28"
          strokeWidth="24"
          strokeLinecap="round"
        />
        <path
          d="M151 381C224 333 279 301 344 276C397 255 446 245 500 248"
          stroke="#061A3A"
          strokeOpacity="0.28"
          strokeWidth="28"
          strokeLinecap="round"
        />
        <ellipse
          cx="320"
          cy="320"
          rx="242"
          ry="73"
          transform="rotate(-24 320 320)"
          stroke="#BFE0FF"
          strokeOpacity="0.4"
          strokeWidth="4"
        />
      </g>

      <g transform="translate(402 192)">
        <circle cx="70" cy="70" r="58" stroke="url(#newscope-scope-gradient)" strokeWidth="12" />
        <circle cx="70" cy="70" r="8" fill="#EAF4FF" />
        <path d="M70 6V34" stroke="#EAF4FF" strokeWidth="9" strokeLinecap="round" />
        <path d="M70 106V134" stroke="#EAF4FF" strokeWidth="9" strokeLinecap="round" />
        <path d="M6 70H34" stroke="#EAF4FF" strokeWidth="9" strokeLinecap="round" />
        <path d="M106 70H134" stroke="#EAF4FF" strokeWidth="9" strokeLinecap="round" />
      </g>

      <path
        d="M118 444C204 498 331 523 438 474"
        stroke="#93C5FD"
        strokeOpacity="0.52"
        strokeWidth="8"
        strokeLinecap="round"
        strokeDasharray="1 22"
      />
      <path d="M504 454L535 424L527 468L504 454Z" fill="#EAF4FF" />
    </svg>
  )
}
