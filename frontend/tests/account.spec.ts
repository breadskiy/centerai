import { expect, test } from "@playwright/test";
import { randomUUID } from "node:crypto";

test("Тема переключается с экрана регистрации и входа", async ({ page }) => {
  await page.emulateMedia({
    colorScheme: "dark",
    reducedMotion: "no-preference",
  });
  await page.goto("/");
  const toggle = page.getByRole("button", { name: "Тёмная тема" });
  await expect(toggle.locator(".lucide-moon")).toBeVisible();
  const bounds = await toggle.boundingBox();
  expect(bounds?.y).toBeLessThan(40);
  expect(bounds?.x).toBeGreaterThan((page.viewportSize()?.width ?? 0) - 96);
  await toggle.focus();
  await expect(toggle).toHaveCSS("outline-style", "none");
  await expect(toggle).toHaveCSS("border-top-width", "0px");
  const root = page.locator("html");
  await toggle.click();
  await expect(root).toHaveClass(/theme-revealing/);
  await expect
    .poll(() =>
      page.evaluate(() =>
        document
          .getAnimations()
          .some(
            (animation) =>
              animation instanceof CSSAnimation &&
              animation.animationName === "theme-reveal",
          ),
      ),
    )
    .toBe(true);
  await expect(toggle.locator(".lucide-sun")).toBeVisible();
  await expect(page.locator("html")).toHaveAttribute("data-theme", "light");
  await page.reload();
  await page
    .getByRole("button", { name: "Вход в аккаунт", exact: true })
    .click();
  await expect(toggle.locator(".lucide-sun")).toBeVisible();
  await page.emulateMedia({ reducedMotion: "reduce" });
  await toggle.click();
  await expect(root).toHaveAttribute("data-theme", "dark");
  await expect(root).not.toHaveClass(/theme-revealing/);
});

test("Язык регистрации переключается и сохраняется", async ({ page }) => {
  const response = await page.goto("/");
  expect(response?.headers()["cache-control"]).toBe("no-store");
  await expect(page).toHaveTitle("CenTRap");
  await page.getByRole("combobox", { name: "Язык" }).focus();
  const ring = await page
    .getByRole("combobox", { name: "Язык" })
    .evaluate((select) => getComputedStyle(select).outlineStyle);
  expect(ring).toBe("none");
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
  const password = "birch amber frost";
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
  await page.getByLabel("Пароль", { exact: true }).fill("Password12345!");
  await expect(page.getByText("Слабый", { exact: true })).toBeVisible();
  await page.getByLabel("Пароль", { exact: true }).fill(password);
  await expect(page.getByText("Надёжный", { exact: true })).toBeVisible();
  const registration = page.waitForResponse(
    (response) =>
      response.url().endsWith("/api/v1/auth/register") &&
      response.request().method() === "POST",
  );
  await page
    .getByRole("button", { name: "Создать аккаунт", exact: true })
    .click();
  expect((await registration).status()).toBe(201);
  await expect(
    page.getByRole("heading", { name: "Главная", exact: true }),
  ).toBeVisible();
  await page.getByRole("link", { name: "Личный кабинет" }).click();
  await expect(
    page.getByRole("heading", { name: "Личный кабинет" }),
  ).toBeVisible();
  expect(
    (await page.locator(".account-avatar").boundingBox())?.width,
  ).toBeGreaterThan(150);
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
