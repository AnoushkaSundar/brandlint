import type { Metadata } from "next";

import { ContentDetail } from "@/components/content-detail";

export const metadata: Metadata = { title: "Content" };

export default async function Page({ params }: PageProps<"/content/[id]">) {
  const { id } = await params;
  return <ContentDetail id={id} />;
}
