import { expect, test } from "@playwright/test";
import { resolve } from "node:path";

test("Тема следует системе и сохраняет ручной выбор", async ({ page }) => {
  const root = page.locator("html");
  await page.emulateMedia({ colorScheme: "dark" });
  await page.goto("/");
  await expect(root).toHaveCSS("background-color", "rgb(17, 19, 22)");
  await expect(page.locator(".pipeline")).toHaveCSS("background-image", "none");
  await expect(page.getByRole("img", { name: "Центр-инвест" })).toBeVisible();
  await expect(page.getByText("Workspace", { exact: true })).toHaveCount(0);
  await expect(page.getByText("Cyber Garden", { exact: true })).toHaveCount(0);
  await expect(page.getByText("Локальная среда", { exact: true })).toHaveCount(
    0,
  );
  await expect(
    page.getByRole("button", { name: "Загрузить репозиторий" }),
  ).toHaveCSS("background-color", "rgb(38, 181, 76)");

  await page.getByRole("link", { name: "Настройки", exact: true }).click();
  const theme = page.getByRole("combobox", { name: "Тема", exact: true });
  await expect(theme).toHaveValue("system");
  await theme.selectOption({ label: "Светлая" });
  await expect(root).toHaveCSS("background-color", "rgb(243, 247, 244)");
  await page.reload();
  await expect(theme).toHaveValue("light");
  await theme.selectOption({ label: "Тёмная" });
  await page.emulateMedia({ colorScheme: "light" });
  await expect(root).toHaveCSS("background-color", "rgb(17, 19, 22)");
  await theme.selectOption({ label: "Как в системе" });
  await expect(root).toHaveCSS("background-color", "rgb(243, 247, 244)");
  await page.emulateMedia({ colorScheme: "dark" });
  await expect(root).toHaveCSS("background-color", "rgb(17, 19, 22)");
});

test("ZIP → editable workflow → live execution → report and settings", async ({
  page,
}) => {
  const errors: string[] = [];
  page.on("pageerror", (e) => errors.push(e.message));
  await page.goto("/");
  await expect(page.getByRole("heading", { name: "Главная" })).toBeVisible();
  await page.screenshot({
    path: resolve("../.qa/dashboard.png"),
    fullPage: true,
  });
  await page
    .getByRole("navigation")
    .getByRole("link", { name: "Сессии", exact: true })
    .click();
  await page.getByRole("button", { name: "Новый проект", exact: true }).click();
  await page
    .getByLabel("Название", { exact: true })
    .fill("Проверка в браузере");
  await page
    .locator("input[type=file]")
    .setInputFiles(resolve("../.qa/e2e-fixture.zip"));
  await page.getByRole("button", { name: "Создать проект" }).click();
  await expect(
    page.getByRole("heading", { name: "Проверка в браузере" }),
  ).toBeVisible();
  await page.getByRole("link", { name: "Создать сценарий" }).click();
  await page.getByRole("button", { name: "Открыть редактор" }).click();
  await expect(page.locator(".react-flow__node")).toHaveCount(6);
  await page.getByLabel("Название сценария").fill("Приёмочная проверка");
  await page
    .getByRole("button", { name: "Regex", exact: true })
    .dragTo(page.locator(".canvas"), { targetPosition: { x: 200, y: 160 } });
  await expect(page.getByLabel("Выражение для пути")).toBeVisible();
  await page.getByText("Входящие связи", { exact: true }).click();
  await page.getByLabel("Вход из узла").selectOption("secrets_scanner");
  await page.getByRole("button", { name: "Соединить", exact: true }).click();
  await expect(page.locator(".react-flow__edge")).toHaveCount(8);
  await page.getByRole("button", { name: "Удалить узел" }).click();
  await page.getByRole("button", { name: "Проверить", exact: true }).click();
  await expect(page.getByText("Граф прошёл проверку")).toBeVisible();
  await page.screenshot({ path: resolve("../.qa/editor.png"), fullPage: true });
  await page.getByRole("button", { name: "Запустить", exact: true }).click();
  await expect(
    page.getByRole("heading", { name: "Выполнение графа" }),
  ).toBeVisible();
  await expect(page.getByText("2 находок в итоговом отчёте.")).toBeVisible();
  const download = page.waitForEvent("download");
  await page.getByRole("link", { name: "JSON", exact: true }).click();
  expect((await download).suggestedFilename()).toMatch(/\.json$/);
  await page.getByRole("link", { name: "Результаты сессии" }).click();
  await page.getByLabel("Категория", { exact: true }).selectOption("SECRET");
  await expect(
    page.getByRole("button", { name: "Подробности находки" }),
  ).toHaveCount(1);
  await page.getByRole("button", { name: "Подробности находки" }).click();
  await expect(page.getByRole("dialog")).toContainText("Значение скрыто");
  await page.getByRole("button", { name: "Закрыть", exact: true }).click();
  await page.getByRole("link", { name: "Настройки", exact: true }).click();
  await expect(
    page.getByRole("heading", { name: "Внешний вид" }),
  ).toBeVisible();
  await page.setViewportSize({ width: 390, height: 844 });
  await page.getByRole("link", { name: "Главная", exact: true }).click();
  await expect(page.getByRole("heading", { name: "Главная" })).toBeVisible();
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth,
    ),
  ).toBe(true);
  expect(errors).toEqual([]);
});

