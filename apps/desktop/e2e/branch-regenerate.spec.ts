import { expect, test } from "@playwright/test";

type MockJob = {
  id: string;
  kind: string;
  status: string;
  payload: Record<string, unknown>;
  progress: number;
  eta_seconds: number;
  eta_confidence?: "none" | "low" | "high";
  progress_state?: "queued" | "running" | "finalizing" | "cancelling" | "terminal";
  error: string | null;
  created_at: string;
  updated_at: string;
};

type MockGeneration = {
  id: string;
  parent_generation_id: string | null;
  model_id: string;
  mode: string;
  prompt: string;
  params_json: Record<string, unknown>;
  output_asset_id: string;
  created_at: string;
};

type MockAsset = {
  id: string;
  project_id: string;
  path: string;
  kind: string;
  width: number;
  height: number;
  meta_json: Record<string, unknown>;
  created_at: string;
};

function buildMockPromptingConfig() {
  return {
    version: 1,
    latency_target_ms: 250,
    starter_intents: [
      {
        id: "photo",
        title: "Photo",
        description: "Portraits",
        starter_prompt: "A cinematic portrait in natural window light, detailed skin texture, professional photography",
        style_id: "cinematic",
        negative_chip_ids: ["low-quality", "text-watermark"],
        recommended_model_family: "sdxl",
        recommended_model_ids: ["stabilityai/stable-diffusion-xl-base-1.0"],
        aspect_ratio: "portrait",
        enhancer_fragments: ["single focal subject", "clean lighting hierarchy"],
      },
      {
        id: "product-mockup",
        title: "Product Mockup",
        description: "Commercial product shots",
        starter_prompt: "Premium skincare bottle on a textured studio set with soft shadows, product photography",
        style_id: "product-shot",
        negative_chip_ids: ["low-quality", "text-watermark", "framing"],
        recommended_model_family: "sd15",
        recommended_model_ids: ["runwayml/stable-diffusion-v1-5"],
        aspect_ratio: "square",
        enhancer_fragments: ["centered hero product", "controlled studio highlights"],
      },
    ],
    styles: [
      {
        id: "none",
        label: "None",
        category: "Core",
        positive: "{prompt}",
        negative: "",
        tags: ["neutral"],
        family_defaults: { sdxl: { positive: "", negative: "" }, sd15: { positive: "", negative: "" }, flux: { positive: "", negative: "" } },
      },
      {
        id: "cinematic",
        label: "Cinematic",
        category: "Look",
        positive: "{prompt}, cinematic lighting, dramatic composition, film grain, high dynamic range",
        negative: "flat lighting, overexposed, washed out, low contrast",
        tags: ["film", "moody"],
        family_defaults: { sdxl: { positive: "subtle lens depth", negative: "" }, sd15: { positive: "", negative: "muddy shadows" }, flux: { positive: "", negative: "" } },
      },
      {
        id: "product-shot",
        label: "Product Shot",
        category: "Commercial",
        positive: "{prompt}, studio product photography, controlled highlights, clean reflections, minimal backdrop",
        negative: "cluttered background, soft focus, lens dirt, motion blur",
        tags: ["photo", "clean", "commercial"],
        family_defaults: { sdxl: { positive: "premium material realism", negative: "" }, sd15: { positive: "tight tabletop composition", negative: "noisy reflections" }, flux: { positive: "", negative: "" } },
      },
    ],
    negative_prompt_chips: [
      { id: "low-quality", label: "Low Quality", fragment: "blurry, low quality", category: "fidelity", tags: ["quality"] },
      { id: "text-watermark", label: "Text / Watermark", fragment: "text, watermark, signature", category: "cleanup", tags: ["text"] },
      { id: "framing", label: "Bad Framing", fragment: "cropped, out of frame, cut off subject", category: "composition", tags: ["composition"] },
    ],
  };
}

