import { ApprovalsScreen } from "@/components/approvals-screen";
import { placeholderMetadata } from "@/components/placeholder-page";

export const metadata = placeholderMetadata("/approvals");

export default function Page() {
  return <ApprovalsScreen />;
}
