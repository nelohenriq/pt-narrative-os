import type { Metadata } from "next";
import "./globals.css";
import Nav from "@/components/Nav";

export const metadata: Metadata = {
  title: "Portugal Narrative OS",
  description: "Portugal-first media narrative intelligence platform",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="pt">
      <body className="bg-stone-50 text-stone-900 min-h-screen antialiased">
        <Nav />
        <main className="max-w-6xl mx-auto px-4 py-8">{children}</main>
        <footer className="border-t border-stone-200 py-6 text-center text-xs text-stone-400">
          Portugal Narrative OS — Evidence-first media comparison. Not a bias-rating app.
        </footer>
      </body>
    </html>
  );
}