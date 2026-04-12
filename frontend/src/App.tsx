// App.tsx
// Top-level component for the Smart Dataset Explainer.
// Reads currentScreen from the Zustand store and renders the matching screen.
// Architecture ref: "Frontend Architecture" in planning/architecture.md §4
//
// SetupScreen is now the real ApiKeyInput component (Step 6).
// UploadScreen and ChatScreen are placeholders — replaced in Steps 7 and 9.

import { useStore } from "./store";
import { ApiKeyInput } from "./components/ApiKeyInput";

function UploadScreen() {
  return <div data-testid="screen-upload">Upload screen — coming in Step 7</div>;
}

function ChatScreen() {
  return <div data-testid="screen-chat">Chat screen — coming in Step 9</div>;
}

export default function App() {
  const currentScreen = useStore((state) => state.currentScreen);

  if (currentScreen === "upload") return <UploadScreen />;
  if (currentScreen === "chat") return <ChatScreen />;
  return <ApiKeyInput />;
}
