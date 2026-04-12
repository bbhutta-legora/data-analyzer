// App.tsx
// Top-level component for the Smart Dataset Explainer.
// Reads currentScreen from the Zustand store and renders the matching screen.
// Architecture ref: "Frontend Architecture" in planning/architecture.md §4
//
// Placeholder screens (SetupScreen, UploadScreen, ChatScreen) will be replaced
// with real components in Steps 6, 7, and 9 respectively.

import { useStore } from "./store";

function SetupScreen() {
  return <div data-testid="screen-setup">Setup screen — coming in Step 6</div>;
}

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
  return <SetupScreen />;
}
