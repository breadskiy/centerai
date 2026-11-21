import { expect, test } from "@playwright/test";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";

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
  page.once("dialog", (d) => d.accept());
  await page.getByRole("button", { name: "Удалить", exact: true }).click();
  await expect(
    page.getByRole("heading", { name: "Проекты", exact: true }),
  ).toBeVisible();
  expect(errors).toEqual([]);
});

test("Настройки cron, часовой пояс, выключение расписания и отказ при ошибке Telegram", async ({
  page,
  request,
}) => {
  const projectResponse = await request.post("/api/v1/projects", {
    multipart: {
      name: "Проект расписаний",
      archive: {
        name: "input.zip",
        mimeType: "application/zip",
        buffer: readFileSync(resolve("../.qa/e2e-fixture.zip")),
      },
    },
  });
  expect(projectResponse.ok()).toBeTruthy();
  const registry = await (await request.get("/api/v1/registry")).json();
  const graph = registry.default_graph;
  graph.nodes[0] = {
    ...graph.nodes[0],
    type: "schedule_trigger",
    config: registry.types.schedule_trigger.defaults,
  };
  const response = await request.post("/api/v1/workflows", {
    data: {
      project_id: (await projectResponse.json()).id,
      name: "Проверка расписания",
      graph,
    },
  });
  expect(response.ok()).toBeTruthy();
  await page.goto("/settings");
  await page.getByLabel("Cron", { exact: true }).fill("0 3 * * *");
  await page.getByLabel("Часовой пояс").fill("Europe/Moscow");
  await page.getByLabel("Включено").check();
  await page.getByRole("button", { name: "Сохранить расписание" }).click();
  await expect(page.getByText("Следующий запуск · —")).toHaveCount(0);
  await page.reload();
  await expect(page.getByLabel("Включено")).toBeChecked();
  await page.getByLabel("Включено").uncheck();
  await page.getByRole("button", { name: "Сохранить расписание" }).click();
  await expect(page.getByText("Следующий запуск · —")).toBeVisible();
  await page.getByLabel("Токен бота").fill("invalid");
  await page.getByLabel("Идентификатор чата").fill("1234");
  await page.getByRole("button", { name: "Сохранить", exact: true }).click();
  await expect(page.getByRole("status")).toContainText("Проверьте токен");
});
