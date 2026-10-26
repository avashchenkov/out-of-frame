import Link from "next/link";

export function SiteHeader() {
  return (
    <header className="site-header">
      <Link href="/" className="brand" aria-label="Out of Frame home">
        <svg
          className="brand-mark"
          viewBox="0 0 24 24"
          aria-hidden="true"
          focusable="false"
        >
          <rect x="2.5" y="5.5" width="13" height="13" rx="1" />
          <circle cx="20" cy="5" r="2.25" />
        </svg>
        Out of Frame
      </Link>
      <nav className="site-nav" aria-label="Main navigation">
        <Link href="/examples">Examples</Link>
      </nav>
    </header>
  );
}
