import { InsightsScreen } from "@/components/insights-screen";
import { placeholderMetadata } from "@/components/placeholder-page";

export const metadata = placeholderMetadata("/insights");

export default function Page() {
  return <InsightsScreen />;
}
