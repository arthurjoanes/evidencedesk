import { connection } from "next/server";
import type { Metadata } from "next";
import localFont from "next/font/local";
import { Providers } from "@/lib/session";
import "./globals.css";

const sans = localFont({
  src: [
    { path: "../../public/fonts/IBMPlexSans-Regular.woff2", weight: "400" },
    { path: "../../public/fonts/IBMPlexSans-Medium.woff2", weight: "500" },
    { path: "../../public/fonts/IBMPlexSans-SemiBold.woff2", weight: "600" },
  ],
  variable: "--font-plex-sans",
  display: "swap",
});
const mono = localFont({
  src: "../../public/fonts/IBMPlexMono-Regular.woff2",
  variable: "--font-plex-mono",
  display: "swap",
  preload: false,
});
export const metadata: Metadata = {
  title: {
    default: "EvidenceDesk — investigação de incidentes",
    template: "%s · EvidenceDesk",
  },
  description:
    "Bancada de investigação de pedidos com fontes verificáveis e revisão humana.",
  robots: { index: false, follow: false },
};
export default async function RootLayout({
  children,
}: Readonly<{ children: React.ReactNode }>) {
  await connection();
  return (
    <html lang="pt-BR" className={sans.variable + " " + mono.variable}>
      <body>
        <Providers>{children}</Providers>
      </body>
    </html>
  );
}
