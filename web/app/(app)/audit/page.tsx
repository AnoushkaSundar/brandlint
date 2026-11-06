import { AuditScreen } from "@/components/audit-screen";
import { placeholderMetadata } from "@/components/placeholder-page";

export const metadata = placeholderMetadata("/audit");

export default function Page() {
  return <AuditScreen />;
}
