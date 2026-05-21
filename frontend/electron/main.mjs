import { spawn } from "node:child_process";
import http from "node:http";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { app, BrowserWindow, Menu } from "electron";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const FRONTEND_ROOT = path.resolve(__dirname, "..");
const PROJECT_ROOT = path.resolve(FRONTEND_ROOT, "..");
const BACKEND_ROOT = path.join(PROJECT_ROOT, "backend");
const BACKEND_URL = "http://127.0.0.1:8000";
const DASHBOARD_URL = "http://127.0.0.1:5173";
const isDev = process.argv.includes("--dev") || process.env.TRICORE_DESKTOP_DEV === "1";
const isTest = process.env.TRICORE_TEST === "1";

let mainWindow = null;
let backendProcess = null;
let allowAppExit = false;
let backendShutdownPromise = null;

function waitForBackend(timeoutMs = 12000) {
  const started = Date.now();

  return new Promise((resolve, reject) => {
    function check() {
      const request = http.get(`${BACKEND_URL}/api/status`, (response) => {
        response.resume();
        if (response.statusCode && response.statusCode < 500) {
          resolve();
        } else {
          retry();
        }
      });

      request.on("error", retry);
      request.setTimeout(1000, () => {
        request.destroy();
        retry();
      });
    }

    function retry() {
      if (Date.now() - started > timeoutMs) {
        reject(new Error("TriCore backend did not start."));
        return;
      }
      setTimeout(check, 300);
    }

    check();
  });
}

function startBackend() {
  const pythonExe = path.join(BACKEND_ROOT, ".venv", "Scripts", "python.exe");

  backendProcess = spawn(
    pythonExe,
    ["-m", "uvicorn", "app:app", "--host", "127.0.0.1", "--port", "8000"],
    {
      cwd: BACKEND_ROOT,
      windowsHide: true,
      stdio: isTest ? "pipe" : "ignore",
    },
  );

  backendProcess.on("exit", () => {
    backendProcess = null;
  });
}

function postToBackend(route, timeoutMs = 1500) {
  return new Promise((resolve) => {
    let settled = false;
    const finish = (value) => {
      if (settled) return;
      settled = true;
      resolve(value);
    };

    const request = http.request(`${BACKEND_URL}${route}`, { method: "POST" }, (response) => {
      response.resume();
      finish(Boolean(response.statusCode && response.statusCode >= 200 && response.statusCode < 300));
    });

    request.on("error", () => finish(false));
    request.setTimeout(timeoutMs, () => {
      request.destroy(new Error("timeout"));
    });
    request.end();
  });
}

function waitForChildExit(childProcess, timeoutMs = 2500) {
  return new Promise((resolve) => {
    if (!childProcess || childProcess.exitCode !== null || childProcess.signalCode !== null) {
      resolve(true);
      return;
    }

    const onExit = () => {
      clearTimeout(timer);
      resolve(true);
    };
    const timer = setTimeout(() => {
      childProcess.off("exit", onExit);
      resolve(false);
    }, timeoutMs);

    childProcess.once("exit", onExit);
  });
}

function killBackendProcessTree(childProcess) {
  if (!childProcess || !childProcess.pid) {
    return Promise.resolve(false);
  }

  if (process.platform === "win32") {
    return new Promise((resolve) => {
      const killer = spawn("taskkill", ["/PID", String(childProcess.pid), "/T", "/F"], {
        windowsHide: true,
        stdio: "ignore",
      });

      killer.on("error", () => {
        try {
          childProcess.kill();
        } catch {
          // Fall through; app exit will still proceed.
        }
        resolve(false);
      });

      killer.on("exit", () => resolve(true));
    });
  }

  try {
    childProcess.kill("SIGTERM");
    return Promise.resolve(true);
  } catch {
    return Promise.resolve(false);
  }
}

async function shutdownBackend() {
  if (backendShutdownPromise) {
    return backendShutdownPromise;
  }

  backendShutdownPromise = (async () => {
    const trackedProcess = backendProcess;
    const requestedShutdown = await postToBackend("/api/system/shutdown");

    if (trackedProcess && requestedShutdown) {
      const exited = await waitForChildExit(trackedProcess);
      if (exited) {
        return;
      }
    }

    if (trackedProcess) {
      await killBackendProcessTree(trackedProcess);
    }
  })().finally(() => {
    backendShutdownPromise = null;
  });

  return backendShutdownPromise;
}

function createMainWindow() {
  mainWindow = new BrowserWindow({
    width: 1440,
    height: 920,
    minWidth: isTest ? 390 : 1100,
    minHeight: isTest ? 640 : 720,
    backgroundColor: "#090d13",
    title: "TriCore Scanner",
    autoHideMenuBar: true,
    show: false,
    webPreferences: { contextIsolation: true, nodeIntegration: false },
  });

  Menu.setApplicationMenu(null);

  mainWindow.once("ready-to-show", () => {
    mainWindow.show();
  });

  if (isDev) {
    mainWindow.loadURL(DASHBOARD_URL);
    mainWindow.webContents.on("did-fail-load", () => {
      setTimeout(() => mainWindow?.loadURL(DASHBOARD_URL), 1500);
    });
  } else {
    mainWindow.loadFile(path.join(FRONTEND_ROOT, "dist", "index.html"));
  }

  mainWindow.on("closed", () => {
    mainWindow = null;
  });
}

app.whenReady().then(async () => {
  startBackend();
  try {
    await waitForBackend();
  } catch {
    // The UI will still show its backend-offline state if startup failed.
  }
  createMainWindow();

  app.on("activate", () => {
    if (BrowserWindow.getAllWindows().length === 0) createMainWindow();
  });
});

app.on("before-quit", (event) => {
  if (allowAppExit) {
    return;
  }

  event.preventDefault();
  shutdownBackend().finally(() => {
    allowAppExit = true;
    app.exit(0);
  });
});

app.on("window-all-closed", () => {
  if (process.platform !== "darwin") app.quit();
});
