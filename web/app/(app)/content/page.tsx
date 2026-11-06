import type { Metadata } from "next";

import { ContentList } from "@/components/content-list";

export const metadata: Metadata = { title: "Content" };

export default function Page() {
  return <ContentList />;
}
