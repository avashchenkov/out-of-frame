import Link from "next/link";

export function SiteHeader() {
  return (
    <header className="site-header">
      <Link href="/" className="brand" aria-label="Out of Frame home">
        <span className="brand-mark" aria-hidden="true" />
        Out of Frame
      </Link>
      <nav className="site-nav" aria-label="Main navigation">
        <Link href="/">Private chat</Link>
        <Link href="/examples">Examples</Link>
        <span className="coverage">Berlin</span>
      </nav>
    </header>
  );
}
