"use client";

import { useEffect, useState } from "react";

// Theme preference aligned with the dsh web client: light / dark / system.
// The boot script in app/layout.tsx applies the resolved theme before first
// paint; this module owns later switches and persistence.
export type ThemePreference = "system" | "light" | "dark";
export type ResolvedTheme = "light" | "dark";

export const THEME_STORAGE_KEY = "sap-nexus-theme";
const ORDER: ThemePreference[] = ["system", "light", "dark"];

export function readThemePreference(): ThemePreference {
  if (typeof window === "undefined") return "system";
  const value = window.localStorage.getItem(THEME_STORAGE_KEY);
  return value === "light" || value === "dark" ? value : "system";
}

export function resolveTheme(preference: ThemePreference): ResolvedTheme {
  if (preference !== "system") return preference;
  if (typeof window === "undefined") return "light";
  return window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
}

export function applyTheme(preference: ThemePreference): ResolvedTheme {
  const resolved = resolveTheme(preference);
  window.localStorage.setItem(THEME_STORAGE_KEY, preference);
  document.body.dataset.theme = resolved;
  document.documentElement.style.colorScheme = resolved;
  return resolved;
}

export function nextThemePreference(current: ThemePreference): ThemePreference {
  return ORDER[(ORDER.indexOf(current) + 1) % ORDER.length];
}

export function useTheme() {
  // Initial render is always system/light to match the server; the effect
  // syncs the real persisted preference after mount (boot script already
  // applied it to the DOM, so there is no flash).
  const [preference, setPreference] = useState<ThemePreference>("system");
  const [resolved, setResolved] = useState<ResolvedTheme>("light");

  useEffect(() => {
    const stored = readThemePreference();
    setPreference(stored);
    setResolved(resolveTheme(stored));

    const media = window.matchMedia("(prefers-color-scheme: dark)");
    const onSystemChange = () => {
      setPreference((current) => {
        const next = resolveTheme(current);
        setResolved(next);
        // A live OS theme switch must reach the DOM too when following system.
        if (current === "system") {
          document.body.dataset.theme = next;
          document.documentElement.style.colorScheme = next;
        }
        return current;
      });
    };
    media.addEventListener("change", onSystemChange);
    return () => media.removeEventListener("change", onSystemChange);
  }, []);

  function cycle() {
    const next = nextThemePreference(preference);
    setPreference(next);
    setResolved(applyTheme(next));
  }

  return { preference, resolved, cycle };
}
