import { AppSidebar } from "@/components/app-sidebar";
import { AuthProvider } from "@/components/auth-provider";
import { DemoTools } from "@/components/demo-tools";
import { ExpiryBanner } from "@/components/expiry-banner";
import {
  SidebarInset,
  SidebarProvider,
  SidebarTrigger,
} from "@/components/ui/sidebar";
import { TooltipProvider } from "@/components/ui/tooltip";
import { UserMenu } from "@/components/user-menu";
import { WorkspaceBadge } from "@/components/workspace-badge";

// Signed-in shell. /login sits outside this route group.
export default function AppLayout({ children }: LayoutProps<"/">) {
  return (
    <AuthProvider>
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
            <header className="sticky top-0 z-30 flex h-14 shrink-0 items-center justify-between gap-2 border-b bg-background/90 px-4 backdrop-blur">
              <div className="flex items-center gap-3">
                <SidebarTrigger />
                <WorkspaceBadge />
              </div>
              <div className="flex flex-wrap items-center justify-end gap-3">
                <DemoTools />
                <UserMenu />
              </div>
            </header>
            <ExpiryBanner />
            <main
              id="main-content"
              tabIndex={-1}
              className="flex-1 bg-muted/40 p-6 outline-none md:p-8"
            >
              {children}
            </main>
          </SidebarInset>
        </SidebarProvider>
      </TooltipProvider>
    </AuthProvider>
  );
}
