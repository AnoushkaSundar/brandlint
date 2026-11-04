import { AppSidebar } from "@/components/app-sidebar";
import { RolePreview } from "@/components/role-preview";
import { RoleProvider } from "@/components/role-provider";
import {
  SidebarInset,
  SidebarProvider,
  SidebarTrigger,
} from "@/components/ui/sidebar";
import { TooltipProvider } from "@/components/ui/tooltip";

// Signed-in shell. The route group keeps /login (block 2) outside it.
export default function AppLayout({ children }: LayoutProps<"/">) {
  return (
    <RoleProvider>
      <TooltipProvider>
        <a
          href="#main-content"
          className="sr-only focus:not-sr-only focus:fixed focus:top-3 focus:left-3 focus:z-50 focus:rounded-md focus:bg-background focus:px-4 focus:py-2 focus:text-sm focus:font-medium focus:ring-2 focus:ring-ring"
        >
          Skip to main content
        </a>
        <SidebarProvider>
          <AppSidebar />
          <SidebarInset>
            <header className="flex h-14 shrink-0 items-center justify-between gap-2 border-b px-4">
              <SidebarTrigger />
              <RolePreview />
            </header>
            <main
              id="main-content"
              tabIndex={-1}
              className="flex-1 p-6 outline-none"
            >
              {children}
            </main>
          </SidebarInset>
        </SidebarProvider>
      </TooltipProvider>
    </RoleProvider>
  );
}
