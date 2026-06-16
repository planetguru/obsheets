import { auth } from "@/auth";

export interface AppUser {
  name: string;
  email: string;
}

export function allowedEmails(): string[] {
  return (process.env.ALLOWED_EMAILS ?? "")
    .split(",")
    .map((e) => e.trim().toLowerCase())
    .filter(Boolean);
}

export function isAllowed(email: string | null | undefined): boolean {
  if (!email) return false;
  return allowedEmails().includes(email.trim().toLowerCase());
}

// All pages and API routes resolve the signed-in user through this helper.
// In dev-bypass mode (AUTH_DEV_BYPASS=1) it returns a fixed local user so the
// app is fully testable before Google OAuth is configured.
export async function getUser(): Promise<AppUser | null> {
  if (process.env.AUTH_DEV_BYPASS === "1") {
    return {
      name: process.env.DEV_USER_NAME || "Dev Coach",
      email: process.env.DEV_USER_EMAIL || "dev@local",
    };
  }
  const session = await auth();
  const u = session?.user;
  if (!u?.email || !isAllowed(u.email)) return null;
  return { name: u.name ?? u.email, email: u.email };
}
