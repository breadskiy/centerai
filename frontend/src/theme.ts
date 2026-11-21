import { useSyncExternalStore } from "react";
import { create } from "zustand";

export type ThemePreference = "light" | "dark" | "system";

const initial = document.documentElement.dataset.theme;
export const useTheme = create<{
  theme: ThemePreference;
  setTheme: (theme: ThemePreference) => void;
}>((set) => ({
  theme: initial === "light" || initial === "dark" ? initial : "system",
  setTheme(theme) {
    if (theme === "system") delete document.documentElement.dataset.theme;
    else document.documentElement.dataset.theme = theme;
    try {
      localStorage.setItem("centerai-theme", theme);
    } catch {}
    set({ theme });
  },
}));

const systemDark = window.matchMedia("(prefers-color-scheme: dark)");
function onSystemThemeChange(listener: () => void) {
  systemDark.addEventListener("change", listener);
  return () => systemDark.removeEventListener("change", listener);
}

export function useSystemDark() {
  return useSyncExternalStore(onSystemThemeChange, () => systemDark.matches);
}
