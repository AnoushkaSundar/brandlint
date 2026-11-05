import {
  PlaceholderPage,
  placeholderMetadata,
} from "@/components/placeholder-page";

const HREF = "/approvals";

export const metadata = placeholderMetadata(HREF);

export default function Page() {
  return <PlaceholderPage href={HREF} />;
}
