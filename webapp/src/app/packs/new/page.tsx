import { redirect } from "next/navigation";
import { getUser } from "@/lib/user";
import Wizard from "./wizard";

export default async function NewPack() {
  const user = await getUser();
  if (!user) redirect("/signin");
  return <Wizard />;
}
