import { expect, test } from "@playwright/test";
import { randomUUID } from "node:crypto";

test("Кнопки регистрации, входа и привязки запускают разные GitHub OAuth потоки", async ({ page }) => {
  // The browser receives the actual authorization URL without contacting GitHub.
  const scopes: string[] = [];
  await page.route("https://github.com/login/oauth/authorize**", async (route) => {
    const url = new URL(route.request().url());
    scopes.push(url.searchParams.get("scope") ?? "");
    await route.fulfill({ contentType: "text/html", body: "<h1>GitHub OAuth fixture</h1>" });
  });
  const begin = async (label: string, intent: string) => {
    const request = page.waitForRequest((req) =>
      req.method() === "POST" && req.url().endsWith("/api/v1/auth/github/" + intent),
    );
    await page.getByRole("button", { name: label, exact: true }).click();
    await request;
    await expect(page.getByRole("heading", { name: "GitHub OAuth fixture" })).toBeVisible();
  };

  await page.goto("/");
  await begin("Зарегистрироваться через GitHub", "register");
  await page.goto("/");
  await page.getByRole("button", { name: "Вход в аккаунт", exact: true }).click();
  await begin("Войти через GitHub", "login");
  await page.goto("/");
  const account = await page.request.post("/api/v1/auth/register", {
    data: {
      email: "github-link-" + randomUUID() + "@example.com",
      password: "Tangerine-River42!",
    },
  });
  expect(account.status()).toBe(201);
  await page.goto("/account");
  await begin("Привязать GitHub", "link");
  expect(scopes).toEqual(["read:user user:email", "read:user", "read:user"]);
});

test("Кнопка GitHub объясняет, почему вход недоступен", async ({ page }) => {
  await page.route("**/api/v1/auth/github/status", (route) =>
    route.fulfill({ json: { available: false } }),
  );
  await page.goto("/");
  await page.getByRole("button", { name: "Зарегистрироваться через GitHub", exact: true }).click();
  await expect(page.getByRole("alert")).toHaveText(
    "Для входа через GitHub администратору нужно настроить OAuth на сервере CenterAI.",
  );
});

test("Привязанный GitHub открывает список репозиториев и позволяет включить автопроверку", async ({ page }) => {
  const account = await page.request.post("/api/v1/auth/register", {
    data: { email: "repos-" + randomUUID() + "@example.com", password: "Tangerine-River42!" },
  });
  expect(account.status()).toBe(201);
  await page.route("**/api/v1/auth/session", async (route) => {
    const response = await route.fetch();
    await route.fulfill({ response, json: { ...(await response.json()), github_login: "owner" } });
  });
  let newInvitationAccepted = false;
  await page.route("**/api/v1/github-repositories?page=1", (route) =>
    route.fulfill({
      json: {
        items: [
          { id: "7", name: "friend/demo", branch: "main", archived: false, owner: false },
          ...(newInvitationAccepted
            ? [{ id: "8", name: "team/added", branch: "main", archived: false, owner: false }]
            : []),
        ],
        has_more: false,
        needs_github_login: false,
      },
    }),
  );
  let enabled = false;
  const registry = await (await page.request.get("/api/v1/registry")).json();
  let scenario = { id: "7", repository: "friend/demo", revision: 0, name: "Полная проверка", description: "", graph: registry.default_graph };
  await page.route("**/api/v1/github-repositories/7/scenario/validate", (route) =>
    route.fulfill({ json: { valid: true } }),
  );
  await page.route("**/api/v1/github-repositories/7/scenario?page=1", (route) => {
    if (route.request().method() === "PUT") {
      const settings = route.request().postDataJSON();
      expect(settings.revision).toBe(scenario.revision);
      scenario = { ...scenario, ...settings, revision: settings.revision + 1 };
    }
    return route.fulfill({ json: scenario });
  });
  let scanStatus = "queued";
  const commitAt = Date.parse("2026-11-22T10:30:00.000Z") / 1000;
  let headSha = "a".repeat(40);
  await page.route("**/api/v1/github-repositories/watches", (route) =>
    route.fulfill({
      json: enabled ? { "7": {
        enabled,
        branch: "main",
        status: scanStatus,
        sha: "a".repeat(40),
        head_sha: headSha,
        head_committed_at: commitAt,
        count: 15,
        delta: { new: 2, fixed: 1 },
      } } : {},
    }),
  );
  await page.route("**/api/v1/github-repositories/7/watch", (route) => {
    enabled = route.request().postDataJSON().enabled;
    return route.fulfill({ json: { enabled } });
  });
  await page.goto("/");
  const nav = page.getByRole("navigation", { name: "Основная навигация" });
  await expect(nav.getByRole("link")).toHaveText(
    ["Главная", "Сессии", "Сценарии", "Запуски", "Мои репозитории", "Настройки"],
  );
  await page.getByRole("link", { name: "Мои репозитории" }).click();
  await expect(page.getByText("Соавтор", { exact: true })).toBeVisible();
  const toggle = page.getByRole("switch", { name: "Автопроверка friend/demo" });
  await expect(toggle).not.toBeChecked();
  await toggle.click();
  await expect(toggle).toBeChecked();
  await expect(page.getByText("Идёт проверка")).toBeVisible();
  const row = page.getByRole("row", { name: /friend\/demo/ });
  await expect(row.locator("time")).toHaveAttribute("datetime", "2026-11-22T10:30:00.000Z");
  await expect(row.getByRole("cell", { name: "15", exact: true })).toHaveCount(0);
  scanStatus = "success";
  await page.getByRole("button", { name: "Обновить", exact: true }).click();
  await expect(row.getByRole("cell", { name: "15", exact: true })).toBeVisible();
  await expect(row.getByText(/Новые: 2/)).toHaveCount(0);
  headSha = "b".repeat(40);
  await page.getByRole("button", { name: "Обновить", exact: true }).click();
  await expect(row.getByText("bbbbbbb")).toBeVisible();
  await expect(row.getByRole("cell", { name: "15", exact: true })).toHaveCount(0);
  await toggle.click();
  await expect(toggle).not.toBeChecked();
  await row.getByRole("link", { name: "Настроить сценарий" }).click();
  await expect(page).toHaveURL(/\/repositories\/7\/scenario\?page=1$/);
  await expect(page.getByText("friend/demo", { exact: true })).toBeVisible();
  await expect(page.locator(".react-flow__node").filter({ hasText: "Secrets" })).toBeVisible();
  await page.getByRole("textbox", { name: "Название сценария" }).fill("Сценарий репозитория");
  await page.getByRole("button", { name: "Сохранить", exact: true }).click();
  await expect.poll(() => scenario.name).toBe("Сценарий репозитория");
  await page.getByRole("link", { name: "Мои репозитории" }).last().click();
  await expect(toggle).not.toBeChecked();
  newInvitationAccepted = true;
  await page.getByRole("button", { name: "Обновить", exact: true }).click();
  await expect(page.getByRole("switch", { name: "Автопроверка team/added", exact: true })).toBeVisible();
  await expect(page).toHaveURL(/\/repositories$/);
});

