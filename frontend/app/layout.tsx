import "./globals.css";

/**
 * Where relative metadata URLs resolve against.
 *
 * Without a `metadataBase`, Next drops relative Open Graph URLs (the
 * canonical `/posts/{id}` a shared story unfurls with) and warns at build
 * time. `NEXT_PUBLIC_SITE_URL` is the explicit answer; Vercel's own
 * production domain is the fallback so a deploy is correct without anyone
 * having to remember to set it; localhost is the last resort for `next dev`.
 */
const siteUrl =
  process.env.NEXT_PUBLIC_SITE_URL ||
  (process.env.VERCEL_PROJECT_PRODUCTION_URL
    ? `https://${process.env.VERCEL_PROJECT_PRODUCTION_URL}`
    : "http://localhost:3000");

// No product name, per the design constraint: this is a description of what
// the site does, and each post overrides it with its own title in
// app/posts/[id]/page.tsx.
export const metadata = {
  metadataBase: new URL(siteUrl),
  title: "News × Prediction Markets",
  description: "Breaking news and posts, linked to the Kalshi markets they bear on.",
};

export default function RootLayout({
  children, modal,
}: { children: React.ReactNode; modal: React.ReactNode }) {
  return (
    <html lang="en">
      <body className="min-h-screen bg-bg text-text antialiased">
        {children}
        {modal}
      </body>
    </html>
  );
}
