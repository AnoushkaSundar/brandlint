import type { Metadata } from "next";

import { ReviewScreen } from "@/components/review-screen";

export const metadata: Metadata = { title: "Review" };

export default async function Page({
  params,
}: PageProps<"/content/[id]/review">) {
  const { id } = await params;
  return <ReviewScreen id={id} />;
}
