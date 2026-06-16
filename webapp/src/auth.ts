import NextAuth from "next-auth";
import Google from "next-auth/providers/google";
import { isAllowed } from "@/lib/user";

export const { handlers, auth, signIn, signOut } = NextAuth({
  trustHost: true,
  providers: [Google],
  callbacks: {
    // Allowlist gate: anyone not on the list is rejected at sign-in.
    signIn({ user }) {
      return isAllowed(user.email);
    },
  },
  pages: {
    signIn: "/signin",
    error: "/signin",
  },
});
