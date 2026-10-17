import "./styles/tokens.css";
import "./styles/base.css";
import "./globals.css";

export const metadata = {
  title: "SAP Nexus Agent Workbench",
  description: "Internal console for Agent run timeline, evidence, trace, and HITL state."
};

// Apply the persisted/system theme before first paint so there is no
// light<->dark flash. Mirrors the preference contract in src/shared/ui/theme.ts.
const themeBoot = `(function(){try{var t=localStorage.getItem("sap-nexus-theme");if(t!=="light"&&t!=="dark")t="system";var d=t==="dark"||(t==="system"&&window.matchMedia("(prefers-color-scheme: dark)").matches);document.body.dataset.theme=d?"dark":"light";document.documentElement.style.colorScheme=d?"dark":"light";}catch(e){}})();`;

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    // suppressHydrationWarning: the boot script below intentionally sets
    // data-theme on <body> and color-scheme on <html> before hydration to
    // avoid a theme flash; React would otherwise flag the attribute diff.
    <html lang="zh-CN" suppressHydrationWarning>
      <body suppressHydrationWarning>
        <script dangerouslySetInnerHTML={{ __html: themeBoot }} />
        {children}
      </body>
    </html>
  );
}
