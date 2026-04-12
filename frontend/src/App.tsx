// App.tsx
// Top-level component for the Smart Dataset Explainer.
// Reads currentScreen from the Zustand store and renders the matching screen.
// Architecture ref: "Frontend Architecture" in planning/architecture.md §4
//
// Screen progression: setup (ApiKeyInput) → upload (FileUpload) → chat (DataSummary).
// Steps 9+ will replace the chat screen with a full ChatPanel component.

import { useStore } from "./store";
import { ApiKeyInput } from "./components/ApiKeyInput";
import { FileUpload } from "./components/FileUpload";
import { DataSummary } from "./components/DataSummary";
import HelpModal from "./components/HelpModal";

function CurrentScreen() {
  const currentScreen = useStore((state) => state.currentScreen);

  if (currentScreen === "upload") return <FileUpload />;
  if (currentScreen === "chat") return <DataSummary />;
  return <ApiKeyInput />;
}

export default function App() {
  return (
    <>
      <CurrentScreen />
      <HelpModal />
    </>
  );
}
