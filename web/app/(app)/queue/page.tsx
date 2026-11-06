import { QueueScreen } from "@/components/queue-screen";
import { placeholderMetadata } from "@/components/placeholder-page";

export const metadata = placeholderMetadata("/queue");

export default function Page() {
  return <QueueScreen />;
}
