// The logo: a frame with a dot outside it.
// A static copy for the README is in docs/assets/logo.svg; change both together.
export function BrandMark() {
  return (
    <svg
      className="brand-mark"
      viewBox="0 0 24 24"
      aria-hidden="true"
      focusable="false"
    >
      <rect x="2.5" y="5.5" width="13" height="13" rx="1" />
      <g className="brand-dot">
        <circle cx="20" cy="5" r="2.25" />
      </g>
    </svg>
  );
}
