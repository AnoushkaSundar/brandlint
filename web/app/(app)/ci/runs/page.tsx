import { CIRunsList } from "@/components/ci-runs-list";
import { placeholderMetadata } from "@/components/placeholder-page";

export const metadata = placeholderMetadata("/ci/runs");

export default function Page() {
  return <CIRunsList />;
}
