import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "Migration Agent",
  description: "Express.js to FastAPI migration workflow agent",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
