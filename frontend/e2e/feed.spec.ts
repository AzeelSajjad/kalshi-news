// frontend/e2e/feed.spec.ts
//
// This is the one thing unit tests structurally cannot reach: whether the
// intercepting-route wiring actually works -- whether clicking a card
// renders the post into the @modal slot as an overlay, at the right URL,
// over the still-mounted feed. Everything else is covered by unit tests.
// Resist adding more cases here.
import { expect, test } from "@playwright/test";

test("clicking a card opens the post as an overlay over the still-mounted feed", async ({
  page,
}) => {
  await page.goto("/");

  const feedCard = page.locator("main").getByText("Shutdown talks collapse");
  await expect(feedCard).toBeVisible();

  await feedCard.click();

  // The intercepting route swapped the URL to the standalone post's URL...
  await expect(page).toHaveURL(/\/posts\/1$/);

  // ...but rendered it into the @modal slot as an overlay, not a full
  // navigation: the dialog is up with the post's content...
  const dialog = page.getByRole("dialog");
  await expect(dialog).toBeVisible();
  await expect(dialog.getByText("Negotiators left without a framework.")).toBeVisible();

  // ...and the feed underneath is still mounted, not replaced.
  await expect(feedCard).toBeVisible();
});
