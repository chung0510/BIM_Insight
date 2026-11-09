import { spawn } from "node:child_process";
import { existsSync } from "node:fs";
import { realpath, rm } from "node:fs/promises";
import { dirname, resolve, relative } from "node:path";
import { randomUUID } from "node:crypto";
import { createInterface } from "node:readline";
import { createServer, preview } from "vite";

const python = resolve(
  process.platform === "win32"
    ? ".venv/Scripts/python.exe"
    : ".venv/bin/python",
);
if (!existsSync(python))
  throw new Error("Create the backend .venv using the README setup first.");
const sessionId = `session-${process.pid}-${randomUUID()}`;
const backend = spawn(
  python,
  ["-m", "app", "--desktop", "--parent-pid", String(process.pid)],
  {
    windowsHide: true,
    stdio: ["ignore", "pipe", "inherit"],
    env: {
      ...process.env,
      BIM_DATA_DIR: resolve(process.env.BIM_DATA_DIR || "data/inspections"),
      BIM_SESSION_ID: sessionId,
    },
  },
);
let server;
let closing = false;
const directory = resolve(process.env.BIM_DATA_DIR || "data/inspections");
async function close(code = 0) {
  if (closing) return;
  closing = true;
  if (backend.exitCode === null && backend.signalCode === null) {
    if (process.platform === "win32") {
      const kill = spawn(
        "taskkill",
        ["/PID", String(backend.pid), "/T", "/F"],
        { windowsHide: true, stdio: "ignore" },
      );
      await new Promise((done) => kill.once("exit", done));
    } else backend.kill();
  }
  try {
    const base = await realpath(directory);
    const temporary = await realpath(resolve(directory, "tmp"));
    const target = await realpath(resolve(temporary, sessionId));
    if (
      relative(base, temporary).toLowerCase() === "tmp" &&
      dirname(target) === temporary &&
      relative(temporary, target) === sessionId
    ) {
      await rm(target, {
        recursive: true,
        force: true,
        maxRetries: 10,
        retryDelay: 100,
      });
    }
  } catch (error) {
    if (error.code !== "ENOENT")
      console.warn(
        "Inspection temporary data will be recovered on next start.",
      );
  }
  if (server?.close) await server.close();
  else if (server) await new Promise((done) => server.httpServer.close(done));
  process.exit(code);
}
process.on("SIGINT", () => close());
process.on("SIGTERM", () => close());
backend.on("error", (error) => {
  console.error(error.message);
  close(1);
});
backend.on("exit", () => {
  if (!closing) {
    console.error("Local processor stopped.");
    close(1);
  }
});
const lines = createInterface({ input: backend.stdout });
const startupTimeout = setTimeout(() => {
  console.error("Local processor startup timed out.");
  close(1);
}, 15000);
try {
  const connection = await new Promise((done, reject) => {
    lines.once("line", (line) => {
      try {
        done(JSON.parse(line));
      } catch {
        reject(new Error("Invalid local processor response"));
      }
    });
    lines.once("close", () =>
      reject(new Error("Local processor did not start")),
    );
  });
  clearTimeout(startupTimeout);
  if (
    !/^http:\/\/127\.0\.0\.1:\d+$/.test(connection.base_url) ||
    connection.token.length < 32
  )
    throw new Error("Invalid processor connection");
  process.env.BIM_BACKEND_URL = connection.base_url;
  process.env.BIM_API_TOKEN = connection.token;
  const config = { root: resolve("frontend"), configFile: resolve("frontend/vite.config.ts") };
  if (process.argv.includes("--preview")) {
    server = await preview({ ...config, preview: { host: "127.0.0.1", port: 1420, strictPort: true } });
  } else {
    server = await createServer({ ...config, server: { host: "127.0.0.1" } });
    await server.listen();
  }
  console.log("IFC/PDF/CAD processor ready on this device.");
  server.printUrls();
} catch (error) {
  clearTimeout(startupTimeout);
  console.error(error.message);
  await close(1);
}
