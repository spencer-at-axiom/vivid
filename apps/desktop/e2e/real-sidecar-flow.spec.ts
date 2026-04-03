import fs from "node:fs";
import { expect, test } from "@playwright/test";

const SIDECAR_BASE_URL = "http://127.0.0.1:8765";

async function resetE2EState(page: import("@playwright/test").Page): Promise<void> {
  const response = await page.request.post(`${SIDECAR_BASE_URL}/e2e/reset`);
  expect(response.ok()).toBeTruthy();
}

async function createProjectFromOnboarding(page: import("@playwright/test").Page): Promise<void> {
  await page.goto("/");
  await expect(page.getByRole("heading", { name: "Welcome to Vivid Studio" })).toBeVisible({ timeout: 20000 });
  await page.locator(".intent-card").first().click();
  await expect(page.getByRole("heading", { name: /New Project/i })).toBeVisible();
}

async function installAndActivateFirstModel(page: import("@playwright/test").Page): Promise<void> {
  await page.getByRole("button", { name: "Model Hub" }).click();
  await page.getByRole("button", { name: /^Search & Install$/ }).click();
  await page.getByPlaceholder("Search Hugging Face models...").fill("stable diffusion");
  await page.getByRole("button", { name: /^Search$/ }).click();

  const sd15Card = page.locator(".model-grid .model-card").filter({ hasText: "Stable Diffusion 1.5" }).first();
  const firstInstallButton = sd15Card.getByRole("button", { name: "Install" });
  await expect(firstInstallButton).toBeVisible();
  page.once("dialog", (dialog) => dialog.accept());
  await firstInstallButton.click();
  await expect(page.getByRole("button", { name: /Local Library/ })).toBeVisible();
  const localCard = page.locator(".model-grid .model-card").filter({ hasText: "Stable Diffusion 1.5" }).first();
  await expect(localCard).toBeVisible({ timeout: 10000 });
  await localCard.getByRole("button", { name: "Activate" }).click();
  await expect(localCard.getByRole("button", { name: "Active" })).toBeVisible();
}

async function waitForGenerationButtons(page: import("@playwright/test").Page, expectedMinimum: number): Promise<void> {
  await expect
    .poll(async () => {
      return page.locator("footer.timeline .timeline-item-mode").count();
    })
    .toBeGreaterThanOrEqual(expectedMinimum);
}

async function fillPromptAndWaitForGenerate(page: import("@playwright/test").Page, prompt: string): Promise<void> {
  const promptInput = page.getByRole("textbox", { name: "Prompt", exact: true });
  const generateButton = page.locator(".generate-btn");
  for (let attempt = 0; attempt < 8; attempt += 1) {
    await promptInput.fill(prompt);
    if (await generateButton.isEnabled()) {
      return;
    }
    await page.waitForTimeout(250);
  }
  await expect(generateButton).toBeEnabled();
}

async function fetchQueueState(page: import("@playwright/test").Page): Promise<{
  queued_job_ids: string[];
  queued_count: number;
  paused: boolean;
  running_status?: "running" | "cancel_requested" | null;
}> {
  const response = await page.request.get(`${SIDECAR_BASE_URL}/jobs/queue/state`);
  expect(response.ok()).toBeTruthy();
  const payload = (await response.json()) as {
    item: {
      queued_job_ids: string[];
      queued_count: number;
      paused: boolean;
      running_status?: "running" | "cancel_requested" | null;
    };
  };
  return payload.item;
}

async function fetchLatestProjectId(page: import("@playwright/test").Page): Promise<string> {
  const response = await page.request.get(`${SIDECAR_BASE_URL}/projects?limit=1`);
  expect(response.ok()).toBeTruthy();
  const payload = (await response.json()) as { items: Array<{ id: string }> };
  expect(payload.items.length).toBeGreaterThan(0);
  return payload.items[0].id;
}

