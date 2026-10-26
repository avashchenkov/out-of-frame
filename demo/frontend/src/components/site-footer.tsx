import Link from "next/link";

export function SiteFooter() {
  return (
    <footer className="site-footer">
      <p>Out of Frame · a public demo for Berlin</p>
      {/* The Impressum holds the contact email, so it needs no own link. */}
      <nav aria-label="Legal">
        <Link href="/terms">Service terms</Link>
        <Link href="/privacy">Privacy notice</Link>
        <Link href="/impressum">Impressum</Link>
      </nav>
    </footer>
  );
}