function buildMockProject() {
  const projectId = "project-e2e-1";
  const assets: MockAsset[] = [
    {
      id: "asset-3",
      project_id: projectId,
      path: "C:\\fake\\asset-3.png",
      kind: "outpaint",
      width: 1024,
      height: 1024,
      meta_json: {},
      created_at: "2026-04-01T00:03:00Z",
    },
    {
      id: "asset-2",
      project_id: projectId,
      path: "C:\\fake\\asset-2.png",
      kind: "inpaint",
      width: 1024,
      height: 1024,
      meta_json: {},
      created_at: "2026-04-01T00:02:00Z",
    },
    {
      id: "asset-1",
      project_id: projectId,
      path: "C:\\fake\\asset-1.png",
      kind: "generate",
      width: 1024,
      height: 1024,
      meta_json: {},
      created_at: "2026-04-01T00:01:00Z",
    },
  ];

  const generations: MockGeneration[] = [
    {
      id: "gen-3",
      parent_generation_id: "gen-1",
      model_id: "runwayml/stable-diffusion-v1-5",
      mode: "outpaint",
      prompt: "outpaint branch",
      params_json: {},
      output_asset_id: "asset-3",
      created_at: "2026-04-01T00:03:00Z",
    },
    {
      id: "gen-2",
      parent_generation_id: "gen-1",
      model_id: "runwayml/stable-diffusion-v1-5",
      mode: "inpaint",
      prompt: "inpaint branch",
      params_json: {},
      output_asset_id: "asset-2",
      created_at: "2026-04-01T00:02:00Z",
    },
    {
      id: "gen-1",
      parent_generation_id: null,
      model_id: "runwayml/stable-diffusion-v1-5",
      mode: "generate",
      prompt: "root generation",
      params_json: {},
      output_asset_id: "asset-1",
      created_at: "2026-04-01T00:01:00Z",
    },
  ];

  return {
    project: {
      id: projectId,
      name: "E2E Project",
      created_at: "2026-04-01T00:00:00Z",
      updated_at: "2026-04-01T00:03:00Z",
      cover_asset_id: "asset-3",
      state: {
        version: 1,
        timeline: { selected_generation_id: null },
        canvas: { version: 1, focused_asset_id: null, assets: {}, autosaved_at: null },
      },
      assets,
      generations,
    },
    models: {
      items: [
        {
          id: "runwayml/stable-diffusion-v1-5",
          source: "huggingface",
          name: "Stable Diffusion 1.5",
          type: "sd15",
          local_path: "C:\\fake\\model",
          size_bytes: 4000000000,
          last_used_at: null,
          profile_json: { favorite: false },
          favorite: false,
          compatibility: { supported: true, reason: null, required_profile: "low_vram" },
        },
      ],
      active_model_id: "runwayml/stable-diffusion-v1-5",
    },
  };
}

