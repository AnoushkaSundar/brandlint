"use client";

import { useAuth } from "@/components/auth-provider";
import { DemoSwitcher } from "@/components/demo-switcher";
import { DemoTour } from "@/components/demo-tour";
import { DEMO_MODE } from "@/lib/demo";

// The guided tour and role switcher belong to the Tarnhollow demo. They never show in a
// workspace someone created, where the switcher's demo accounts mean nothing.
export function DemoTools() {
  const { workspace } = useAuth();
  if (!DEMO_MODE || workspace?.kind !== "demo") return null;

  return (
    <>
      <DemoTour />
      <DemoSwitcher />
    </>
  );
}
