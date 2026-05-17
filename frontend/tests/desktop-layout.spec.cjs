const { test, expect, _electron: electron } = require("@playwright/test");
const path = require("node:path");

async function launchApp() {
  const env = { ...process.env, TRICORE_TEST: "1" };
  delete env.ELECTRON_RUN_AS_NODE;

  const app = await electron.launch({
    args: [path.resolve(__dirname, "..")],
    env,
  });
  const page = await app.firstWindow();
  await page.waitForLoadState("domcontentloaded");
  await expect(page.getByRole("heading", { name: "TriCore Scanner" })).toBeVisible();
  return { app, page };
}

test.describe("TriCore desktop layout and controls", () => {
  test("main dashboard controls render and respond in the desktop app", async () => {
    const { app, page } = await launchApp();

    try {
      await page.setViewportSize({ width: 1440, height: 920 });

      await expect(page.getByRole("heading", { name: "Bearcat Scan Lists" })).toBeVisible();
      await expect(page.getByText("Favorites Lists")).toBeVisible();
      await expect(page.getByText("Service Types")).toBeVisible();
      await expect(page.getByText("Departments / Systems")).toBeVisible();
      await expect(page.getByText("TriCore Scanner Display")).toBeVisible();
      await expect(page.getByText("Front Panel")).toBeVisible();
      await expect(page.getByText("FM Station ID")).toBeVisible();
      await expect(page.getByRole("button", { name: /Add Channel/i })).toBeVisible();

      await expect(page.getByRole("button", { name: /^(Scan|Stop)$/i })).toBeVisible();
      await expect(page.getByRole("button", { name: /Scan playlist Railroad/i })).toBeVisible();
      await expect(page.getByRole("button", { name: /Scan Austin Area Railroads/i })).toBeVisible();
      await expect(page.getByText("P25 Trunking Decoder")).toBeVisible();
      await expect(page.getByRole("button", { name: /Start SDR Backend/i })).toBeVisible();

      await page.getByRole("button", { name: /Mute/i }).click();
      await expect(page.getByRole("button", { name: /Unmute/i })).toBeVisible();

      await page.locator("#gain").selectOption("28");
      await expect(page.locator("#gain")).toHaveValue("28");

      await page.getByRole("button", { name: /^Austin FM Radio \d+ channels$/i }).click();
      await page.getByRole("button", { name: /KVET 98\.1/i }).click();
      await expect(page.getByRole("button", { name: /Stop FM/i })).toBeVisible({ timeout: 15000 });
      await page.waitForFunction(async () => {
        const response = await fetch("http://127.0.0.1:8000/api/fm/player/status");
        const player = await response.json();
        return player.playing && player.station?.callsign === "KVET" && player.chunks > 5;
      }, null, { timeout: 20000 });
      await expect(page.getByText(/Audio playing through Windows output/i)).toBeVisible();
      await page.getByRole("button", { name: /Stop FM/i }).click();
      await expect(page.getByText(/Click any Austin FM Radio channel/i)).toBeVisible();

      await page.getByRole("button", { name: /Add Channel/i }).click();
      await expect(page.getByRole("heading", { name: "Add Channel" })).toBeVisible();
      await page.getByPlaceholder("AFD Fire Dispatch").fill("Layout Test Channel");
      await page.getByPlaceholder("Austin Fire & EMS").fill("Layout Test System");
      await page.getByPlaceholder("154.1750").fill("155.5500");
      await page.getByRole("button", { name: /^Cancel$/i }).click();
      await expect(page.getByRole("heading", { name: "Add Channel" })).toBeHidden();

      await page.setViewportSize({ width: 430, height: 820 });
      await expect(page.getByRole("heading", { name: "TriCore Scanner" })).toBeVisible();
      await expect(page.getByRole("heading", { name: "Bearcat Scan Lists" })).toBeVisible();
      await expect(page.getByText("TriCore Scanner Display")).toBeVisible();
      await expect(page.getByText("Front Panel")).toBeVisible();
    } finally {
      await app.close();
    }
  });
});
