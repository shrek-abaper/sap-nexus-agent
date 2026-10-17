"use client";

import { useTheme, type ThemePreference } from "./theme";

const LABELS: Record<ThemePreference, string> = {
  system: "跟随系统",
  light: "亮色",
  dark: "暗色",
};

function ThemeIcon({ preference }: { preference: ThemePreference }) {
  const common = {
    viewBox: "0 0 24 24",
    fill: "none",
    stroke: "currentColor",
    strokeWidth: 2,
    strokeLinecap: "round",
    strokeLinejoin: "round",
    "aria-hidden": true,
  } as const;
  if (preference === "light") {
    return (
      <svg {...common}>
        <circle cx="12" cy="12" r="4" />
        <path d="M12 2v2m0 16v2M4.93 4.93l1.41 1.41m11.32 11.32 1.41 1.41M2 12h2m16 0h2M4.93 19.07l1.41-1.41M17.66 6.34l1.41-1.41" />
      </svg>
    );
  }
  if (preference === "dark") {
    return (
      <svg {...common}>
        <path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79Z" />
      </svg>
    );
  }
  return (
    <svg {...common}>
      <rect width="18" height="12" x="3" y="4" rx="2" />
      <path d="M8 20h8m-4-4v4" />
    </svg>
  );
}

// Cycles system -> light -> dark. Lives in sidebars' footer areas.
export function ThemeToggle() {
  const { preference, cycle } = useTheme();
  const label = LABELS[preference];
  return (
    <button
      type="button"
      className="theme-toggle"
      onClick={cycle}
      aria-label={`主题：${label}，点击切换`}
      title={`主题：${label}`}
    >
      <ThemeIcon preference={preference} />
    </button>
  );
}
