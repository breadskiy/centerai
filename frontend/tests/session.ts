import { expect, test as base } from "@playwright/test";
import { randomUUID } from "node:crypto";

export const test = base.extend<{ signedIn: void }>({
  signedIn: [
    async ({ context }, use) => {
      const response = await context.request.post("/api/v1/auth/register", {
        data: {
          email: `user-${randomUUID()}@example.com`,
          password: "Tangerine-River42!",
        },
      });
      expect(response.status()).toBe(201);
      await use();
    },
    { auto: true },
  ],
  request: async ({ context }, use) => {
    await use(context.request);
  },
});

export { expect };
