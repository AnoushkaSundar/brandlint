import type { Metadata } from "next";

import { CIRunScreen } from "@/components/ci-run-screen";

export const metadata: Metadata = { title: "CI run" };

export default async function Page({ params }: PageProps<"/ci/runs/[id]">) {
  const { id } = await params;
  return <CIRunScreen id={id} />;
}
