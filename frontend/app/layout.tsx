import "./globals.css";

export const metadata = {
  title: "News × Prediction Markets",
  description: "Breaking news and posts, linked to the Kalshi markets they bear on.",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body className="min-h-screen bg-bg text-text antialiased">{children}</body>
    </html>
  );
}
