// FileUpload.tsx
// Upload screen: drag-and-drop zone + click-to-browse for CSV/Excel files.
// On successful upload, stores session data in Zustand and transitions to the chat screen.
// Supports: PRD #1 (upload), #2 (initial summary — triggers the LLM call via the backend)
// Key deps: api.ts (uploadFile), store.ts (setSessionId, setDatasetInfo, setScreen)
// Architecture ref: "Frontend Architecture" in planning/architecture.md §4

import { useCallback, useRef, useState } from "react";
import { uploadFile, ApiError } from "../api";
import { useStore } from "../store";

const ACCEPTED_EXTENSIONS = ".csv,.xlsx,.xls";
const MAX_FILE_SIZE_MB = 50;

export function FileUpload() {
  const apiKey = useStore((s) => s.apiKey);
  const provider = useStore((s) => s.provider);
  const model = useStore((s) => s.model);
  const setSessionId = useStore((s) => s.setSessionId);
  const setDatasetInfo = useStore((s) => s.setDatasetInfo);
  const setScreen = useStore((s) => s.setScreen);

  const fileInputRef = useRef<HTMLInputElement>(null);
  const [isDragOver, setIsDragOver] = useState(false);
  const [isUploading, setIsUploading] = useState(false);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const [selectedFileName, setSelectedFileName] = useState<string | null>(null);

  const handleFile = useCallback(
    async (file: File) => {
      setErrorMessage(null);
      setSelectedFileName(file.name);

      if (!apiKey || !provider || !model) {
        setErrorMessage("Missing API credentials. Go back and enter your API key.");
        return;
      }

      setIsUploading(true);

      try {
        const response = await uploadFile(file, apiKey, provider, model);
        setSessionId(response.session_id);
        setDatasetInfo({
          datasets: response.datasets,
          summary: response.summary ?? null,
        });
        setScreen("chat");
      } catch (error) {
        if (error instanceof ApiError) {
          setErrorMessage(error.detail);
        } else {
          setErrorMessage("Upload failed. Check your connection and try again.");
        }
      } finally {
        setIsUploading(false);
      }
    },
    [apiKey, provider, model, setSessionId, setDatasetInfo, setScreen]
  );

  function handleDrop(event: React.DragEvent) {
    event.preventDefault();
    setIsDragOver(false);
    const file = event.dataTransfer.files[0];
    if (file) handleFile(file);
  }

  function handleDragOver(event: React.DragEvent) {
    event.preventDefault();
    setIsDragOver(true);
  }

  function handleDragLeave() {
    setIsDragOver(false);
  }

  function handleInputChange(event: React.ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0];
    if (file) handleFile(file);
  }

  function handleBrowseClick() {
    fileInputRef.current?.click();
  }

  return (
    <div style={{ maxWidth: 520, margin: "80px auto", padding: "0 24px" }}>
      <h1 style={{ fontSize: 24, fontWeight: 600, marginBottom: 8 }}>
        Smart Dataset Explainer
      </h1>
      <p style={{ color: "#555", marginBottom: 32 }}>
        Upload your dataset to start exploring.
      </p>

      <div
        onDrop={handleDrop}
        onDragOver={handleDragOver}
        onDragLeave={handleDragLeave}
        style={{
          border: isDragOver ? "2px solid #1a73e8" : "2px dashed #ccc",
          borderRadius: 12,
          padding: "48px 24px",
          textAlign: "center",
          background: isDragOver ? "#e8f0fe" : "#fafafa",
          transition: "border-color 0.15s, background 0.15s",
          cursor: isUploading ? "not-allowed" : "pointer",
          opacity: isUploading ? 0.6 : 1,
        }}
        onClick={isUploading ? undefined : handleBrowseClick}
        data-testid="drop-zone"
      >
        <input
          ref={fileInputRef}
          type="file"
          accept={ACCEPTED_EXTENSIONS}
          onChange={handleInputChange}
          style={{ display: "none" }}
          disabled={isUploading}
        />

        {isUploading ? (
          <>
            <div style={{ fontSize: 32, marginBottom: 12 }}>⏳</div>
            <p style={{ fontSize: 15, fontWeight: 500, color: "#333", margin: "0 0 4px" }}>
              Analyzing {selectedFileName}…
            </p>
            <p style={{ fontSize: 13, color: "#888", margin: 0 }}>
              Uploading and generating summary
            </p>
          </>
        ) : (
          <>
            <div style={{ fontSize: 32, marginBottom: 12 }}>📄</div>
            <button
              type="button"
              onClick={(e) => {
                e.stopPropagation();
                handleBrowseClick();
              }}
              style={{
                padding: "8px 20px",
                fontSize: 14,
                fontWeight: 500,
                background: "#1a73e8",
                color: "#fff",
                border: "none",
                borderRadius: 6,
                cursor: "pointer",
                marginBottom: 12,
              }}
            >
              Choose file
            </button>
            <p style={{ fontSize: 14, color: "#888", margin: "0 0 4px" }}>
              or drag and drop here
            </p>
            <p style={{ fontSize: 12, color: "#aaa", margin: 0 }}>
              CSV, XLS, XLSX — up to {MAX_FILE_SIZE_MB} MB
            </p>
          </>
        )}
      </div>

      {errorMessage && (
        <p
          role="alert"
          style={{
            color: "#d93025",
            fontSize: 13,
            marginTop: 16,
            padding: "10px 14px",
            background: "#fce8e6",
            borderRadius: 6,
          }}
        >
          {errorMessage}
        </p>
      )}
    </div>
  );
}
