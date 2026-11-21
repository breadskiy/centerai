import { expect, test } from "@playwright/test";
import { randomUUID } from "node:crypto";

test("Язык регистрации переключается и сохраняется", async ({ page }) => {
  await page.goto("/");
  await page.getByRole("combobox", { name: "Язык" }).selectOption("en");
  await expect(page.getByRole("heading", { name: "Create an account" })).toBeVisible();
  await page.reload();
  await expect(page.getByRole("combobox", { name: "Language" })).toHaveValue("en");
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
    await page.getByRole("button", { name: "Вход в аккаунт", exact: true }).click();
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
