// TypeScript mirror of docs/contracts.md. The rest of the shared types land with
// the contracts/v1 PR.

export const ROLES = [
  "creator",
  "reviewer",
  "manager",
  "legal",
  "admin",
] as const;

export type Role = (typeof ROLES)[number];
