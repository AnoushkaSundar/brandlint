import { FactsScreen } from "@/components/facts-screen";
import { placeholderMetadata } from "@/components/placeholder-page";

export const metadata = placeholderMetadata("/brand/facts");

export default function Page() {
  return <FactsScreen />;
}
