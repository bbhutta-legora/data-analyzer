import { useState, useEffect, useCallback } from "react";

const EXAMPLE_QUESTIONS = [
  "What is the distribution of age?",
  "Are there correlations between price and rating?",
  "Show me the outliers in revenue",
  "Build a model to predict churn",
  "Clean up the missing values in the salary column",
];

export default function HelpModal() {
  const [open, setOpen] = useState(false);

  const close = useCallback(() => setOpen(false), []);

  useEffect(() => {
    if (!open) return;

    function handleKey(e: KeyboardEvent) {
      if (e.key === "Escape") close();
    }

    document.addEventListener("keydown", handleKey);
    return () => document.removeEventListener("keydown", handleKey);
  }, [open, close]);

  return (
    <>
      <button
        className="help-trigger"
        onClick={() => setOpen(true)}
        aria-label="Open help"
      >
        ?
      </button>

      <div
        className={`help-overlay${open ? " help-overlay--visible" : ""}`}
        onClick={close}
        aria-hidden={!open}
      />

      <aside
        className={`help-panel${open ? " help-panel--open" : ""}`}
        role="dialog"
        aria-label="Help"
        aria-hidden={!open}
      >
        <div className="help-panel__header">
          <h2>Help</h2>
          <button
            className="help-panel__close"
            onClick={close}
            aria-label="Close help"
          >
            &times;
          </button>
        </div>

        <div className="help-panel__body">
          <section>
            <h3>What this tool does</h3>
            <p>
              Upload a CSV or Excel file and explore your data through
              conversation. Ask questions in plain English&nbsp;&mdash; the tool
              writes and runs Python code behind the scenes, returning
              explanations, tables, and charts.
            </p>
          </section>

          <hr />

          <section>
            <h3>Getting started</h3>
            <ol>
              <li>
                <strong>Enter your API key</strong> &mdash; Provide an OpenAI or
                Anthropic API key. Your key is used for this session only and is
                never stored.
              </li>
              <li>
                <strong>Upload a dataset</strong> &mdash; Drag and drop or
                select a <code>.csv</code> or <code>.xlsx</code> file (up to
                50&nbsp;MB). For multi-sheet Excel files, you&rsquo;ll be asked
                to pick a sheet.
              </li>
              <li>
                <strong>Ask questions</strong> &mdash; Type a question in the
                chat. You can also click the suggested questions that appear
                after upload.
              </li>
            </ol>
          </section>

          <hr />

          <section>
            <h3>Example questions</h3>
            <ul>
              {EXAMPLE_QUESTIONS.map((q) => (
                <li key={q}>&ldquo;{q}&rdquo;</li>
              ))}
            </ul>
          </section>

          <hr />

          <section>
            <h3>Getting an API key</h3>

            <h4>OpenAI</h4>
            <p>
              Sign up at{" "}
              <a
                href="https://platform.openai.com"
                target="_blank"
                rel="noopener noreferrer"
              >
                platform.openai.com
              </a>
              , navigate to <strong>API Keys</strong>, and create a new secret
              key.
            </p>

            <h4>Anthropic</h4>
            <p>
              Sign up at{" "}
              <a
                href="https://console.anthropic.com"
                target="_blank"
                rel="noopener noreferrer"
              >
                console.anthropic.com
              </a>
              , navigate to <strong>API Keys</strong>, and generate a new key.
            </p>
          </section>

          <hr />

          <section>
            <h3>Exporting your work</h3>
            <p>
              After your analysis, click the <strong>Export</strong> button in
              the chat to download a Jupyter notebook (<code>.ipynb</code>)
              containing all the code and explanations from your session.
            </p>
          </section>
        </div>
      </aside>
    </>
  );
}
