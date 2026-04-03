import fs from "node:fs";
import { expect, test } from "@playwright/test";

const SIDECAR_BASE_URL = "http://127.0.0.1:8765";
const SMOKE_PROFILE = process.env.VIVID_SMOKE_PROFILE ?? "balanced";

async function resetE2EState(page: import("@playwright/test").Page): Promise<void> {
  const response = await page.request.post(`${SIDECAR_BASE_URL}/e2e/reset`);
  expect(response.ok()).toBeTruthy();
}

async function setHardwareProfile(page: import("@playwright/test").Page, profile: string): Promise<void> {
  const response = await page.request.post(`${SIDECAR_BASE_URL}/settings`, {
    data: {
      key: "hardware_profile",
      value: profile,
    },
  });
  expect(response.ok()).toBeTruthy();
  const payload = (await response.json()) as {
    value: string;
    runtime_policy?: { name?: string };
  };
  expect(payload.value).toBe(profile);
  expect(payload.runtime_policy?.name).toBe(profile);
}

async function createProjectFromOnboarding(page: import("@playwright/test").Page): Promise<void> {
  await page.goto("/");
  await expect(page.getByRole("heading", { name: "Welcome to Vivid Studio" })).toBeVisible({ timeout: 20000 });
  await page.getByRole("button", { name: /^Photo\b/i }).click();
  await expect(page.getByRole("heading", { name: /New Project/i })).toBeVisible();
}

async function installAndActivateModel(page: import("@playwright/test").Page, modelName: string): Promise<void> {
  await page.getByRole("button", { name: "Model Hub" }).click();
  await page.getByRole("button", { name: /^Search & Install$/ }).click();
  await page.getByRole("textbox", { name: "Search Models" }).fill("stable diffusion");
  await page.getByRole("button", { name: /^Search$/ }).click();

  const remoteCard = page.getByRole("article", { name: new RegExp(`Remote model ${modelName}`, "i") });
  await expect(remoteCard).toBeVisible();
  page.once("dialog", (dialog) => dialog.accept());
  await remoteCard.getByRole("button", { name: "Install" }).click();

  await page.getByRole("button", { name: /Local Library/ }).click();
  const localCard = page.getByRole("article", { name: new RegExp(`Local model ${modelName}`, "i") });
  await expect(localCard).toBeVisible({ timeout: 10000 });
  await localCard.getByRole("button", { name: "Activate" }).click();
  await expect(localCard.getByRole("button", { name: "Active" })).toBeVisible();
}

async function fillPrompt(page: import("@playwright/test").Page, prompt: string): Promise<void> {
  const promptInput = page.getByRole("textbox", { name: "Prompt", exact: true });
  await promptInput.fill(prompt);
}

async function waitForHistoryEntries(
  page: import("@playwright/test").Page,
  expectedGenerations: number
): Promise<void> {
  const history = page.getByTestId("generation-history");
  await expect(history).toBeVisible();
  await expect(history.getByRole("button")).toHaveCount(expectedGenerations + 1);
}

test.describe("Release critical path", () => {
  test.beforeEach(async ({ page }) => {
    await resetE2EState(page);
    await setHardwareProfile(page, SMOKE_PROFILE);
  });

  test(`onboarding -> install -> activate -> generate -> inpaint -> outpaint -> export (${SMOKE_PROFILE})`, async ({
    page,
  }) => {
    await createProjectFromOnboarding(page);
    await installAndActivateModel(page, "Stable Diffusion 1.5");

    await page.getByRole("button", { name: "Studio" }).click();

    await fillPrompt(page, "A cinematic red fox in a forest clearing");
    await page.getByTestId("generation-submit").click();
    await waitForHistoryEntries(page, 1);
    await expect(page.getByText(/Branch source: generate/i)).toBeVisible();

    await page.getByRole("button", { name: "Inpaint", exact: true }).click();
    await fillPrompt(page, "Add warm sunset light around the fox");
    await page.getByRole("button", { name: "Apply Mask" }).click();
    await page.getByTestId("generation-submit").click();
    await waitForHistoryEntries(page, 2);
    await expect(page.getByTestId("generation-history").getByRole("button", { name: /inpaint/i })).toBeVisible();

    await page.getByRole("button", { name: "Outpaint", exact: true }).click();
    await fillPrompt(page, "Extend the forest into a wide panoramic scene");
    await page.getByTestId("generation-submit").click();
    await waitForHistoryEntries(page, 3);
    await expect(page.getByTestId("generation-history").getByRole("button", { name: /outpaint/i })).toBeVisible();

    await page.getByTestId("project-export").click();
    const exportedLabel = page.getByText("Exported to:");
    await expect(exportedLabel).toBeVisible();

    const exportedText = await exportedLabel.textContent();
    expect(exportedText).toBeTruthy();
    const exportPath = exportedText!.replace("Exported to:", "").trim();
    expect(exportPath.toLowerCase().endsWith(".png")).toBeTruthy();
    expect(fs.existsSync(exportPath)).toBeTruthy();
  });
});
