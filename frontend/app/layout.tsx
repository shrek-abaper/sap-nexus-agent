import "./globals.css";

export const metadata = {
  title: "SAP Nexus Agent Workbench",
  description: "Internal console for Agent run timeline, evidence, trace, and HITL state."
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="zh-CN">
      <body>{children}</body>
    </html>
  );
}
