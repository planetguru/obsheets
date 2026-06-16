import type { Metadata } from "next";
import Link from "next/link";
import { getUser } from "@/lib/user";
import "./globals.css";

export const metadata: Metadata = {
  title: "Observation Packs — Bridgwater ASC",
  description: "Coach recording sheets from gala paperwork",
};

export default async function RootLayout({ children }: { children: React.ReactNode }) {
  const user = await getUser();
  const devMode = process.env.AUTH_DEV_BYPASS === "1";
  return (
    <html lang="en">
      <body>
        <div className="wrap">
          <div className="topbar">
            <Link className="brand" href="/">
              Observation<span>Packs</span>
            </Link>
            <div className="who">
              {user ? (
                <>
                  {user.name}
                  {devMode ? " · dev mode" : ""}
                </>
              ) : null}
            </div>
          </div>
          {children}
        </div>
      </body>
    </html>
  );
}
