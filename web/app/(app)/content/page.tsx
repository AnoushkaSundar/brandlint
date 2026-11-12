import type { Metadata } from "next";

import { ContentList } from "@/components/content-list";
import { OnboardingChecklist } from "@/components/onboarding-checklist";

export const metadata: Metadata = { title: "Content" };

export default function Page() {
  return (
    <>
      <OnboardingChecklist />
      <ContentList />
    </>
  );
}