test.describe("Studio branch and queue flows", () => {
  test("branches from selected timeline generation on regenerate", async ({ page }) => {
    const { project, models } = buildMockProject();
    const promptingConfig = buildMockPromptingConfig();
    const capturedJobBodies: Array<Record<string, unknown>> = [];

    await page.route("http://127.0.0.1:8765/**", async (route) => {
      const request = route.request();
      const url = new URL(request.url());
      const { pathname, searchParams } = url;
      const method = request.method();

      if (pathname === "/health" && method === "GET") {
        await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ status: "ok" }) });
        return;
      }
      if (pathname === "/prompting/config" && method === "GET") {
        await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ item: promptingConfig }) });
        return;
      }
      if (pathname === "/jobs/queue/state" && method === "GET") {
        await route.fulfill({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify({
            item: { paused: false, running_job_id: null, running_status: null, queued_job_ids: [], queued_count: 0 },
          }),
        });
        return;
      }
      if (pathname === "/jobs" && method === "GET") {
        await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ items: [], total: 0 }) });
        return;
      }
      if (pathname === "/models/local" && method === "GET") {
        await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(models) });
        return;
      }
      if (pathname === "/projects" && method === "GET" && searchParams.has("limit")) {
        await route.fulfill({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify({
            items: [
              {
                id: project.id,
                name: project.name,
                created_at: project.created_at,
                updated_at: project.updated_at,
                cover_asset_id: project.cover_asset_id,
              },
            ],
            total: 1,
          }),
        });
        return;
      }
      if (pathname === `/projects/${project.id}` && method === "GET") {
        await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ item: project }) });
        return;
      }
      if (pathname === `/projects/${project.id}/state` && method === "PUT") {
        const body = request.postDataJSON() as { state?: Record<string, unknown> };
        project.state = (body.state ?? project.state) as typeof project.state;
        await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ item: project }) });
        return;
      }
      if (pathname === "/jobs/img2img" && method === "POST") {
        const body = request.postDataJSON() as Record<string, unknown>;
        capturedJobBodies.push(body);
        const job: MockJob = {
          id: `job-${capturedJobBodies.length}`,
          kind: "img2img",
          status: "queued",
          payload: body,
          progress: 0,
          eta_seconds: 0,
          error: null,
          created_at: "2026-04-01T00:04:00Z",
          updated_at: "2026-04-01T00:04:00Z",
        };
        await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ item: job }) });
        return;
      }

      await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({}) });
    });

    await page.goto("/");

    const timeline = page.locator("footer.timeline");
    await expect(timeline).toBeVisible();
    await expect(timeline.getByRole("button", { name: /inpaint/i })).toContainText("B1 D1");

    await timeline.getByRole("button", { name: /inpaint/i }).click();
    await page.getByRole("button", { name: "Img2Img" }).click();
    await page.getByRole("textbox", { name: "Prompt", exact: true }).fill("branch regenerate request");

    const requestPromise = page.waitForRequest("http://127.0.0.1:8765/jobs/img2img");
    await page.getByRole("button", { name: "Remix (Img2Img)" }).click();
    await requestPromise;

    expect(capturedJobBodies.length).toBe(1);
    const payload = capturedJobBodies[0];
    expect(payload.parent_generation_id).toBe("gen-2");
    const params = payload.params as Record<string, unknown>;
    expect(params.init_image_asset_id).toBe("asset-2");

    await timeline.locator('button[title="root generation"]').click();
    await expect(page.getByText(/Branch source: generate/i)).toBeVisible();
    await page.getByRole("textbox", { name: "Prompt", exact: true }).fill("branch from root generation");
    const secondRequestPromise = page.waitForRequest("http://127.0.0.1:8765/jobs/img2img");
    await page.getByRole("button", { name: "Remix (Img2Img)" }).click();
    await secondRequestPromise;

    expect(capturedJobBodies.length).toBe(2);
    const secondPayload = capturedJobBodies[1];
    expect(secondPayload.parent_generation_id).toBe("gen-1");
    const secondParams = secondPayload.params as Record<string, unknown>;
    expect(secondParams.init_image_asset_id).toBe("asset-1");
  });

  test("persists timeline selection to project state across reload", async ({ page }) => {
    const { project, models } = buildMockProject();
    const promptingConfig = buildMockPromptingConfig();

    await page.route("http://127.0.0.1:8765/**", async (route) => {
      const request = route.request();
      const url = new URL(request.url());
      const { pathname, searchParams } = url;
      const method = request.method();

      if (pathname === "/health" && method === "GET") {
        await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ status: "ok" }) });
        return;
      }
      if (pathname === "/prompting/config" && method === "GET") {
        await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ item: promptingConfig }) });
        return;
      }
      if (pathname === "/jobs/queue/state" && method === "GET") {
        await route.fulfill({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify({
            item: { paused: false, running_job_id: null, running_status: null, queued_job_ids: [], queued_count: 0 },
          }),
        });
        return;
      }
      if (pathname === "/jobs" && method === "GET") {
        await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ items: [], total: 0 }) });
        return;
      }
      if (pathname === "/models/local" && method === "GET") {
        await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(models) });
        return;
      }
      if (pathname === "/projects" && method === "GET" && searchParams.has("limit")) {
        await route.fulfill({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify({
            items: [
              {
                id: project.id,
                name: project.name,
                created_at: project.created_at,
                updated_at: project.updated_at,
                cover_asset_id: project.cover_asset_id,
              },
            ],
            total: 1,
          }),
        });
        return;
      }
      if (pathname === `/projects/${project.id}` && method === "GET") {
        await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ item: project }) });
        return;
      }
      if (pathname === `/projects/${project.id}/state` && method === "PUT") {
        const body = request.postDataJSON() as { state?: Record<string, unknown> };
        project.state = (body.state ?? project.state) as typeof project.state;
        await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ item: project }) });
        return;
      }

      await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({}) });
    });

    await page.goto("/");

    const timeline = page.locator("footer.timeline");
    await expect(timeline).toBeVisible();
    await timeline.getByRole("button", { name: /inpaint/i }).click();

    await expect.poll(() => project.state.timeline.selected_generation_id).toBe("gen-2");

    await page.reload();
    await expect(page.getByText(/Branch source: inpaint/i)).toBeVisible();
    await expect(timeline.getByRole("button", { name: /inpaint/i })).toHaveClass(/timeline-item-active/);
  });

  test("supports queue reordering controls and persists requested order", async ({ page }) => {
    const { project, models } = buildMockProject();
    const promptingConfig = buildMockPromptingConfig();
    const queueState = {
      paused: false,
      running_job_id: null,
      running_status: null,
      queued_job_ids: ["job-a", "job-b", "job-c"],
      queued_count: 3,
    };
    const jobs: MockJob[] = [
      {
        id: "job-a",
        kind: "generate",
        status: "queued",
        payload: { prompt: "a" },
        progress: 0,
        eta_seconds: 0,
        error: null,
        created_at: "2026-04-01T00:10:00Z",
        updated_at: "2026-04-01T00:10:00Z",
      },
      {
        id: "job-b",
        kind: "inpaint",
        status: "queued",
        payload: { prompt: "b" },
        progress: 0,
        eta_seconds: 0,
        error: null,
        created_at: "2026-04-01T00:11:00Z",
        updated_at: "2026-04-01T00:11:00Z",
      },
      {
        id: "job-c",
        kind: "upscale",
        status: "queued",
        payload: { prompt: "c" },
        progress: 0,
        eta_seconds: 0,
        error: null,
        created_at: "2026-04-01T00:12:00Z",
        updated_at: "2026-04-01T00:12:00Z",
      },
    ];

    let lastReorderBody: { job_ids?: string[] } | null = null;

    await page.route("http://127.0.0.1:8765/**", async (route) => {
      const request = route.request();
      const url = new URL(request.url());
      const { pathname, searchParams } = url;
      const method = request.method();

      if (pathname === "/health" && method === "GET") {
        await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ status: "ok" }) });
        return;
      }
      if (pathname === "/prompting/config" && method === "GET") {
        await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ item: promptingConfig }) });
        return;
      }
      if (pathname === "/jobs/queue/state" && method === "GET") {
        await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ item: queueState }) });
        return;
      }
      if (pathname === "/jobs" && method === "GET") {
        await route.fulfill({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify({ items: jobs, total: jobs.length }),
        });
        return;
      }
      if (pathname === "/jobs/queue/reorder" && method === "POST") {
        lastReorderBody = request.postDataJSON() as { job_ids?: string[] };
        queueState.queued_job_ids = lastReorderBody.job_ids ?? queueState.queued_job_ids;
        queueState.queued_count = queueState.queued_job_ids.length;
        await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ item: queueState }) });
        return;
      }
      if (pathname === "/models/local" && method === "GET") {
        await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(models) });
        return;
      }
      if (pathname === "/projects" && method === "GET" && searchParams.has("limit")) {
        await route.fulfill({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify({
            items: [
              {
                id: project.id,
                name: project.name,
                created_at: project.created_at,
                updated_at: project.updated_at,
                cover_asset_id: project.cover_asset_id,
              },
            ],
            total: 1,
          }),
        });
        return;
      }
      if (pathname === `/projects/${project.id}` && method === "GET") {
        await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ item: project }) });
        return;
      }

      await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({}) });
    });

    await page.goto("/");

    const reorderNames = page.locator(".queue-reorder-name");
    await expect(reorderNames.first()).toHaveText("generate");

    await page.locator(".queue-reorder-item").first().getByRole("button", { name: "Down" }).click();

    expect(lastReorderBody).not.toBeNull();
    expect(lastReorderBody?.job_ids).toEqual(["job-b", "job-a", "job-c"]);
    await expect(reorderNames.first()).toHaveText("inpaint");
  });

  test("renders cancel-requested state and queue controls survive reload", async ({ page }) => {
    const { project, models } = buildMockProject();
    const promptingConfig = buildMockPromptingConfig();
    const queueState = {
      paused: false,
      running_job_id: "job-running",
      running_status: "cancel_requested",
      queued_job_ids: ["job-queued"],
      queued_count: 1,
      active_job: {
        id: "job-running",
        status: "cancel_requested",
        kind: "generate",
        progress: 0.42,
        progress_state: "cancelling",
        eta_seconds: null,
        eta_confidence: "low",
      },
      progress_contract_version: "v1",
    };
    const jobs: MockJob[] = [
      {
        id: "job-running",
        kind: "generate",
        status: "cancel_requested",
        payload: { prompt: "running" },
        progress: 0.42,
        eta_seconds: 5,
        eta_confidence: "low",
        progress_state: "cancelling",
        error: "Cancellation requested by user.",
        created_at: "2026-04-01T00:20:00Z",
        updated_at: "2026-04-01T00:20:00Z",
      },
      {
        id: "job-queued",
        kind: "inpaint",
        status: "queued",
        payload: { prompt: "queued" },
        progress: 0,
        eta_seconds: 0,
        progress_state: "queued",
        error: null,
        created_at: "2026-04-01T00:21:00Z",
        updated_at: "2026-04-01T00:21:00Z",
      },
      {
        id: "job-failed",
        kind: "upscale",
        status: "failed",
        payload: { prompt: "failed" },
        progress: 1,
        eta_seconds: 0,
        progress_state: "terminal",
        error: "simulated failure",
        created_at: "2026-04-01T00:19:00Z",
        updated_at: "2026-04-01T00:19:00Z",
      },
    ];

    let retryCount = 0;

    await page.route("http://127.0.0.1:8765/**", async (route) => {
      const request = route.request();
      const url = new URL(request.url());
      const { pathname, searchParams } = url;
      const method = request.method();

      if (pathname === "/health" && method === "GET") {
        await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ status: "ok" }) });
        return;
      }
      if (pathname === "/prompting/config" && method === "GET") {
        await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ item: promptingConfig }) });
        return;
      }
      if (pathname === "/jobs/queue/state" && method === "GET") {
        await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ item: queueState }) });
        return;
      }
      if (pathname === "/jobs" && method === "GET") {
        await route.fulfill({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify({ items: jobs, total: jobs.length }),
        });
        return;
      }
      if (pathname === "/jobs/queue/pause" && method === "POST") {
        queueState.paused = true;
        await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ item: queueState }) });
        return;
      }
      if (pathname === "/jobs/queue/resume" && method === "POST") {
        queueState.paused = false;
        await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ item: queueState }) });
        return;
      }
      if (pathname === "/jobs/queue/retry" && method === "POST") {
        retryCount += 1;
        const retriedJob: MockJob = {
          id: `job-retry-${retryCount}`,
          kind: "upscale",
          status: "queued",
          payload: { prompt: "retried" },
          progress: 0,
          eta_seconds: 0,
          progress_state: "queued",
          error: null,
          created_at: "2026-04-01T00:22:00Z",
          updated_at: "2026-04-01T00:22:00Z",
        };
        jobs.unshift(retriedJob);
        queueState.queued_job_ids = [...queueState.queued_job_ids, retriedJob.id];
        queueState.queued_count = queueState.queued_job_ids.length;
        await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ item: retriedJob }) });
        return;
      }
      if (pathname === "/jobs/queue/clear" && method === "POST") {
        for (const job of jobs) {
          if (job.status === "queued" || job.status === "recovered") {
            job.status = "cancelled";
            job.progress_state = "terminal";
            job.error = null;
          }
        }
        queueState.queued_job_ids = [];
        queueState.queued_count = 0;
        await route.fulfill({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify({
            item: {
              queue: queueState,
              maintenance: {
                wal_checkpoint: {
                  busy: 0,
                  log_frames: 0,
                  checkpointed_frames: 0,
                  mode: "PASSIVE",
                },
              },
            },
          }),
        });
        return;
      }
      if (pathname === "/models/local" && method === "GET") {
        await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(models) });
        return;
      }
      if (pathname === "/projects" && method === "GET" && searchParams.has("limit")) {
        await route.fulfill({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify({
            items: [
              {
                id: project.id,
                name: project.name,
                created_at: project.created_at,
                updated_at: project.updated_at,
                cover_asset_id: project.cover_asset_id,
              },
            ],
            total: 1,
          }),
        });
        return;
      }
      if (pathname === `/projects/${project.id}` && method === "GET") {
        await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ item: project }) });
        return;
      }

      await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({}) });
    });

    await page.goto("/");

    const cancelButton = page.locator(".current-job .cancel-btn");
    await expect(cancelButton).toHaveText("Cancelling...");
    await expect(cancelButton).toBeDisabled();
    await expect(page.getByText("Queue paused")).toHaveCount(0);
    await expect(page.getByText("Queued: 1")).toBeVisible();

    await page.getByRole("button", { name: "Pause Queue" }).click();
    await expect(page.getByText("Queue paused")).toBeVisible();

    await page.getByRole("button", { name: "Resume Queue" }).click();
    await expect(page.getByText("Queue paused")).toHaveCount(0);

    await page.getByRole("button", { name: "Retry Last" }).click();
    await expect(page.getByText("Queued: 2")).toBeVisible();

    await page.getByRole("button", { name: "Clear Queued" }).click();
    await expect(page.getByText(/^Queued:/)).toHaveCount(0);

    await page.reload();
    await expect(cancelButton).toHaveText("Cancelling...");
    await expect(cancelButton).toBeDisabled();
    await expect(page.getByText(/^Queued:/)).toHaveCount(0);
  });

  test("gesture-level canvas edits persist drag, zoom, mask, undo/redo, and reload restoration", async ({ page }) => {
    const { project, models } = buildMockProject();
    const promptingConfig = buildMockPromptingConfig();

    await page.route("http://127.0.0.1:8765/**", async (route) => {
      const request = route.request();
      const url = new URL(request.url());
      const { pathname, searchParams } = url;
      const method = request.method();

      if (pathname === "/health" && method === "GET") {
        await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ status: "ok" }) });
        return;
      }
      if (pathname === "/prompting/config" && method === "GET") {
        await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ item: promptingConfig }) });
        return;
      }
      if (pathname === "/jobs/queue/state" && method === "GET") {
        await route.fulfill({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify({
            item: { paused: false, running_job_id: null, running_status: null, queued_job_ids: [], queued_count: 0 },
          }),
        });
        return;
      }
      if (pathname === "/jobs" && method === "GET") {
        await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ items: [], total: 0 }) });
        return;
      }
      if (pathname === "/models/local" && method === "GET") {
        await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(models) });
        return;
      }
      if (pathname === "/projects" && method === "GET" && searchParams.has("limit")) {
        await route.fulfill({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify({
            items: [
              {
                id: project.id,
                name: project.name,
                created_at: project.created_at,
                updated_at: project.updated_at,
                cover_asset_id: project.cover_asset_id,
              },
            ],
            total: 1,
          }),
        });
        return;
      }
      if (pathname === `/projects/${project.id}` && method === "GET") {
        await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ item: project }) });
        return;
      }
      if (pathname === `/projects/${project.id}/state` && method === "PUT") {
        const body = request.postDataJSON() as { state?: Record<string, unknown> };
        project.state = (body.state ?? project.state) as typeof project.state;
        await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ item: project }) });
        return;
      }

      await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({}) });
    });

    await page.goto("/");

    const canvas = page.getByTestId("studio-canvas");
    const canvasBox = await canvas.boundingBox();
    expect(canvasBox).not.toBeNull();
    const startBounds = await page.getByTestId("canvas-source-bounds").textContent();
    const startZoom = await page.getByTestId("canvas-zoom").textContent();

    await page.getByRole("button", { name: "Inpaint", exact: true }).click();
    await page.mouse.move(canvasBox!.x + canvasBox!.width * 0.48, canvasBox!.y + canvasBox!.height * 0.48);
    await page.mouse.down();
    await page.mouse.move(canvasBox!.x + canvasBox!.width * 0.56, canvasBox!.y + canvasBox!.height * 0.56, { steps: 16 });
    await page.mouse.up();

    await expect(page.getByTestId("canvas-mask-count")).toHaveText("Mask strokes: 1");
    await page.getByRole("button", { name: "Undo Mask" }).click();
    await expect(page.getByTestId("canvas-mask-count")).toHaveText("Mask strokes: 0");
    await page.getByRole("button", { name: "Redo Mask" }).click();
    await expect(page.getByTestId("canvas-mask-count")).toHaveText("Mask strokes: 1");

    await page.getByRole("button", { name: "Move" }).click();
    await page.mouse.move(canvasBox!.x + canvasBox!.width * 0.5, canvasBox!.y + canvasBox!.height * 0.5);
    await page.mouse.down();
    await page.mouse.move(canvasBox!.x + canvasBox!.width * 0.62, canvasBox!.y + canvasBox!.height * 0.57, { steps: 12 });
    await page.mouse.up();
    await expect(page.getByTestId("canvas-source-bounds")).not.toHaveText(startBounds ?? "");

    await page.mouse.move(canvasBox!.x + canvasBox!.width * 0.5, canvasBox!.y + canvasBox!.height * 0.5);
    await page.mouse.wheel(0, -500);
    await expect.poll(async () => page.getByTestId("canvas-zoom").textContent()).not.toBe(startZoom);
    await page.waitForTimeout(1200);

    const persistedBounds = await page.getByTestId("canvas-source-bounds").textContent();
    const persistedZoom = await page.getByTestId("canvas-zoom").textContent();

    await page.reload();
    await expect(page.getByTestId("canvas-source-bounds")).toHaveText(persistedBounds ?? "");
    await expect(page.getByTestId("canvas-zoom")).toHaveText(persistedZoom ?? "");
    await expect(page.getByTestId("canvas-mask-count")).toHaveText("Mask strokes: 1");
  });

  test("onboarding starter flow preloads prompt stack, enhances, and auto-generates with selected local model", async ({ page }) => {
    const promptingConfig = buildMockPromptingConfig();
    const createdProject = {
      id: "starter-project",
      name: "New Project",
      created_at: "2026-04-02T00:00:00Z",
      updated_at: "2026-04-02T00:00:00Z",
      cover_asset_id: null,
      state: {
        version: 1,
        timeline: { selected_generation_id: null },
        canvas: { version: 1, focused_asset_id: null, assets: {}, autosaved_at: null },
      },
      assets: [],
      generations: [],
    };
    const models = {
      items: [
        {
          id: "runwayml/stable-diffusion-v1-5",
          source: "huggingface",
          name: "Stable Diffusion 1.5",
          type: "sd15",
          family: "sd15",
          precision: "fp16",
          local_path: "C:\\fake\\model",
          size_bytes: 4000000000,
          last_used_at: null,
          required_files: [],
          is_valid: true,
          invalid_reason: null,
          favorite: false,
          profile_json: {},
          compatibility: { supported: true, reason: null, required_profile: "low_vram" },
          supported_modes: ["generate", "img2img", "inpaint", "outpaint", "upscale"],
        },
      ],
      active_model_id: null,
    };
    const capturedGenerateBodies: Array<Record<string, unknown>> = [];

    await page.route("http://127.0.0.1:8765/**", async (route) => {
      const request = route.request();
      const url = new URL(request.url());
      const { pathname, searchParams } = url;
      const method = request.method();

      if (pathname === "/health" && method === "GET") {
        await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ status: "ok" }) });
        return;
      }
      if (pathname === "/prompting/config" && method === "GET") {
        await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ item: promptingConfig }) });
        return;
      }
      if (pathname === "/prompting/enhance" && method === "POST") {
        await route.fulfill({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify({
            item: {
              original_prompt: "Premium skincare bottle on a textured studio set with soft shadows, product photography",
              suggested_prompt:
                "Premium skincare bottle on a textured studio set with soft shadows, product photography, centered hero product, controlled studio highlights",
              intent_id: "product-mockup",
              style_id: "product-shot",
              reasons: ["Added product-specific guidance."],
              latency_ms: 9.5,
              latency_target_ms: 250,
            },
          }),
        });
        return;
      }
      if (pathname === "/jobs/queue/state" && method === "GET") {
        await route.fulfill({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify({ item: { paused: false, running_job_id: null, running_status: null, queued_job_ids: [], queued_count: 0 } }),
        });
        return;
      }
      if (pathname === "/jobs" && method === "GET") {
        await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ items: [], total: 0 }) });
        return;
      }
      if (pathname === "/models/local" && method === "GET") {
        await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(models) });
        return;
      }
      if (pathname === "/models/activate" && method === "POST") {
        const body = request.postDataJSON() as { model_id: string };
        models.active_model_id = body.model_id;
        await route.fulfill({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify({ item: models.items[0], active_model_id: body.model_id }),
        });
        return;
      }
      if (pathname === "/projects" && method === "GET" && searchParams.has("limit")) {
        await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ items: [], total: 0 }) });
        return;
      }
      if (pathname === "/projects" && method === "POST") {
        await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ item: createdProject }) });
        return;
      }
      if (pathname === `/projects/${createdProject.id}` && method === "GET") {
        await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ item: createdProject }) });
        return;
      }
      if (pathname === `/projects/${createdProject.id}/state` && method === "PUT") {
        const body = request.postDataJSON() as { state?: Record<string, unknown> };
        createdProject.state = (body.state ?? createdProject.state) as typeof createdProject.state;
        await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ item: createdProject }) });
        return;
      }
      if (pathname === "/jobs/generate" && method === "POST") {
        const body = request.postDataJSON() as Record<string, unknown>;
        capturedGenerateBodies.push(body);
        await route.fulfill({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify({
            item: {
              id: `starter-job-${capturedGenerateBodies.length}`,
              kind: "generate",
              status: "queued",
              payload: body,
              progress: 0,
              eta_seconds: null,
              eta_confidence: "low",
              progress_state: "queued",
              error: null,
              created_at: "2026-04-02T00:00:02Z",
              updated_at: "2026-04-02T00:00:02Z",
            },
          }),
        });
        return;
      }

      await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({}) });
    });

    await page.goto("/");
    await page.getByRole("button", { name: /Product Mockup/i }).click();

    await expect(page.getByRole("textbox", { name: "Prompt", exact: true })).toHaveValue(
      "Premium skincare bottle on a textured studio set with soft shadows, product photography"
    );
    await expect.poll(() => capturedGenerateBodies.length).toBeGreaterThanOrEqual(1);
    expect(capturedGenerateBodies[0].negative_prompt).toContain("blurry, low quality");
    expect(capturedGenerateBodies[0].negative_prompt).toContain("text, watermark, signature");
    expect(capturedGenerateBodies[0].negative_prompt).toContain("cropped, out of frame, cut off subject");

    await page.getByRole("button", { name: "Enhance" }).click();
    await expect(page.getByRole("button", { name: "Accept Suggestion" })).toBeVisible();
    await page.getByRole("button", { name: "Accept Suggestion" }).click();
    await expect(page.getByRole("textbox", { name: "Prompt", exact: true })).toHaveValue(/centered hero product/i);

    await page.getByRole("button", { name: "Bad Framing" }).click();
    await expect(page.getByText(/Resolved negative prompt:/)).not.toContainText("cropped, out of frame, cut off subject");
    await page.locator(".generate-btn").click();
    await expect.poll(() => capturedGenerateBodies.length).toBeGreaterThanOrEqual(2);
    expect(capturedGenerateBodies.at(-1)?.negative_prompt).not.toContain("cropped, out of frame, cut off subject");
    expect(capturedGenerateBodies.at(-1)?.prompt).toContain("studio product photography");
  });
});
