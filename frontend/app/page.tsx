import { redirect } from "next/navigation";

// dsh is now the sole conversation runtime; the legacy evidence workbench
// stays available at /workbench.
export default function HomePage() {
  redirect("/chat");
}
