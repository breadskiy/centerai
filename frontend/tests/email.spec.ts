import { expect, test } from "@playwright/test";
import { randomUUID } from "node:crypto";
import { readFileSync } from "node:fs";

function lastMail(): { from: string; to: string; body: string } {
  return JSON.parse(readFileSync("../.qa/e2e-mail.json", "utf8"));
}

test("Почта подтверждается после входа, отчёт отправляется владельцу через SMTP", async ({
  page,
}) => {
  const email = `mail-${randomUUID()}@example.com`;
  const password = "Tangerine-River42!";
  const registration = await page.request.post("/api/v1/auth/register", {
    data: { email, password },
  });
  expect(registration.status()).toBe(201);
  await page.goto("/account");
  await page
    .getByRole("button", {
      name: "Отправить письмо для подтверждения",
      exact: true,
    })
    .click();
  await expect(page.getByRole("status")).toHaveText(
    "Письмо отправлено. Откройте ссылку из письма.",
  );
  const verification = lastMail();
  expect(verification.from).toBe("noreply@example.com");
  expect(verification.to).toBe(email);
  const link = verification.body.match(
    /http:\/\/127\.0\.0\.1:8765\/account#verify-email=[A-Za-z0-9_-]+/,
  )?.[0];
  expect(link).toBeDefined();
  await page.getByRole("button", { name: "Выйти из аккаунта" }).click();
  await expect(page).toHaveURL(new URL("/", link!).href);
  await expect(page.getByRole("heading", { name: "Создайте аккаунт" })).toBeVisible();
  await page.goto(link!);
  await expect(page).toHaveURL(/\/account#verify-email=/);
  await page.getByLabel("Электронная почта").fill(email);
  await page.getByLabel("Пароль", { exact: true }).fill(password);
  await page.getByRole("button", { name: "Войти", exact: true }).click();
  await page
    .getByRole("button", { name: "Подтвердить адрес", exact: true })
    .click();
  await expect(page.getByRole("status")).toHaveText("Почта подтверждена.");
  await expect(page).toHaveURL(/\/account$/);
  const registry = await (await page.request.get("/api/v1/registry")).json();
  expect(registry.email_available).toBe(true);

  const project = await page.request.post("/api/v1/projects", {
    multipart: {
      name: "Email report session",
      archive: {
        name: "fixture.zip",
        mimeType: "application/zip",
        buffer: readFileSync("../.qa/e2e-fixture.zip"),
      },
    },
  });
  expect(project.status()).toBe(201);
  const graph = registry.default_graph;
  graph.nodes.push({ id: "mail", type: "email_notification" });
  graph.edges.push({ source: "report_generator", target: "mail" });
  const workflow = await page.request.post("/api/v1/workflows", {
    data: {
      project_id: (await project.json()).id,
      name: "Email delivery",
      graph,
    },
  });
  expect(workflow.status()).toBe(201);
  const scan = await page.request.post(
    `/api/v1/workflows/${(await workflow.json()).id}/runs`,
  );
  expect(scan.status()).toBe(202);
  const path = `/runs/${(await scan.json()).id}`;
  await page.goto(path);
  await expect(page.getByText("Принято почтовым сервером")).toBeVisible({
    timeout: 15000,
  });
  const report = lastMail();
  expect(report.from).toBe("noreply@example.com");
  expect(report.to).toBe(email);
  expect(report.body).toContain(path);
  expect(report.body).toContain("HIGH:");
  expect(report.body).not.toContain("synthetic_fixture_only");

  await page.goto("/account");
  await page.getByText("Добавить или изменить адрес", { exact: true }).click();
  await expect(page.getByLabel("Использовать только для отчётов")).toBeChecked();
  const extraEmail = `reports-${randomUUID()}@example.com`;
  await page.getByLabel("Новый адрес почты").fill(extraEmail);
  await page.getByLabel("Текущий пароль").fill(password);
  await page.getByRole("button", { name: "Отправить письмо для подтверждения", exact: true }).click();
  await expect(page.getByRole("status")).toHaveText("Подтвердите новый адрес по ссылке из письма.");
  const extraVerification = lastMail();
  expect(extraVerification.to).toBe(extraEmail);
  const extraLink = extraVerification.body.match(
    /http:\/\/127\.0\.0\.1:8765\/account#verify-email=[A-Za-z0-9_-]+/,
  )?.[0];
  expect(extraLink).toBeDefined();
  await page.goto(extraLink!);
  await page.getByRole("button", { name: "Подтвердить адрес", exact: true }).click();
  await expect(page.getByRole("status")).toHaveText("Адрес для отчётов подтверждён.");
  const account = await (await page.request.get("/api/v1/auth/session")).json();
  expect(account.email).toBe(email);
  expect(account.report_recipient).toBe(extraEmail);
});
