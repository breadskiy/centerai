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
