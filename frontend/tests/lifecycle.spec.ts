import { expect, test } from "@playwright/test";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";

test("Генератор сохраняет описание при ошибке", async ({ page, request }) => {
  const project = await request.post("/api/v1/projects", {
    multipart: {
      name: "Проект для CI",
      archive: {
        name: "input.zip",
        mimeType: "application/zip",
        buffer: readFileSync(resolve("../.qa/e2e-fixture.zip")),
      },
    },
  });
  await page.goto("/workflows?new=1&project=" + (await project.json()).id);
  await page.getByLabel("Начальный граф").selectOption("prompt");
  const description = "Проверяй зависимости и отправляй письмо";
  await page.getByLabel("Что проверить").fill(description);
  await page.getByRole("button", { name: "Открыть редактор" }).click();
  await expect(
    page.getByRole("status").filter({ hasText: "Сервис модели недоступен" }),
  ).toBeVisible({ timeout: 20000 });
  await expect(page.getByLabel("Что проверить")).toHaveValue(description);
  await page.getByLabel("Начальный граф").selectOption("base");
  await page.getByRole("button", { name: "Открыть редактор" }).click();
  await expect(
    page.getByRole("button", { name: "Email", exact: true }),
  ).toBeVisible();
});

test("Готовый AI-граф сохраняет находки при недоступной модели", async ({
  page,
  request,
}) => {
  const project = await request.post("/api/v1/projects", {
    multipart: {
      name: "AI проверка",
      archive: {
        name: "input.zip",
        mimeType: "application/zip",
        buffer: readFileSync(resolve("../.qa/e2e-fixture.zip")),
      },
    },
  });
  expect(project.ok()).toBeTruthy();
  await page.goto("/workflows?new=1&project=" + (await project.json()).id);
  await page.getByLabel("Начальный граф").selectOption("ai");
  await page.getByRole("button", { name: "Открыть редактор" }).click();
  await expect(page.locator(".react-flow__node")).toHaveCount(7);
  await page
    .locator(".react-flow__node")
    .filter({ hasText: "AI-анализ" })
    .click();
  await page.getByLabel("Модель", { exact: true }).fill("offline-fixture");
  await page.getByRole("button", { name: "Проверить", exact: true }).click();
  await page.getByRole("button", { name: "Запустить", exact: true }).click();
  await expect(
    page.getByText("Модель недоступна или ответ не прошёл проверку", {
      exact: false,
    }),
  ).toBeVisible({ timeout: 20000 });
  await expect(page.getByText("2 находок в итоговом отчёте.")).toBeVisible();
});

