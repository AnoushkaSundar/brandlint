import { CISettings } from "@/components/ci-settings";
import { placeholderMetadata } from "@/components/placeholder-page";

export const metadata = placeholderMetadata("/ci/settings");

export default function Page() {
  return <CISettings />;
}
