import type { Metadata } from "next";
import { IBM_Plex_Sans, Source_Serif_4 } from "next/font/google";
import type { ReactNode } from "react";
import { SiteFooter } from "../components/site-footer";
import { SiteHeader } from "../components/site-header";
import "./globals.css";

// next/font downloads the fonts at build time and serves them from this site.
const sans = IBM_Plex_Sans({
  subsets: ["latin"],
  weight: ["400", "500", "600"],
  variable: "--font-sans",
});
const serif = Source_Serif_4({
  subsets: ["latin"],
  weight: ["500", "600"],
  variable: "--font-serif",
});

export const metadata: Metadata = {
  title: "Out of Frame",
  description: "Check what a Berlin property listing leaves out.",
};

// Every page fills one screen like an app: the header and footer stay in
// place and only the page content between them scrolls.
export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="en" className={`${sans.variable} ${serif.variable}`}>
      <body>
        <div className="app-shell">
          <SiteHeader />
          <div className="app-content">{children}</div>
          <SiteFooter />
        </div>
      </body>
    </html>
  );
}