test("Ошибки импорта, поиск, история версий, публикация и отдельная копия", async ({
  page,
}) => {
  const errors: string[] = [];
  page.on("pageerror", (e) => errors.push(e.message));
  await page.goto("/projects?new=1");
  await page
    .getByLabel("Название", { exact: true })
    .fill("Проект для шаблонов");
  await page.locator("input[type=file]").setInputFiles({
    name: "wrong.zip",
    mimeType: "application/zip",
    buffer: Buffer.from("invalid"),
  });
  await page
    .getByRole("button", { name: "Создать проект", exact: true })
    .click();
  await expect(page.getByRole("status")).toContainText("ZIP");
  await page
    .locator("input[type=file]")
    .setInputFiles(resolve("../.qa/e2e-fixture.zip"));
  await page
    .getByRole("button", { name: "Создать проект", exact: true })
    .click();
  await page.getByRole("button", { name: "Изменить", exact: true }).click();
  await page
    .getByLabel("Описание", { exact: true })
    .fill("Проверка публикации");
  await page.getByRole("button", { name: "Сохранить", exact: true }).click();
  await expect(
    page.getByText("Проверка публикации", { exact: true }),
  ).toBeVisible();
  await page
    .getByRole("link", { name: "Создать сценарий", exact: true })
    .click();
  await page.getByLabel("Название", { exact: true }).fill("Версионный граф");
  await page.getByRole("button", { name: "Открыть редактор" }).click();
  await page.getByRole("button", { name: "Regex", exact: true }).click();
  await expect(
    page.getByRole("button", { name: "Запустить", exact: true }),
  ).toBeDisabled();
  await expect(page.getByRole("alert").first()).toContainText(
    "Подключите вход",
  );
  await page.getByRole("button", { name: "Удалить узел" }).click();
  await page.getByLabel("Название сценария").fill("Версионный граф v2");
  await page.getByRole("button", { name: "Сохранить", exact: true }).click();
  await page.getByRole("button", { name: "Версии", exact: true }).click();
  await page
    .locator(".version")
    .filter({ hasText: "v1 · Версионный граф" })
    .getByRole("button", { name: "Загрузить" })
    .click();
  await expect(page.getByLabel("Название сценария")).toHaveValue(
    "Версионный граф",
  );
  await page.getByRole("button", { name: "Сохранить", exact: true }).click();
  await page
    .getByRole("navigation")
    .getByRole("link", { name: "Сценарии" })
    .click();
  await page.getByRole("button", { name: "Опубликовать версию" }).click();
  await page
    .getByRole("dialog")
    .getByLabel("Сценарий")
    .selectOption({
      label: (
        await page.getByRole("dialog").locator("option").allTextContents()
      ).find((s) => s.startsWith("Версионный граф ·"))!,
    });
  await page.getByRole("button", { name: "Опубликовать", exact: true }).click();
  await page.getByRole("button", { name: "Посмотреть шаблон" }).first().click();
  await expect(page.locator("dialog .react-flow__node")).toHaveCount(6);
  await page.getByLabel("Название копии").fill("Независимая копия");
  await page.getByRole("button", { name: "Создать из шаблона" }).click();
  await expect(page.getByLabel("Название сценария")).toHaveValue(
    "Независимая копия",
  );
  await page.getByRole("button", { name: "Запустить", exact: true }).click();
  await expect(page.getByText(/Структура JSON проверена/)).toBeVisible();
  await page.getByText("Порядок исправлений").click();
  await page.locator(".reportPreview li button").first().click();
  await expect(page.getByRole("dialog")).toContainText("Исправление");
  await page.getByRole("button", { name: "Закрыть", exact: true }).click();
  await page.goto("/projects");
  await page.getByLabel("Поиск проектов").fill("Проект для шаблонов");
  await expect(page.locator(".projectrow")).toHaveCount(1);
  await page.locator(".projectrow").click();
  await page.getByText("Источник и сценарии", { exact: true }).click();
  page.once("dialog", (d) => d.accept());
  await page.getByRole("button", { name: "Удалить", exact: true }).click();
  await expect(
    page.getByRole("heading", { name: "Сессии", exact: true }),
  ).toBeVisible();
  expect(errors).toEqual([]);
});

test("В настройках только внешний вид, язык меняется и сохраняется", async ({
  page,
}) => {
  await page.goto("/settings");
  await expect(page.getByRole("heading", { level: 2 })).toHaveText(
    "Внешний вид",
  );
  await expect(page.getByRole("combobox")).toHaveCount(2);
  await page.getByRole("combobox", { name: "Язык" }).selectOption("en");
  await expect(page.getByRole("heading", { name: "Settings" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Appearance" })).toBeVisible();
  await page.reload();
  await expect(page.getByRole("combobox", { name: "Language" })).toHaveValue(
    "en",
  );
  await page.getByRole("link", { name: "Sessions", exact: true }).click();
  await expect(page.getByRole("heading", { name: "Sessions" })).toBeVisible();
  await expect(
    page.getByRole("textbox", { name: "Search projects" }),
  ).toBeVisible();
  await page.getByRole("link", { name: "Settings", exact: true }).click();
  await page.getByRole("combobox", { name: "Language" }).selectOption("ru");
  await expect(page.getByRole("heading", { name: "Настройки" })).toBeVisible();
});
