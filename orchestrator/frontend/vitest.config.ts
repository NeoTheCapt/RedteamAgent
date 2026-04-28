import { defineConfig } from "vitest/config";
import react from "@vitejs/plugin-react";
import path from "node:path";

// Tests live under repo-root tests/orchestrator/frontend/ (per project policy:
// all tests under root tests/, never colocated with product source). The `@/*`
// alias points back into orchestrator/frontend/src/ so test imports stay clean.
export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: {
      "@": path.resolve(__dirname, "src"),
    },
    // Tests live at repo-root tests/orchestrator/frontend/ (per project policy).
    // A node_modules symlink there points back to this package's deps so vite's
    // standard package resolution works for react/jsx-dev-runtime etc.
    dedupe: ["react", "react-dom"],
  },
  server: {
    fs: {
      // Vitest 4 sandboxes the dev server to project root by default. Tests
      // live at repo-root tests/orchestrator/frontend/, two levels up from
      // this vitest.config.ts — allow vite to read those files.
      allow: [path.resolve(__dirname, "../..")],
    },
  },
  test: {
    environment: "jsdom",
    globals: true,
    include: [path.resolve(__dirname, "../../tests/orchestrator/frontend/*.test.{ts,tsx}")],
    // Exclude any deps that might leak in via the node_modules symlink we
    // created at tests/orchestrator/frontend/node_modules to make vite's
    // package resolver find react from this package.
    exclude: ["**/node_modules/**", "**/dist/**"],
    // Tiny setup wrapper stays in src/ so vitest's node_modules resolution
    // walks up from a path INSIDE the package and finds @testing-library.
    // Tests themselves live in tests/orchestrator/frontend/ per project policy.
    setupFiles: [path.resolve(__dirname, "src/test-setup.ts")],
    css: true,
  },
});
