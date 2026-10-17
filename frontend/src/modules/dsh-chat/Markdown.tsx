"use client";

import { useRef, useState } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { normalizeMarkdown } from "./normalize-markdown";

// Code block with a hover-revealed copy button (dsh CodeBlock analogue).
function CodeBlock({ children }: { children?: React.ReactNode }) {
  const rootRef = useRef<HTMLDivElement | null>(null);
  const [copied, setCopied] = useState(false);
  return (
    <div className="dsh-codeblock" ref={rootRef}>
      <button
        type="button"
        className="dsh-codeblock__copy"
        onClick={async () => {
          const text = rootRef.current?.querySelector("pre")?.textContent ?? "";
          try {
            await navigator.clipboard.writeText(text);
            setCopied(true);
            setTimeout(() => setCopied(false), 1500);
          } catch {
            /* clipboard unavailable: stay silent */
          }
        }}
      >
        {copied ? "已复制" : "复制"}
      </button>
      <pre>{children}</pre>
    </div>
  );
}

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
          pre: ({ children }) => <CodeBlock>{children}</CodeBlock>,
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
