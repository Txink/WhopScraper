import { describe, expect, it } from "vitest";
import { readFileSync } from "fs";
import { resolve, dirname } from "path";
import { fileURLToPath } from "url";

const __dirname = dirname(fileURLToPath(import.meta.url));

describe("design tokens", () => {
  it("tokens.css exists and contains required custom properties", () => {
    const content = readFileSync(resolve(__dirname, "tokens.css"), "utf-8");
    expect(content).toContain("--bg-0");
    expect(content).toContain("--bg-1");
    expect(content).toContain("--bg-2");
    expect(content).toContain("--brand");
    expect(content).toContain("--ok");
    expect(content).toContain("--err");
    expect(content).toContain("--warn");
    expect(content).toContain("--info");
    expect(content).toContain("--fg-1");
    expect(content).toContain("--fg-2");
    expect(content).toContain("--font-sans");
    expect(content).toContain("--font-mono");
    expect(content).toContain("--space-1");
    expect(content).toContain("--radius-chip");
    expect(content).toContain("--radius-card");
    expect(content).toContain("@keyframes pulse");
    expect(content).toContain("prefers-reduced-motion");
  });

  it("fonts.css exists and imports IBM Plex fonts only", () => {
    const content = readFileSync(resolve(__dirname, "fonts.css"), "utf-8");
    expect(content).toContain("IBM+Plex+Sans");
    expect(content).toContain("IBM+Plex+Mono");
    expect(content).not.toContain("Inter");
    expect(content).not.toContain("Roboto");
  });
});
