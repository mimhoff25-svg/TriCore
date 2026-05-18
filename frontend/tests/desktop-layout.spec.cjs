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
  await expect(page.getByRole("heading", { name: "Bearcat Scan Lists" })).toBeVisible();
  return { app, page };
}

test.describe("TriCore desktop stripped layout", () => {
  test("playlist and live screen render in the desktop app", async () => {
    const { app, page } = await launchApp();

    try {
      await page.setViewportSize({ width: 1440, height: 920 });

      await expect(page.getByRole("heading", { name: "Bearcat Scan Lists" })).toBeVisible();
      await expect(page.getByText("Favorites Lists")).toBeVisible();
      await expect(page.getByText("Service Types")).toBeVisible();
      await expect(page.getByText("Departments / Systems")).toBeVisible();
      await expect(page.getByText("Live Screen")).toBeVisible();
      await expect(page.getByText(/^Department\s*$/)).toBeVisible();
      await expect(page.getByText("Radio ID").first()).toBeVisible();

      await expect(page.getByText("Front Panel")).toHaveCount(0);
      await expect(page.getByText("FM Station ID")).toHaveCount(0);
      await expect(page.getByText(/P25 Trunking Decoder/i)).toHaveCount(0);
      await expect(page.getByText("Recent Calls")).toHaveCount(0);

      const backendOnline = await page.evaluate(async () => {
        try {
          const response = await fetch("http://127.0.0.1:8000/api/status");
          return response.ok;
        } catch {
          return false;
        }
      });

      if (backendOnline) {
        await expect(page.getByRole("button", { name: /Scan playlist Railroad/i })).toBeVisible();
        await expect(page.getByRole("button", { name: /Scan Austin Area Railroads/i })).toBeVisible();

        const railroadPlaylist = page.getByRole("button", { name: /Scan playlist Railroad/i });
        await railroadPlaylist.click();
        await expect(page.getByText(/SCAN MODE|Austin Area Railroads/i).first()).toBeVisible();
      }

      await page.setViewportSize({ width: 430, height: 820 });
      await expect(page.getByRole("heading", { name: "Bearcat Scan Lists" })).toBeVisible();
      await expect(page.getByText("Live Screen")).toBeVisible();
      await expect(page.getByText(/^Department\s*$/)).toBeVisible();
      await expect(page.getByText("Front Panel")).toHaveCount(0);
    } finally {
      await app.close();
    }
  });
});
