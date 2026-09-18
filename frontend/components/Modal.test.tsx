import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

const { back } = vi.hoisted(() => ({ back: vi.fn() }));
vi.mock("next/navigation", () => ({
  useRouter: () => ({ back }),
}));

import { Modal } from "./Modal";

describe("Modal", () => {
  it("dismisses via router.back() when Escape is pressed", () => {
    back.mockClear();
    render(
      <Modal>
        <p>content</p>
      </Modal>,
    );
    fireEvent.keyDown(document, { key: "Escape" });
    expect(back).toHaveBeenCalledTimes(1);
  });

  it("dismisses via router.back() when the close button is clicked", () => {
    back.mockClear();
    render(
      <Modal>
        <p>content</p>
      </Modal>,
    );
    fireEvent.click(screen.getByRole("button", { name: /close/i }));
    expect(back).toHaveBeenCalledTimes(1);
  });
});
