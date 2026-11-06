import type { Metadata } from "next";

import { ContentForm } from "@/components/content-form";

export const metadata: Metadata = { title: "New content" };

export default function Page() {
  return <ContentForm />;
}