test.describe("Real sidecar studio flows", () => {
  test.describe.configure({ mode: "serial" });

  test.beforeEach(async ({ page }) => {
    await resetE2EState(page);
  });

  test("generation stays blocked until a model is activated", async ({ page }) => {
    await createProjectFromOnboarding(page);

    const promptInput = page.getByRole("textbox", { name: "Prompt", exact: true });
    const generateButton = page.locator(".generate-btn");
    await promptInput.fill("activation required");
    await expect(generateButton).toBeDisabled();
    await expect(page.getByText("Activate a local model in Model Hub before generating.")).toBeVisible();
  });

  test("install -> generate -> img2img -> inpaint -> outpaint -> upscale -> export", async ({ page }) => {
    await createProjectFromOnboarding(page);
    await installAndActivateFirstModel(page);

    await page.getByRole("button", { name: "Studio" }).click();
    await fillPromptAndWaitForGenerate(page, "A red fox in a cinematic forest");
    await page.locator(".generate-btn").click();

    await waitForGenerationButtons(page, 1);

    await page.getByRole("button", { name: "Img2Img" }).click();
    await fillPromptAndWaitForGenerate(page, "Remix with a storm-lit dramatic sky");
    await page.locator(".generate-btn").click();

    await waitForGenerationButtons(page, 2);

    await page.getByRole("button", { name: "Inpaint" }).first().click();
    await fillPromptAndWaitForGenerate(page, "Inpaint with warm sunset lighting");
    await page.getByRole("button", { name: "Apply Mask" }).click();
    await page.locator(".generate-btn").click();

    await waitForGenerationButtons(page, 3);

    await page.getByRole("button", { name: "Outpaint" }).click();
    await fillPromptAndWaitForGenerate(page, "Extend the scene into a wide forest clearing");
    await page.locator(".generate-btn").click();

    await waitForGenerationButtons(page, 4);

    await page.getByRole("button", { name: "Upscale" }).click();
    await fillPromptAndWaitForGenerate(page, "Upscale with crisp fur detail");
    await page.locator(".generate-btn").click();

    await waitForGenerationButtons(page, 5);

    await page.getByRole("button", { name: /^Export$/ }).last().click();
    const exportedLabel = page.getByText("Exported to:");
    await expect(exportedLabel).toBeVisible();
    const exportedText = await exportedLabel.textContent();
    expect(exportedText).toBeTruthy();
    const exportPath = exportedText!.replace("Exported to:", "").trim();
    expect(exportPath.toLowerCase().endsWith(".png")).toBeTruthy();
    expect(fs.existsSync(exportPath)).toBeTruthy();
  });

  test("websocket reconnects after forced drop and still updates generation timeline", async ({ page }) => {
    await createProjectFromOnboarding(page);
    await installAndActivateFirstModel(page);
    await page.getByRole("button", { name: "Studio" }).click();

    await expect
      .poll(async () => {
        const response = await page.request.get(`${SIDECAR_BASE_URL}/e2e/websockets`);
        const payload = await response.json();
        return Number(payload.connections ?? 0);
      })
      .toBeGreaterThanOrEqual(1);

    const dropResponse = await page.request.post(`${SIDECAR_BASE_URL}/e2e/drop-websockets`);
    expect(dropResponse.ok()).toBeTruthy();

    await expect
      .poll(async () => {
        const response = await page.request.get(`${SIDECAR_BASE_URL}/e2e/websockets`);
        const payload = await response.json();
        return Number(payload.connections ?? 0);
      })
      .toBeGreaterThanOrEqual(1);

    await fillPromptAndWaitForGenerate(page, "Reconnection verification prompt");
    await page.locator(".generate-btn").click();

    await waitForGenerationButtons(page, 1);
  });

  test("queue controls use real backend semantics and survive reconnect/reload", async ({ page }) => {
    await createProjectFromOnboarding(page);
    await installAndActivateFirstModel(page);
    await page.getByRole("button", { name: "Studio" }).click();

    await fillPromptAndWaitForGenerate(page, "queue controls bootstrap job");
    await page.locator(".generate-btn").click();
    const pauseButton = page.getByRole("button", { name: "Pause Queue" });
    await expect(pauseButton).toBeVisible();

    await pauseButton.click();
    await expect(page.getByText("Queue paused")).toBeVisible();

    const bootstrapCancelButton = page.locator(".current-job .cancel-btn");
    if ((await bootstrapCancelButton.count()) > 0) {
      await bootstrapCancelButton.click();
      await expect
        .poll(async () => {
          const queue = await fetchQueueState(page);
          return queue.running_status ?? null;
        })
        .not.toBe("running");
    }

    for (let index = 1; index <= 3; index += 1) {
      await fillPromptAndWaitForGenerate(page, `queued-control-test-${index}`);
      await page.locator(".generate-btn").click();
    }

    await expect(page.getByText("Queued: 3")).toBeVisible();
    const beforeReorder = await fetchQueueState(page);
    expect(beforeReorder.queued_job_ids.length).toBeGreaterThanOrEqual(3);

    await page.locator(".queue-reorder-item").first().getByRole("button", { name: "Down" }).click();
    await expect
      .poll(async () => {
        const afterReorder = await fetchQueueState(page);
        return afterReorder.queued_job_ids.join(",");
      })
      .not.toEqual(beforeReorder.queued_job_ids.join(","));

    await page.getByRole("button", { name: "Clear Queued" }).click();
    await expect(page.getByText(/^Queued:/)).toHaveCount(0);

    await page.getByRole("button", { name: "Resume Queue" }).click();
    await expect(page.getByText("Queue paused")).toHaveCount(0);

    const projectId = await fetchLatestProjectId(page);
    const createRunningResponse = await page.request.post(`${SIDECAR_BASE_URL}/jobs/generate`, {
      data: {
        project_id: projectId,
        prompt: "cancel requested backend parity",
        params: { steps: 80 },
      },
    });
    expect(createRunningResponse.ok()).toBeTruthy();
    await expect
      .poll(async () => {
        const queue = await fetchQueueState(page);
        return queue.running_status ?? null;
      })
      .toBe("running");

    const cancelButton = page.locator(".current-job .cancel-btn");
    await expect(cancelButton).toHaveText("Cancel");
    await cancelButton.click();
    await expect
      .poll(async () => {
        const queue = await fetchQueueState(page);
        return queue.running_status ?? null;
      })
      .not.toBe("running");

    await page.getByRole("button", { name: "Pause Queue" }).click();
    await expect(page.getByText("Queue paused")).toBeVisible();

    await page.getByRole("button", { name: "Retry Last" }).click();
    await expect(page.getByText("Queued: 1")).toBeVisible();

    const dropResponse = await page.request.post(`${SIDECAR_BASE_URL}/e2e/drop-websockets`);
    expect(dropResponse.ok()).toBeTruthy();

    await expect
      .poll(async () => {
        const response = await page.request.get(`${SIDECAR_BASE_URL}/e2e/websockets`);
        const payload = await response.json();
        return Number(payload.connections ?? 0);
      })
      .toBeGreaterThanOrEqual(1);

    await page.reload();
    await expect(page.getByText("Queue paused")).toBeVisible();
    await expect(page.getByText("Queued: 1")).toBeVisible();
  });
});
