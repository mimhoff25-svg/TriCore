const { spawn } = require("node:child_process");
const fs = require("node:fs");
const http = require("node:http");
const path = require("node:path");
const { app, BrowserWindow, Menu } = require("electron");

const FRONTEND_ROOT = path.resolve(__dirname, "..");
const PROJECT_ROOT = path.resolve(FRONTEND_ROOT, "..");
const BACKEND_ROOT = path.join(PROJECT_ROOT, "backend");
const BACKEND_URL = "http://127.0.0.1:8000";
const DASHBOARD_URL = "http://127.0.0.1:5173";
const APP_ICON_PATH = path.join(FRONTEND_ROOT, "public", "icons", "tricore.ico");
const isDev = process.argv.includes("--dev") || process.env.TRICORE_DESKTOP_DEV === "1";
const isTest = process.env.TRICORE_TEST === "1";
const RTLSDR_DLL_DIRS = [
  path.join(PROJECT_ROOT, "tools", "tricore-sdr", "rtl-sdr"),
  path.join(PROJECT_ROOT, "tools", "tricore-sdr", "dsdplus"),
  path.resolve(PROJECT_ROOT, "..", "..", "sdrpp_windows_x64"),
  path.resolve(PROJECT_ROOT, "..", "..", "sdrpp_windows_x64", "sdrpp_windows_x64"),
  path.resolve(PROJECT_ROOT, "..", "..", "sdrpp_windows_x64", "DSDPlus"),
  "C:\\Program Files\\PothosSDR\\bin",
  "C:\\rtl-sdr",
  "C:\\Users\\mimho\\Downloads\\SDRPlusPlus\\sdrpp_windows_x64",
  "C:\\Program Files\\rtl-sdr",
  "C:\\Program Files (x86)\\rtl-sdr",
];

let mainWindow = null;
let backendProcess = null;
const LOG_DIR = path.join(PROJECT_ROOT, "logs");
const BACKEND_STDOUT_LOG = path.join(LOG_DIR, "backend.out.log");
const BACKEND_STDERR_LOG = path.join(LOG_DIR, "backend.err.log");
const ELECTRON_LOG = path.join(LOG_DIR, "electron.log");

const LOCAL_ELECTRON_DATA = path.join(PROJECT_ROOT, ".electron-data");
const LOCAL_USER_DATA = path.join(LOCAL_ELECTRON_DATA, "user-data");
const INSTANCE_ID = String(process.pid);
const LOCAL_CACHE_DATA = path.join(LOCAL_ELECTRON_DATA, "cache", INSTANCE_ID);
const LOCAL_SESSION_DATA = path.join(LOCAL_ELECTRON_DATA, "session", INSTANCE_ID);
const LOCAL_GPU_CACHE = path.join(LOCAL_CACHE_DATA, "gpu");

const gotSingleInstanceLock = app.requestSingleInstanceLock();
if (!gotSingleInstanceLock) {
  app.quit();
  process.exit(0);
}

// Keep Electron runtime data inside the project workspace to avoid
// machine-specific profile permission issues that can crash the face UI.
for (const dir of [LOCAL_ELECTRON_DATA, LOCAL_USER_DATA, LOCAL_CACHE_DATA, LOCAL_SESSION_DATA, LOCAL_GPU_CACHE]) {
  try {
    fs.mkdirSync(dir, { recursive: true });
  } catch {
    // Fall back to Electron defaults when local data paths cannot be set.
  }
}

try {
  app.setPath("userData", LOCAL_USER_DATA);
} catch {
  // Fall back to Electron defaults when this path key is unavailable.
}
try {
  app.setPath("cache", LOCAL_CACHE_DATA);
} catch {
  // Fall back to Electron defaults when this path key is unavailable.
}
try {
  app.setPath("sessionData", LOCAL_SESSION_DATA);
} catch {
  // Electron builds that do not expose sessionData will use defaults.
}

app.commandLine.appendSwitch("disk-cache-dir", LOCAL_CACHE_DATA);
app.commandLine.appendSwitch("gpu-disk-cache-dir", LOCAL_GPU_CACHE);
app.commandLine.appendSwitch("media-cache-size", "0");

function appendLog(file, message) {
  try {
    fs.mkdirSync(LOG_DIR, { recursive: true });
    fs.appendFileSync(file, `${new Date().toISOString()} ${message}\n`);
  } catch {
    // Last-resort logging must never crash the app.
  }
}

function backendEnvironment() {
  const env = { ...process.env };
  const pathKey = Object.keys(env).find((key) => key.toLowerCase() === "path") || "PATH";
  const rtlPaths = RTLSDR_DLL_DIRS.filter(
    (dir) => fs.existsSync(path.join(dir, "rtlsdr.dll")) || fs.existsSync(path.join(dir, "rtl_fm.exe")),
  );

  if (rtlPaths.length > 0) {
    env[pathKey] = `${rtlPaths.join(path.delimiter)}${path.delimiter}${env[pathKey] || ""}`;
  }

  return env;
}

