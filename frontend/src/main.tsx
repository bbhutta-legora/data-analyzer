// main.tsx
// React entry point for the Smart Dataset Explainer frontend.
// Mounts the App component into the #root div defined in index.html.
// Architecture ref: "Frontend Architecture" in planning/architecture.md §4

import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import App from "./App";

const rootElement = document.getElementById("root");

if (!rootElement) {
  throw new Error(
    "Root element #root not found in the DOM. Check index.html."
  );
}

createRoot(rootElement).render(
  <StrictMode>
    <App />
  </StrictMode>
);
