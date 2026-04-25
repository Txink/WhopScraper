import { describe, expect, it } from "vitest";
import { render } from "@testing-library/react";
import { StatusPill } from "./StatusPill";

describe("StatusPill", () => {
  it("FILLED → status-filled class", () => {
    const { container } = render(<StatusPill status="FILLED" />);
    expect(container.querySelector(".status-filled")).toBeInTheDocument();
  });

  it("PARTIAL → status-partial class", () => {
    const { container } = render(<StatusPill status="PARTIAL" />);
    expect(container.querySelector(".status-partial")).toBeInTheDocument();
  });

  it("PENDING → status-pending class", () => {
    const { container } = render(<StatusPill status="PENDING" />);
    expect(container.querySelector(".status-pending")).toBeInTheDocument();
  });

  it("SUBMITTED → status-pending class", () => {
    const { container } = render(<StatusPill status="SUBMITTED" />);
    expect(container.querySelector(".status-pending")).toBeInTheDocument();
  });

  it("NEW → status-pending class", () => {
    const { container } = render(<StatusPill status="NEW" />);
    expect(container.querySelector(".status-pending")).toBeInTheDocument();
  });

  it("CANCELLED → status-cancelled class", () => {
    const { container } = render(<StatusPill status="CANCELLED" />);
    expect(container.querySelector(".status-cancelled")).toBeInTheDocument();
  });

  it("SKIPPED → status-cancelled class", () => {
    const { container } = render(<StatusPill status="SKIPPED" />);
    expect(container.querySelector(".status-cancelled")).toBeInTheDocument();
  });

  it("REJECTED → status-error class", () => {
    const { container } = render(<StatusPill status="REJECTED" />);
    expect(container.querySelector(".status-error")).toBeInTheDocument();
  });

  it("PARSE_ERROR → status-error class", () => {
    const { container } = render(<StatusPill status="PARSE_ERROR" />);
    expect(container.querySelector(".status-error")).toBeInTheDocument();
  });

  it("SUBMIT_FAILED → status-error class", () => {
    const { container } = render(<StatusPill status="SUBMIT_FAILED" />);
    expect(container.querySelector(".status-error")).toBeInTheDocument();
  });

  it("RECEIVING → status-pending class", () => {
    const { container } = render(<StatusPill status="RECEIVED" />);
    expect(container.querySelector(".status-pending")).toBeInTheDocument();
  });

  it("PARSING → status-pending class", () => {
    const { container } = render(<StatusPill status="PARSING" />);
    expect(container.querySelector(".status-pending")).toBeInTheDocument();
  });

  it("PENDING status pill has card-status class", () => {
    const { container } = render(<StatusPill status="PENDING" />);
    // The ::before pseudo-element for pulse is CSS; we check the element exists
    const el = container.querySelector(".card-status.status-pending");
    expect(el).toBeInTheDocument();
  });
});
