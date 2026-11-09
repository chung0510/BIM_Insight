import { spawnSync } from "node:child_process";
import { existsSync, mkdirSync } from "node:fs";
import { resolve, relative } from "node:path";

if (process.platform !== "win32")
  throw new Error("The current desktop bundle targets Windows x64.");
const root = resolve(".");
const destination = resolve("src-tauri/binaries");
if (relative(root, destination).startsWith(".."))
  throw new Error("Build output must stay inside the workspace");
mkdirSync(destination, { recursive: true });
const python = resolve(".venv/Scripts/python.exe");
if (!existsSync(python))
  throw new Error("Install backend[dev] in .venv before building.");
const result = spawnSync(
  python,
  [
    "-m",
    "PyInstaller",
    "--noconfirm",
    "--distpath",
    destination,
    "--workpath",
    resolve("data/build/pyinstaller"),
    "backend/bim_backend.spec",
  ],
  { stdio: "inherit", windowsHide: true },
);
if (result.error) throw result.error;
if (result.status !== 0) process.exit(result.status ?? 1);
if (!existsSync(resolve(destination, "bim_backend/bim_backend.exe")))
  throw new Error("Processor executable was not produced");
