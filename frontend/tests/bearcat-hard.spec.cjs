const { test, expect, _electron: electron } = require("@playwright/test");
const path = require("node:path");

const API_BASE = "http://127.0.0.1:8000";

async function api(request, endpoint, method = "GET", data = undefined) {
  const response = await request.fetch(`${API_BASE}${endpoint}`, {
    method,
    data,
  });
  if (!response.ok()) {
    const body = await response.text();
    throw new Error(`${method} ${endpoint} failed: ${response.status()} ${body}`);
  }
  return response.json();
}

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

async function waitForScannerState(request) {
  await expect
    .poll(async () => {
      const status = await api(request, "/api/status");
      return status.state || "";
    }, { timeout: 15000 })
    .toMatch(/SCANNING|RECEIVING_CALL|HOLDING_CHANNEL/);
}

test.describe("Bearcat hard test", () => {
  test.setTimeout(180000);

  test("scanner stress + APD playlist flow", async ({ request }) => {
    const { app, page } = await launchApp();

    try {
      await expect(page.getByRole("heading", { name: "Bearcat Scan Lists" })).toBeVisible();

      await api(request, "/api/sdr/runtime/sync", "POST");
      await api(request, "/api/p25/sync-playlist", "POST");

      for (let i = 0; i < 3; i += 1) {
        await api(request, "/api/scanner/start", "POST");
        await api(request, "/api/scanner/hold", "POST");
        await expect
          .poll(async () => {
            const status = await api(request, "/api/status");
            return Boolean(status.held);
          }, { timeout: 12000 })
          .toBe(true);

        await api(request, "/api/scanner/clear-hold", "POST");
        await expect
          .poll(async () => {
            const status = await api(request, "/api/status");
            return Boolean(status.held);
          }, { timeout: 12000 })
          .toBe(false);

        await api(request, "/api/scanner/skip", "POST");
      }

      const filterInput = page.getByPlaceholder("Filter channels, systems, talkgroups");
      await expect(page.getByRole("button", { name: /Scan playlist Railroad/i })).toBeVisible();
      await page.getByRole("button", { name: /Scan playlist Railroad/i }).click();
      await waitForScannerState(request);

      await page.getByRole("button", { name: /^Stay Here$/i }).click();

      await expect
        .poll(async () => {
          const status = await api(request, "/api/status");
          return Boolean(status.held && status.active_channel?.name);
        }, { timeout: 15000 })
        .toBe(true);

      await page.getByRole("button", { name: /^Resume$/i }).click();
      await expect
        .poll(async () => {
          const status = await api(request, "/api/status");
          return Boolean(status.held);
        }, { timeout: 15000 })
        .toBe(false);

      await filterInput.fill("__no_match_hard_test__");
      await expect(page.getByText(/No matches for/i)).toBeVisible();
      await page.getByRole("button", { name: /Clear filter/i }).click();

      const allTalkgroups = await api(request, "/api/trunked/talkgroups?include_encrypted=true");
      const apdTalkgroups = allTalkgroups.filter((tg) => {
        const alpha = String(tg.alpha_tag || "").toLowerCase();
        const tag = String(tg.tag || "").toLowerCase();
        return alpha.includes("apd") || tag.includes("austin police");
      });

      await filterInput.fill("APD");

      if (apdTalkgroups.length > 0) {
        await expect(page.getByRole("button", { name: /Scan APD stations/i })).toBeVisible({ timeout: 15000 });
        await page.getByRole("button", { name: /Scan APD stations/i }).click();
      } else {
        const clearTalkgroup = allTalkgroups.find((tg) => !tg.encrypted);
        if (!clearTalkgroup) {
          throw new Error("No clear talkgroups available for P25 validation");
        }
        await api(request, "/api/p25/start", "POST");
        await api(request, "/api/p25/select-talkgroup", "POST", {
          talkgroup: clearTalkgroup,
        });
      }

      await expect
        .poll(async () => {
          const p25 = await api(request, "/api/p25/status");
          const selectedDecimal = Number(
            p25.selected_talkgroup?.decimal
              || p25.active_call?.talkgroup?.decimal
              || p25.active_call?.talkgroup
              || 0,
          );
          return {
            running: Boolean(p25.running),
            hasSelection: Boolean(selectedDecimal),
            isApdOrFallback: apdTalkgroups.length > 0
              ? apdTalkgroups.some((tg) => Number(tg.decimal) === selectedDecimal)
              : true,
          };
        }, { timeout: 25000 })
        .toEqual({
          running: true,
          hasSelection: true,
          isApdOrFallback: true,
        });

      if (apdTalkgroups.length > 0) {
        await expect(page.getByText("APD Stations")).toBeVisible();
      }

      const importButton = page.getByRole("button", { name: /Import SDRTrunk|Importing\.\.\.|Sync Playlist|Syncing\.\.\./i });
      if (await importButton.isVisible().catch(() => false)) {
        await importButton.click();
      }

      await expect
        .poll(async () => {
          const p25 = await api(request, "/api/p25/status");
          return p25.message || "";
        }, { timeout: 15000 })
        .not.toEqual("");
    } finally {
      await app.close();
    }
  });
});
