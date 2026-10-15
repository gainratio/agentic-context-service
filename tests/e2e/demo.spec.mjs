import { expect, test } from "@playwright/test";

// The offline demo that `make demo` opens. Served by playwright.config.mjs on DEMO_URL.
const DEMO_URL = process.env.DEMO_URL ?? "http://127.0.0.1:8091/demo/";

function watchForErrors(page) {
  const errors = [];
  page.on("pageerror", (error) => errors.push(error.message));
  page.on("console", (message) => {
    if (message.type() === "error") errors.push(message.text());
  });
  return errors;
}

test("the pricing assistant gets the cited rule and the store shows what stayed hidden", async ({ page }) => {
  const errors = watchForErrors(page);
  await page.goto(DEMO_URL);
  await expect(page.getByRole("heading", { name: "Offline demo" })).toBeVisible();
  await expect(page.getByRole("note")).toContainText("No API key");

  await page.getByRole("button", { name: "Pricing assistant asks the discount limit" }).click();

  const results = page.locator("[data-results] li");
  await expect(results.first()).toContainText("at most 20% off list price");
  await expect(results.first()).toContainText("postgres://catalog/pricing_rules/NS-100 · version 7");
  await expect(page.locator("[data-request]")).toContainText("POST /v1/context:retrieve");
  await expect(page.locator("[data-request]")).toContainText("X-ACS-Signature:");
  const margin = page.locator("tr", { hasText: "NS-100-margin" });
  await expect(margin).toContainText("Hidden: not cleared for pricing-analysis");
  const other = page.locator("tr", { hasText: "NS-100-other" });
  await expect(other).toContainText("Hidden: another company's record");
  expect(errors).toEqual([]);
});

test("the support chatbot never sees the internal limit and is refused the pricing collection", async ({ page }) => {
  const errors = watchForErrors(page);
  await page.goto(DEMO_URL);

  await page.getByRole("button", { name: "Support chatbot asks the same question" }).click();
  await expect(page.locator("[data-results] li").first()).toBeVisible();
  await expect(page.locator("[data-results]")).not.toContainText("at most 20% off");
  await expect(page.locator("[data-results]")).toContainText("15% off until October 31");

  await page.getByRole("button", { name: "Support chatbot tries to read pricing records" }).click();
  await expect(page.locator("[data-status]")).toContainText("403 POLICY_DENIED");
  await expect(page.locator("[data-results] li")).toHaveCount(0);
  expect(errors).toEqual([]);
});

test("the page says so plainly when the demo service stops answering", async ({ page }) => {
  await page.goto(DEMO_URL);
  await expect(page.locator("body[data-ready=true]")).toBeVisible();
  await page.route("**/demo/api/ask", (route) => route.abort());

  await page.getByRole("button", { name: "Ask", exact: true }).click();

  await expect(page.locator("[data-status]")).toContainText("Could not reach the demo service");
  await expect(page.getByRole("button", { name: "Ask", exact: true })).toBeEnabled();
});