test("Главная принимает архив перетаскиванием и запускает выбранный профиль", async ({
  page,
}) => {
  const { readFileSync } = await import("node:fs");
  const bytes = [...readFileSync(resolve("../.qa/e2e-fixture.zip"))];
  await page.goto("/");
  await expect(
    page.getByRole("button", { name: "Загрузить репозиторий" }),
  ).toBeVisible();
  const transfer = await page.evaluateHandle((bytes) => {
    const data = new DataTransfer();
    data.items.add(new File([new Uint8Array(bytes)], "drag.zip"));
    return data;
  }, bytes);
  await page
    .locator("main")
    .dispatchEvent("dragenter", { dataTransfer: transfer });
  await expect(page.getByText("Отпустите архив")).toBeVisible();
  await page.locator("main").dispatchEvent("drop", { dataTransfer: transfer });
  await expect(page.getByRole("dialog")).toContainText("drag.zip");
  await page.getByRole("radio", { name: /Только зависимости/ }).check();
  await page.getByRole("button", { name: "Запустить проверку" }).click();
  await expect(page.getByText("1 находок в итоговом отчёте.")).toBeVisible({
    timeout: 20000,
  });
  await expect(page.locator(".risk-badges").first()).toBeVisible();
  await expect(
    page.locator(".react-flow__node").filter({ hasText: "Завершён" }),
  ).toHaveCount(0);
});

test("Главная сохраняет выбранный профиль после ошибки ссылки", async ({
  page,
}) => {
  await page.goto("/");
  await page.getByRole("button", { name: "Загрузить репозиторий" }).click();
  await page.getByRole("button", { name: "По ссылке" }).click();
  await page
    .getByLabel("Ссылка на публичный GitHub-репозиторий")
    .fill("https://example.test/owner/repo");
  await page.getByRole("radio", { name: /Только секреты/ }).check();
  await page.getByRole("button", { name: "Запустить проверку" }).click();
  await expect(page.getByRole("dialog").getByRole("alert")).toBeVisible();
  await expect(
    page.getByRole("radio", { name: /Только секреты/ }),
  ).toBeChecked();
  await page.getByRole("button", { name: "Архив", exact: true }).click();
  await page
    .getByLabel("Выбрать архив")
    .setInputFiles(resolve("../.qa/e2e-fixture.zip"));
  await page.getByRole("button", { name: "Запустить проверку" }).click();
  await expect(page.getByText("1 находок в итоговом отчёте.")).toBeVisible({
    timeout: 20000,
  });
});

