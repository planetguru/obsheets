import { NextResponse } from "next/server";
import { getUser } from "@/lib/user";
import { getPack } from "@/lib/db";

export async function GET(req: Request, { params }: { params: Promise<{ id: string }> }) {
  const user = await getUser();
  if (!user) return new NextResponse("Not signed in", { status: 401 });

  const { id } = await params;
  const pack = getPack(id);
  if (!pack) return new NextResponse("Not found", { status: 404 });

  const url = new URL(req.url);
  const download = url.searchParams.get("download") === "1";
  const slug = pack.title.replace(/[^A-Za-z0-9]+/g, "_").replace(/^_|_$/g, "") || "pack";
  return new NextResponse(pack.generatedHtml, {
    headers: {
      "Content-Type": "text/html; charset=utf-8",
      "Content-Disposition": `${download ? "attachment" : "inline"}; filename="${slug}.html"`,
    },
  });
}
