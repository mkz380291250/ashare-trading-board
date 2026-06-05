import { render, screen, act } from "@testing-library/react";
import { describe, it, expect, beforeEach } from "vitest";
import { ThemeProvider, useTheme } from "./ThemeProvider";

function Probe() {
  const { isDark, toggle } = useTheme();
  return <button onClick={toggle}>{isDark ? "dark" : "light"}</button>;
}

beforeEach(() => localStorage.clear());

describe("ThemeProvider", () => {
  it("defaults to dark", () => {
    render(<ThemeProvider><Probe /></ThemeProvider>);
    expect(screen.getByRole("button").textContent).toBe("dark");
  });

  it("toggle flips theme and persists to localStorage", () => {
    render(<ThemeProvider><Probe /></ThemeProvider>);
    act(() => screen.getByRole("button").click());
    expect(screen.getByRole("button").textContent).toBe("light");
    expect(localStorage.getItem("ui-theme")).toBe("light");
  });

  it("reads initial theme from localStorage", () => {
    localStorage.setItem("ui-theme", "light");
    render(<ThemeProvider><Probe /></ThemeProvider>);
    expect(screen.getByRole("button").textContent).toBe("light");
  });
});
