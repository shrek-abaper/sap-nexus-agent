"use client";

import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { normalizeMarkdown } from "./normalize-markdown";

// Renders model output as markdown. react-markdown does not interpret raw
// HTML (rehype-raw is intentionally absent), so model text cannot inject
// markup; links open in a new, isolated tab.
export function Markdown({ children, raw = false }: { children: string; raw?: boolean }) {
  // Normalize only the complete final text; streaming fragments render raw.
  const source = raw ? children : normalizeMarkdown(children);
  return (
    <div className="dsh-md">
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        components={{
          a: ({ href, children }) => (
            <a href={href} target="_blank" rel="noreferrer noopener">
              {children}
            </a>
          ),
          table: ({ children }) => (
            <div className="dsh-md__table">
              <table>{children}</table>
            </div>
          ),
        }}
      >
        {source}
      </ReactMarkdown>
    </div>
  );
}
