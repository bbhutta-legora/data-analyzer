// MessageBubble.test.tsx
// Tests for the MessageBubble component added in Step 9.
//
// Behaviors tested:
//  14. Renders user message content with a "You" label
//  15. Renders assistant explanation text with an "Assistant" label
//  16. Renders base64 figures as <img> elements when present
//  17. Does not render an image section when figures array is empty
//  18. "Show code" toggle is hidden when message has no code
//  19. Clicking "Show code" reveals the code block
//  20. Clicking "Hide code" hides the code block again
//  21. Renders stdout text when present in result
//  22. Renders an error state when the message has an error field

import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MessageBubble } from "../MessageBubble";
import type { Message } from "../../store";

describe("MessageBubble", () => {
  // Behavior 14
  it("renders user message content with a 'You' label", () => {
    const msg: Message = { role: "user", content: "What is the mean?" };
    render(<MessageBubble message={msg} />);

    expect(screen.getByText("You")).toBeInTheDocument();
    expect(screen.getByText("What is the mean?")).toBeInTheDocument();
  });

  // Behavior 15
  it("renders assistant explanation text with an 'Assistant' label", () => {
    const msg: Message = {
      role: "assistant",
      content: "The average is 42.",
    };
    render(<MessageBubble message={msg} />);

    expect(screen.getByText("Assistant")).toBeInTheDocument();
    expect(screen.getByText("The average is 42.")).toBeInTheDocument();
  });

  // Behavior 16
  it("renders base64 figures as img elements when present", () => {
    const msg: Message = {
      role: "assistant",
      content: "Here is the chart.",
      figures: ["abc123base64"],
    };
    render(<MessageBubble message={msg} />);

    const img = screen.getByRole("img");
    expect(img).toHaveAttribute("src", "data:image/png;base64,abc123base64");
  });

  // Behavior 17
  it("does not render an image when figures array is empty", () => {
    const msg: Message = {
      role: "assistant",
      content: "No chart.",
      figures: [],
    };
    render(<MessageBubble message={msg} />);

    expect(screen.queryByRole("img")).not.toBeInTheDocument();
  });

  // Behavior 18
  it("hides code toggle when message has no code", () => {
    const msg: Message = {
      role: "assistant",
      content: "No code here.",
    };
    render(<MessageBubble message={msg} />);

    expect(screen.queryByText(/show code/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/hide code/i)).not.toBeInTheDocument();
  });

  // Behavior 19
  it("clicking 'Show code' reveals the code block", async () => {
    const user = userEvent.setup();
    const msg: Message = {
      role: "assistant",
      content: "Result.",
      code: "print(df.mean())",
    };
    render(<MessageBubble message={msg} />);

    // Code should not be visible initially
    expect(screen.queryByText("print(df.mean())")).not.toBeInTheDocument();

    await user.click(screen.getByText(/show code/i));
    expect(screen.getByText("print(df.mean())")).toBeInTheDocument();
  });

  // Behavior 20
  it("clicking 'Hide code' hides the code block again", async () => {
    const user = userEvent.setup();
    const msg: Message = {
      role: "assistant",
      content: "Result.",
      code: "print(1)",
    };
    render(<MessageBubble message={msg} />);

    await user.click(screen.getByText(/show code/i));
    expect(screen.getByText("print(1)")).toBeInTheDocument();

    await user.click(screen.getByText(/hide code/i));
    expect(screen.queryByText("print(1)")).not.toBeInTheDocument();
  });

  // Behavior 21
  it("renders stdout text when present", () => {
    const msg: Message = {
      role: "assistant",
      content: "Computed.",
      stdout: "revenue    200.0\ncost        60.0",
    };
    render(<MessageBubble message={msg} />);

    expect(screen.getByText(/revenue\s+200\.0/)).toBeInTheDocument();
  });

  // Behavior 22
  it("renders an error state when message has an error field", () => {
    const msg: Message = {
      role: "assistant",
      content: "",
      error: "NameError: x is not defined",
    };
    render(<MessageBubble message={msg} />);

    expect(screen.getByText(/NameError/)).toBeInTheDocument();
  });
});
