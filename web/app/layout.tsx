import type { Metadata } from "next";
import { Geist, Geist_Mono } from "next/font/google";
import "./globals.css";

const geistSans = Geist({
  variable: "--font-geist-sans",
  subsets: ["latin"],
});

const geistMono = Geist_Mono({
  variable: "--font-geist-mono",
  subsets: ["latin"],
});

export const metadata: Metadata = {
  title: { default: "BrandLint", template: "%s · BrandLint" },
  description:
    "Pre-publication brand governance: every draft is reviewed against an approved rulebook, and people make every decision.",
};

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    // Browser extensions such as Grammarly add attributes to these two tags before
    // React loads. This ignores attribute differences on them only, not their children.
    <html
      lang="en"
      className={`${geistSans.variable} ${geistMono.variable} h-full antialiased`}
      suppressHydrationWarning
    >
      <body className="min-h-full flex flex-col" suppressHydrationWarning>
        {children}
      </body>
    </html>
  );
}
