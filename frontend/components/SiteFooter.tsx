const REPO_URL = "https://github.com/SandeepKr24/GridMind";
const PORTFOLIO_URL = "https://sandeepkumar24.vercel.app/";

const LINKS = [
  { href: `${REPO_URL}/issues`, label: "Suggestions & problems" },
  { href: REPO_URL, label: "Source code on GitHub" },
] as const;

const SOURCES = [
  { href: "https://docs.fastf1.dev", label: "FastF1", note: "timing, laps and pit stops" },
  { href: "https://github.com/jolpica/jolpica-f1", label: "Jolpica F1", note: "championship standings" },
] as const;

function ExternalLink({ href, children }: { href: string; children: React.ReactNode }) {
  return (
    <a
      href={href}
      target="_blank"
      rel="noopener noreferrer"
      className="text-sm text-ink-muted no-underline transition-colors hover:text-ink"
    >
      {children}
    </a>
  );
}

/**
 * Site-wide footer: who made GridMind, where to report problems, where the
 * data comes from, and the trademark notice an unofficial F1 site needs.
 */
export function SiteFooter() {
  return (
    <footer className="relative z-[2] border-t border-line bg-surface-base">
      <div className="mx-auto grid max-w-[1400px] gap-8 px-5 py-10 md:grid-cols-[2fr_1fr_1fr]">
        <section aria-labelledby="footer-about">
          <h2 id="footer-about" className="gm-label m-0 mb-3">
            About
          </h2>
          <p className="m-0 max-w-[460px] text-sm leading-relaxed text-ink-muted text-pretty">
            GridMind is an AI race analyst for Formula 1, built by{" "}
            <a
              href={PORTFOLIO_URL}
              target="_blank"
              rel="noopener noreferrer"
              className="font-semibold text-accent-bright no-underline underline-offset-2 transition-colors hover:text-accent-soft hover:underline"
            >
              Sandeep Kumar
            </a>
            . Ask a question in plain English and it answers from real timing data,
            fetched the first time a race is needed and stored after that.
          </p>
        </section>

        <nav aria-labelledby="footer-feedback">
          <h2 id="footer-feedback" className="gm-label m-0 mb-3">
            Feedback
          </h2>
          <ul className="m-0 flex list-none flex-col gap-2 p-0">
            {LINKS.map((link) => (
              <li key={link.href}>
                <ExternalLink href={link.href}>{link.label}</ExternalLink>
              </li>
            ))}
          </ul>
        </nav>

        <section aria-labelledby="footer-data">
          <h2 id="footer-data" className="gm-label m-0 mb-3">
            Data
          </h2>
          <ul className="m-0 flex list-none flex-col gap-2 p-0">
            {SOURCES.map((source) => (
              <li key={source.href} className="text-sm text-ink-ghost">
                <ExternalLink href={source.href}>{source.label}</ExternalLink>
                <span>: {source.note}</span>
              </li>
            ))}
          </ul>
        </section>
      </div>

      <div className="border-t border-line-subtle">
        <div className="mx-auto flex max-w-[1400px] flex-col gap-3 px-5 py-6 text-xs leading-relaxed text-ink-ghost">
          <p className="m-0 max-w-[900px] text-pretty">
            GridMind is an unofficial project and is not associated in any way with the
            Formula 1 companies. F1, FORMULA ONE, FORMULA 1, FIA FORMULA ONE WORLD
            CHAMPIONSHIP, GRAND PRIX and related marks are trademarks of Formula One
            Licensing B.V. Team names and logos belong to their respective owners.
          </p>
          <p className="m-0 max-w-[900px] text-pretty">
            Answers and reports are written by an AI model from stored timing data. Check
            anything important against an official source.
          </p>
          {/* Pages are prerendered, so the build year can differ from the viewer's. */}
          <p className="m-0" suppressHydrationWarning>
            © {new Date().getFullYear()} GridMind
          </p>
        </div>
      </div>
    </footer>
  );
}
