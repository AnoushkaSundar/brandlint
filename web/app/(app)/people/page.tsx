import { placeholderMetadata } from "@/components/placeholder-page";
import { UsersScreen } from "@/components/users-screen";

export const metadata = placeholderMetadata("/people");

export default function Page() {
  return <UsersScreen />;
}
