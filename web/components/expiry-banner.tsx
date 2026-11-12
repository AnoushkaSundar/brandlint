"use client";

import { useState } from "react";

import { useAuth } from "@/components/auth-provider";

const DAY_MS = 24 * 60 * 60 * 1000;

// A sandbox stops working at a set time. Say so, so nobody loses work by surprise.
export function ExpiryBanner() {
  const { workspace } = useAuth();
  // Read once per page, so the sentence doesn't change under someone reading it.
  const [now] = useState(() => Date.now());
  if (!workspace || workspace.kind !== "sandbox" || !workspace.expires_at) {
    return null;
  }
  const expires = new Date(workspace.expires_at);
  const daysLeft = Math.max(0, Math.ceil((expires.getTime() - now) / DAY_MS));

  return (
    <p role="status" className="border-b bg-muted px-4 py-2 text-center text-sm">
      This is a sandbox workspace. It expires on{" "}
      <strong>{expires.toLocaleDateString()}</strong> (
      {daysLeft === 1 ? "1 day" : `${daysLeft} days`} left), and everything in it
      is deleted then.
    </p>
  );
}