function backendPythonCommand() {
  const venvPython = path.join(BACKEND_ROOT, ".venv", "Scripts", "python.exe");
  if (fs.existsSync(venvPython)) {
    return { command: venvPython, args: ["-m", "uvicorn", "backend.app:app", "--host", "127.0.0.1", "--port", "8000"] };
  }

  // Fallback to launcher-based discovery for systems where venv was moved.
  return { command: "py", args: ["-3", "-m", "uvicorn", "backend.app:app", "--host", "127.0.0.1", "--port", "8000"] };
}

function waitForBackend(timeoutMs = 12000) {
  const started = Date.now();

  return new Promise((resolve, reject) => {
    function check() {
      const request = http.get(`${BACKEND_URL}/api/status`, (response) => {
        response.resume();
        if (response.statusCode && response.statusCode >= 200 && response.statusCode < 300) {
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

function isBackendAlive() {
  return new Promise((resolve) => {
    const request = http.get(`${BACKEND_URL}/api/status`, (response) => {
      response.resume();
      resolve(Boolean(response.statusCode && response.statusCode >= 200 && response.statusCode < 300));
    });
    request.on("error", () => resolve(false));
    request.setTimeout(800, () => {
      request.destroy();
      resolve(false);
    });
  });
}

async function startBackend() {
  if (await isBackendAlive()) {
    appendLog(ELECTRON_LOG, "Reusing existing TriCore backend on port 8000.");
    return;
  }

  const pythonCommand = backendPythonCommand();
  fs.mkdirSync(LOG_DIR, { recursive: true });
  const out = fs.openSync(BACKEND_STDOUT_LOG, "a");
  const err = fs.openSync(BACKEND_STDERR_LOG, "a");

  backendProcess = spawn(
    pythonCommand.command,
    pythonCommand.args,
    {
      cwd: PROJECT_ROOT,
      env: backendEnvironment(),
      windowsHide: true,
      stdio: isTest ? "pipe" : ["ignore", out, err],
    },
  );
  appendLog(ELECTRON_LOG, `Started backend pid=${backendProcess.pid} using ${pythonCommand.command}.`);

  backendProcess.on("error", (error) => {
    appendLog(ELECTRON_LOG, `Backend spawn error: ${error.message}`);
  });

  backendProcess.on("exit", (code, signal) => {
    appendLog(ELECTRON_LOG, `Backend exited code=${code} signal=${signal}.`);
    backendProcess = null;
  });
}

function createMainWindow() {
  const iconPath = fs.existsSync(APP_ICON_PATH) ? APP_ICON_PATH : undefined;

  mainWindow = new BrowserWindow({
    width: 1440,
    height: 920,
    minWidth: isTest ? 390 : 1100,
    minHeight: isTest ? 640 : 720,
    backgroundColor: "#090d13",
    title: "TriCore Scanner",
    icon: iconPath,
    autoHideMenuBar: true,
    show: false,
    webPreferences: { contextIsolation: true, nodeIntegration: false, webSecurity: true },
  });

  Menu.setApplicationMenu(null);

  mainWindow.webContents.on("console-message", (_e, level, msg, line, src) => {
    appendLog(ELECTRON_LOG, `[renderer L${level}] ${msg} (${src}:${line})`);
  });

  mainWindow.once("ready-to-show", () => {
    mainWindow.show();
    if (isDev || isTest) {
      mainWindow.webContents.openDevTools({ mode: "detach" });
    }
  });

  if (isDev) {
    mainWindow.loadURL(DASHBOARD_URL);
    mainWindow.webContents.on("did-fail-load", () => {
      setTimeout(() => mainWindow && mainWindow.loadURL(DASHBOARD_URL), 1500);
    });
  } else {
    mainWindow.loadFile(path.join(FRONTEND_ROOT, "dist", "index.html"));
  }

  mainWindow.webContents.on("render-process-gone", (_event, details) => {
    appendLog(ELECTRON_LOG, `Renderer gone reason=${details.reason} exitCode=${details.exitCode}. Reloading UI.`);
    if (mainWindow && !mainWindow.isDestroyed()) {
      setTimeout(() => {
        if (mainWindow && !mainWindow.isDestroyed()) {
          if (isDev) mainWindow.loadURL(DASHBOARD_URL);
          else mainWindow.loadFile(path.join(FRONTEND_ROOT, "dist", "index.html"));
        }
      }, 500);
    }
  });

  mainWindow.webContents.on("unresponsive", () => {
    appendLog(ELECTRON_LOG, "Renderer became unresponsive.");
  });

  mainWindow.on("closed", () => {
    mainWindow = null;
  });
}

app.whenReady().then(async () => {
  if (process.platform === "win32") {
    app.setAppUserModelId("com.tricore.scanner");
  }

  await startBackend();
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

app.on("second-instance", () => {
  if (mainWindow && !mainWindow.isDestroyed()) {
    if (mainWindow.isMinimized()) {
      mainWindow.restore();
    }
    mainWindow.focus();
  }
});

process.on("uncaughtException", (error) => {
  appendLog(ELECTRON_LOG, `Uncaught exception: ${error.stack || error.message}`);
});

process.on("unhandledRejection", (reason) => {
  appendLog(ELECTRON_LOG, `Unhandled rejection: ${reason && reason.stack ? reason.stack : reason}`);
});

app.on("before-quit", () => {
  if (backendProcess) {
    backendProcess.kill();
    backendProcess = null;
  }
});

app.on("window-all-closed", () => {
  if (process.platform !== "darwin") app.quit();
});
