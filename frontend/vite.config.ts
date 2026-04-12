// vite.config.ts
// Vite build and dev-server configuration for the Smart Dataset Explainer frontend.
// The proxy rule forwards /api requests to the FastAPI backend during development,
// so the frontend never needs to know the backend's port explicitly.
// Architecture ref: "Communication Protocol" in planning/architecture.md §5

import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Backend dev server runs on 8000 per planning/implementiton plan.md Step 1.
const BACKEND_DEV_URL = "http://localhost:8000";

export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      "/api": BACKEND_DEV_URL,
    },
  },
});
