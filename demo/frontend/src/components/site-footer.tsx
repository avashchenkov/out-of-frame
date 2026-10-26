import Link from "next/link";

export function SiteFooter() {
  return (
    <footer className="site-footer">
      <p>Out of Frame · a public demo for Berlin</p>
      <nav aria-label="Legal and contact">
        <Link href="/terms">Service terms</Link>
        <Link href="/privacy">Privacy notice</Link>
        <Link href="/impressum">Impressum</Link>
        <Link href="/impressum#contact">Contact</Link>
      </nav>
    </footer>
  );
}