test("Сессия показывает один запуск, монитор открывает выбранный снимок результатов", async ({
  page,
  request,
}) => {
  const { readFileSync } = await import("node:fs");
  const buffer = readFileSync(resolve("../.qa/e2e-fixture.zip"));
  const create = async (name: string, profile: string) => {
    const response = await request.post("/api/v1/quick-scan", {
      multipart: {
        profile,
        archive: { name, mimeType: "application/zip", buffer },
      },
    });
    expect(response.status()).toBe(202);
    const run = await response.json();
    await expect
      .poll(
        async () =>
          (await (await request.get("/api/v1/runs/" + run.id)).json()).status,
      )
      .toBe("success");
    return run;
  };
  const sca = await create("session-sca.zip", "sca");
  await create("session-secrets.zip", "secrets");
  const repeat = await request.post(
    "/api/v1/workflows/" + sca.workflow_id + "/runs",
  );
  const latest = await repeat.json();
  await expect
    .poll(
      async () =>
        (await (await request.get("/api/v1/runs/" + latest.id)).json()).status,
    )
    .toBe("success");
  await page.goto("/projects/" + sca.project_id);
  await expect(
    page.getByRole("navigation").getByRole("link", { name: "Находки" }),
  ).toHaveCount(0);
  await expect(page.getByRole("heading", { name: "Находки" })).toBeVisible();
  const search = page.getByRole("textbox", { name: "Поиск находок" });
  await search.pressSequentially("missing");
  await expect(page.getByText("Находок нет", { exact: true })).toBeVisible();
  await expect(search).toBeFocused();
  await expect(search).toHaveValue("missing");
  await search.fill("");
  await expect(page.getByRole("table").getByRole("row")).toHaveCount(2);
  const severity = page.locator(".session-severity button").first();
  await severity.click();
  await expect(severity).toHaveAttribute("aria-pressed", "true");
  await expect(page.getByRole("table").getByRole("row")).toHaveCount(2);
  await expect(page.getByRole("table").getByRole("row")).toHaveCount(2);
  await expect(page.getByRole("combobox", { name: "Запуск" })).toHaveValue(
    latest.id,
  );
  await page.getByRole("combobox", { name: "Запуск" }).selectOption(sca.id);
  await expect(page).toHaveURL(new RegExp("run_id=" + sca.id + "$"));
  await expect(page.getByRole("table").getByRole("row")).toHaveCount(2);
  await page.goto("/runs/" + sca.id);
  await page.getByRole("link", { name: "Результаты сессии" }).click();
  await expect(page).toHaveURL(
    new RegExp("/projects/" + sca.project_id + "[?]run_id=" + sca.id + "$"),
  );
  await expect
    .poll(async () => (await search.boundingBox())?.width || 0)
    .toBeLessThanOrEqual(280);
  await expect(search.locator("..")).toHaveCSS("border-radius", "999px");
  const full = await create("session-multiple-levels.zip", "full");
  await page.goto("/projects/" + full.project_id);
  const high = page.getByRole("button", { name: /^HIGH/ });
  const medium = page.getByRole("button", { name: /^MEDIUM/ });
  await high.click();
  await expect(page.getByRole("table").getByRole("row")).toHaveCount(2);
  await medium.click();
  await expect(high).toHaveAttribute("aria-pressed", "true");
  await expect(medium).toHaveAttribute("aria-pressed", "true");
  await expect(page.getByRole("table").getByRole("row")).toHaveCount(3);
  await high.click();
  await expect(page.getByRole("table").getByRole("row")).toHaveCount(2);
  await expect(
    page.getByRole("table").getByText("MEDIUM", { exact: true }),
  ).toBeVisible();
  await page.goto("/settings");
  await page.getByRole("combobox", { name: "Язык" }).selectOption("en");
  await page.goto("/projects");
  const row = page.getByRole("link", { name: /session-secrets.zip/ });
  await row.hover();
  await expect(row.locator("svg")).toHaveCSS("color", "rgb(38, 181, 76)");
  await row.click();
  await page.getByRole("button", { name: "Hardcoded API key" }).click();
  await expect(page.getByRole("dialog")).toContainText(
    "Credentials can be recovered from the project files.",
  );
});
