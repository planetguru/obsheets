import Link from "next/link";
import { redirect } from "next/navigation";
import { signIn } from "@/auth";
import { getUser } from "@/lib/user";

export default async function SignIn({
  searchParams,
}: {
  searchParams: Promise<{ error?: string }>;
}) {
  const user = await getUser();
  if (user) redirect("/");
  const { error } = await searchParams;
  const devMode = process.env.AUTH_DEV_BYPASS === "1";

  return (
    <main>
      <div className="card" style={{ maxWidth: 460, margin: "60px auto", textAlign: "center" }}>
        <h1 style={{ marginTop: 4 }}>Sign in</h1>
        <p className="lede">Coach recording sheets for Bridgwater ASC.</p>
        {error === "AccessDenied" ? (
          <div className="banner err">
            You&rsquo;re not authorised to use this tool. Ask the team admin to add your
            email to the allowlist.
          </div>
        ) : null}
        {devMode ? (
          <Link className="btn big" href="/">
            Continue (development mode)
          </Link>
        ) : (
          <form
            action={async () => {
              "use server";
              await signIn("google", { redirectTo: "/" });
            }}
          >
            <button className="btn big" type="submit">
              Sign in with Google
            </button>
          </form>
        )}
      </div>
    </main>
  );
}
