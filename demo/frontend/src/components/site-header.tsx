import Link from "next/link";
import { BrandMark } from "./brand-mark";

export function SiteHeader() {
  return (
    <header className="site-header">
      <Link href="/" className="brand" aria-label="Out of Frame home">
        <BrandMark />
        Out of Frame
      </Link>
      <nav className="site-nav" aria-label="Main navigation">
        <Link href="/examples">Examples</Link>
      </nav>
    </header>
  );
}
