import Link from "next/link";

export function SiteFooter() {
  return (
    <footer className="site-footer">
      <nav aria-label="Legal and contact">
        <Link href="/terms">Service terms</Link>
        <Link href="/privacy">Privacy notice</Link>
        <Link href="/impressum">Impressum</Link>
        <Link href="/impressum#contact">Contact</Link>
      </nav>
    </footer>
  );
}
