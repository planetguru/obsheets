import Link from "next/link";
import { redirect } from "next/navigation";
import { getUser } from "@/lib/user";
import { listPacks } from "@/lib/db";

export const dynamic = "force-dynamic";

export default async function Dashboard() {
  const user = await getUser();
  if (!user) redirect("/signin");

  const packs = listPacks();
  return (
    <main>
      <h1>Observation packs</h1>
      <p className="lede">
        Turn a gala&rsquo;s paperwork into a printable poolside recording sheet.
      </p>
      <Link className="btn big" href="/packs/new">
        + Create new observation pack
      </Link>

      <div className="card">
        <h2>Previous packs</h2>
        {packs.length === 0 ? (
          <p className="kv">No packs yet — create the first one above.</p>
        ) : (
          <table className="packs">
            <thead>
              <tr>
                <th>Pack</th>
                <th>Session</th>
                <th>Created by</th>
                <th>Date</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              {packs.map((p) => (
                <tr key={p.id}>
                  <td className="title">{p.title}</td>
                  <td>
                    Session {p.sessionNumber} · {p.entryCount} entries
                  </td>
                  <td>{p.creatorName}</td>
                  <td>{new Date(p.createdAt).toLocaleDateString("en-GB")}</td>
                  <td>
                    <Link className="btn alt" href={`/packs/${p.id}`} style={{ padding: "7px 14px", fontSize: 13 }}>
                      View
                    </Link>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </main>
  );
}
