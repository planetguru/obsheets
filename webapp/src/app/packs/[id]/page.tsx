import Link from "next/link";
import { notFound, redirect } from "next/navigation";
import { getUser } from "@/lib/user";
import { getPack } from "@/lib/db";
import PackActions from "./actions";

export const dynamic = "force-dynamic";

export default async function PackView({ params }: { params: Promise<{ id: string }> }) {
  const user = await getUser();
  if (!user) redirect("/signin");

  const { id } = await params;
  const pack = getPack(id);
  if (!pack) notFound();

  return (
    <main>
      <h1>{pack.title}</h1>
      <p className="lede">
        Session {pack.sessionNumber} · {pack.sessionLabel} ·{" "}
        {pack.course === "long" ? `Long course (${pack.poolLengthM}m)` : `Short course (${pack.poolLengthM}m)`}
      </p>

      <div className="banner ok">
        Entry count check passed ✓ — {pack.entryCount} entries across {pack.eventCount}{" "}
        events are on this sheet.
      </div>
      {pack.discrepancies.length > 0 ? (
        <div className="banner warn">
          Attendance discrepancies (the sheet is unchanged — for your judgement):
          <ul className="notes">
            {pack.discrepancies.map((d, i) => (
              <li key={i}>{d}</li>
            ))}
          </ul>
        </div>
      ) : null}

      <PackActions id={pack.id} />

      <p className="kv" style={{ margin: "6px 0 14px" }}>
        Created by <b>{pack.creatorName}</b> ({pack.creatorEmail}) on{" "}
        <b>{new Date(pack.createdAt).toLocaleString("en-GB")}</b>
      </p>

      <iframe className="packframe" id="packframe" src={`/api/packs/${pack.id}/html`} title={pack.title} />

      <p style={{ marginTop: 16 }}>
        <Link className="btn subtle" href="/">
          ← Back to all packs
        </Link>
      </p>
    </main>
  );
}
