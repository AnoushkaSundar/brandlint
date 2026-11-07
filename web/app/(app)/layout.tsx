import { AppSidebar } from "@/components/app-sidebar";
import { AuthProvider } from "@/components/auth-provider";
import { DemoTour } from "@/components/demo-tour";
import { DemoSwitcher } from "@/components/demo-switcher";
import {
  SidebarInset,
  SidebarProvider,
  SidebarTrigger,
} from "@/components/ui/sidebar";
import { TooltipProvider } from "@/components/ui/tooltip";
import { UserMenu } from "@/components/user-menu";
import { DEMO_MODE } from "@/lib/demo";

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
            <header className="flex h-14 shrink-0 items-center justify-between gap-2 border-b px-4">
              <SidebarTrigger />
              <div className="flex flex-wrap items-center justify-end gap-3">
                {DEMO_MODE && (
                  <>
                    <DemoTour />
                    <DemoSwitcher />
                  </>
                )}
                <UserMenu />
              </div>
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
    </AuthProvider>
  );
}
