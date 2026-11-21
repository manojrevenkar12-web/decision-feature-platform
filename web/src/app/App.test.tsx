import { render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import fixture from "../test/report.fixture.json";
import { App } from "./App";

function mockFetch(impl: () => Promise<Response>) {
  vi.stubGlobal("fetch", vi.fn(impl));
}

afterEach(() => vi.unstubAllGlobals());

describe("App", () => {
  it("shows a skeleton while loading, then the budget tracks and every design", async () => {
    mockFetch(async () => new Response(JSON.stringify(fixture), { status: 200 }));
    render(<App />);
    expect(screen.getByRole("status")).toBeInTheDocument();
    await waitFor(() => expect(screen.getByLabelText(/against the 1,500 ms budget/)).toBeInTheDocument());
    expect(screen.getAllByText("This platform").length).toBeGreaterThan(0);
    expect(screen.getAllByText("Breaks a rule").length).toBeGreaterThan(0);
    expect(screen.getByText("Miscounts")).toBeInTheDocument();
  });

  it("offers a retry when the report fails to load", async () => {
    mockFetch(async () => new Response("boom", { status: 500 }));
    render(<App />);
    await waitFor(() => expect(screen.getByRole("alert")).toHaveTextContent("HTTP 500"));
    expect(screen.getByRole("button", { name: "Try again" })).toBeInTheDocument();
  });

  it("explains how to produce a missing report", async () => {
    mockFetch(async () => new Response("", { status: 404 }));
    render(<App />);
    await waitFor(() => expect(screen.getByText(/No held-out report yet/)).toBeInTheDocument());
    expect(screen.getByRole("button", { name: "Show the development seeds" })).toBeInTheDocument();
  });
});
