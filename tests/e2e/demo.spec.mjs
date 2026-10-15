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

function record(page, title) {
  return page.locator(".record", { hasText: title });
}

test("the pricing assistant gets the cited rule and the page explains every record", async ({ page }) => {
  const errors = watchForErrors(page);
  await page.goto(DEMO_URL);
  await expect(page.getByRole("heading", { level: 1 })).toHaveText("Each AI assistant sees only what its job allows.");
  await expect(page.getByRole("note")).toContainText("Runs only on your computer");
  await expect(page.locator("[data-run]")).toBeHidden();

  await page.getByRole("button", { name: "The pricing assistant asks for a discount limit" }).click();

  await expect(page.locator("[data-who]")).toContainText("Pricing assistant at Demo Retail. It works for the pricing team.");
  const captions = page.locator("[data-captions]");
  await expect(captions).toContainText("tamper-proof tag");
  await expect(captions).toContainText("Blocked 4 of the 7 records");
  const first = page.locator("[data-results] li").first();
  await expect(first).toContainText("at most 20% off list price");
  await expect(first).toContainText("Source: the catalog database, record NS-100, edit number 7");
  await expect(page.locator("[data-why]")).toContainText("each fact says where it came from");
  await page.getByText("See all 7 records and what happened to each").click();
  await expect(record(page, "NS-100 margin target")).toContainText("Only for the finance team.");
  await expect(record(page, "NS-100 clearance discount limit")).toContainText("Belongs to another shop.");
  await expect(page.locator("[data-request]")).toContainText("X-ACS-Signature:");
  expect(errors).toEqual([]);
});

test("the help desk never sees the internal limit and is refused the pricing rules", async ({ page }) => {
  const errors = watchForErrors(page);
  await page.goto(DEMO_URL);

  await page.getByRole("button", { name: "The customer help assistant asks the same thing" }).click();
  await expect(page.locator("[data-results] li").first()).toBeVisible();
  await expect(page.locator("[data-results]")).not.toContainText("at most 20% off");
  await expect(page.locator("[data-results]")).toContainText("15% off until October 31");

  await page.getByRole("button", { name: "The customer help assistant tries to open pricing rules" }).click();
  await expect(page.locator("[data-captions]")).toContainText("Refused: it asked to open pricing rules");
  await expect(page.locator("[data-status]")).toContainText("The service said no.");
  await expect(page.locator("[data-response]")).toContainText("POLICY_DENIED");
  await expect(page.locator("[data-results] li")).toHaveCount(0);
  expect(errors).toEqual([]);
});

test("the page says so plainly when the demo service stops answering", async ({ page }) => {
  await page.goto(DEMO_URL);
  await expect(page.locator("body[data-ready=true]")).toBeVisible();
  await page.route("**/demo/api/ask", (route) => route.abort());

  await page.getByRole("button", { name: "Another shop's assistant asks the same thing" }).click();

  await expect(page.locator("[data-status]")).toContainText("Could not reach the demo service");
});

test("it reads at phone width without sideways scrolling", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto(DEMO_URL);
  await page.getByRole("button", { name: "The pricing assistant asks for a discount limit" }).click();
  await expect(page.locator("[data-results] li").first()).toBeVisible();
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
  expect(overflow).toBeLessThanOrEqual(0);
});
