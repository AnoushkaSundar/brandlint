import { GraphScreen } from "@/components/graph-screen";
import { placeholderMetadata } from "@/components/placeholder-page";

export const metadata = placeholderMetadata("/graph");

export default function Page() {
  return <GraphScreen />;
}
