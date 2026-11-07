import { placeholderMetadata } from "@/components/placeholder-page";
import { ProposalsScreen } from "@/components/proposals-screen";

export const metadata = placeholderMetadata("/proposals");

export default function Page() {
  return <ProposalsScreen />;
}
