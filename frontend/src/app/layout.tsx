import type { Metadata } from "next";
import "./globals.css";
import { Playfair_Display, JetBrains_Mono } from "next/font/google";

const geistMono = JetBrains_Mono({
  subsets: ["latin"],
  variable: "--font-mono",
  display: "swap",
});

const playfair = Playfair_Display({
  subsets: ["latin"],
  variable: "--font-display",
  display: "swap",
});

export const metadata: Metadata = {
  title: "LockedIn — Interruptible AI Agents",
  description: "Real-time agent execution you can interrupt. Version-aware, dependency-aware replanning.",
  icons: {
    icon: "data:image/svg+xml,<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 32 32'><rect width='32' height='32' rx='6' fill='%236633ff'/><text x='50%' y='50%' dominant-baseline='central' text-anchor='middle' font-size='20' fill='white'>⚡</text></svg>",
  },
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" className="dark">
      <body className={`${geistMono.variable} ${playfair.variable} font-mono antialiased bg-background text-foreground`}>
        {children}
      </body>
    </html>
  );
}