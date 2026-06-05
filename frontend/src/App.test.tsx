import { render } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, it, expect, beforeEach, vi } from "vitest";
import { ThemeProvider } from "./theme/ThemeProvider";
import App from "./App";

beforeEach(() => {
  // pages fetch on mount; stub fetch so they don't error
  vi.stubGlobal("fetch", vi.fn(() => Promise.resolve({ ok: true,
    json: () => Promise.resolve([]) })) as any);
});

function renderApp() {
  return render(
    <ThemeProvider><MemoryRouter><App /></MemoryRouter></ThemeProvider>);
}

describe("App shell", () => {
  it("renders a layout shell", () => {
    renderApp();
    expect(document.querySelector("#app-shell")).toBeTruthy();
  });
});
