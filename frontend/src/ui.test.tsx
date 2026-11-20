// @vitest-environment jsdom
import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { RunsTable, Status } from "./ui";

describe("Состояния рабочего пространства", () => {
  it("объясняет пустую историю", () => {
    render(
      <MemoryRouter>
        <RunsTable rows={[]} />
      </MemoryRouter>,
    );
    expect(screen.getByText("История запусков пуста")).toBeTruthy();
  });
  it("обозначает пропущенную ветвь текстом", () => {
    render(<Status value="skipped" />);
    expect(screen.getByText("Пропущен")).toBeTruthy();
  });
});