test("Язык регистрации переключается и сохраняется", async ({ page }) => {
  await page.goto("/");
  await page.getByRole("combobox", { name: "Язык" }).selectOption("en");
  await expect(
    page.getByRole("heading", { name: "Create an account" }),
  ).toBeVisible();
  await page.reload();
  await expect(page.getByRole("combobox", { name: "Language" })).toHaveValue(
    "en",
  );
});

test("Регистрация, проверка пароля и сохранение профиля после входа", async ({
  page,
}) => {
  const email = `profile-${randomUUID()}@example.com`;
  const password = "Sunrise*Quartz43";
  await page.goto("/");
  await expect(
    page.getByRole("heading", { name: "Создайте аккаунт" }),
  ).toBeVisible();
  await page.getByLabel("Электронная почта").fill(email);
  await page.getByLabel("Пароль", { exact: true }).fill("123456");
  await expect(page.getByText("Слабый", { exact: true })).toBeVisible();
  await page
    .getByRole("button", { name: "Создать аккаунт", exact: true })
    .click();
  await expect(page.getByRole("alert")).toHaveText(
    "Выберите более надёжный пароль",
  );
  await page.getByLabel("Пароль", { exact: true }).fill(password);
  await page
    .getByRole("button", { name: "Создать аккаунт", exact: true })
    .click();
  await expect(
    page.getByRole("heading", { name: "Главная", exact: true }),
  ).toBeVisible();
  await page.getByRole("link", { name: "Личный кабинет" }).click();
  await page.getByLabel("Никнейм").fill("Quartz");
  await page.getByLabel("Имя пользователя Telegram").fill("@quartz_owner");
  await page.getByRole("button", { name: "Сохранить профиль" }).click();
  await expect(page.getByRole("status")).toHaveText("Профиль сохранён");
  await expect(page.getByRole("link", { name: "Личный кабинет" })).toHaveText(
    /Quartz/,
  );
  await page.getByRole("button", { name: "Выйти из аккаунта" }).click();
  await page
    .getByRole("button", { name: "Вход в аккаунт", exact: true })
    .click();
  await page.getByLabel("Электронная почта").fill(email);
  await page.getByLabel("Пароль", { exact: true }).fill(password);
  await page.getByRole("button", { name: "Войти", exact: true }).click();
  await page.getByRole("link", { name: "Личный кабинет" }).click();
  await expect(page.getByLabel("Никнейм")).toHaveValue("Quartz");
  await expect(page.getByLabel("Имя пользователя Telegram")).toHaveValue(
    "quartz_owner",
  );
});

test("Гость может запустить проверку, выход возвращает на регистрацию и удаляет историю", async ({
  page,
}) => {
  await page.goto("/");
  await page.getByRole("button", { name: "Продолжить как гость" }).click();
  await expect(
    page.getByRole("heading", { name: "Главная", exact: true }),
  ).toBeVisible();
  const response = await page.request.post("/api/v1/quick-scan", {
    multipart: {
      profile: "secrets",
      archive: {
        name: "guest.zip",
        mimeType: "application/zip",
        buffer: (await import("node:fs")).readFileSync(
          "../.qa/e2e-fixture.zip",
        ),
      },
    },
  });
  expect(response.status()).toBe(202);
  const run = await response.json();
  await expect
    .poll(async () => {
      return (await (await page.request.get("/api/v1/runs/" + run.id)).json())
        .status;
    })
    .toBe("success");
  await page.getByRole("link", { name: "Личный кабинет" }).click();
  await expect(
    page.getByRole("heading", { name: "Гостевой режим" }),
  ).toBeVisible();
  page.once("dialog", (dialog) => dialog.accept());
  await page.getByRole("button", { name: "Завершить гостевую сессию" }).click();
  await expect(
    page.getByRole("heading", { name: "Создайте аккаунт" }),
  ).toBeVisible();
  await page.getByRole("button", { name: "Продолжить как гость" }).click();
  await expect(
    page.getByRole("heading", { name: "Главная", exact: true }),
  ).toBeVisible();
  expect((await page.request.get("/api/v1/runs/" + run.id)).status()).toBe(404);
});
