import { execFile, spawn, type ChildProcess } from "node:child_process";
import { randomUUID } from "node:crypto";
import { readFile } from "node:fs/promises";
import { homedir } from "node:os";
import { join } from "node:path";

export type BridgeState =
  | "off"
  | "starting"
  | "waiting"
  | "discovering"
  | "ready"
  | "partial"
  | "external"
  | "error";

export type ControllerStatus = {
  enabled: boolean;
  state: BridgeState;
  ownership: "none" | "owned" | "external";
  instanceId?: string;
  bridge?: unknown;
  diagnostics?: string[];
};

type Probe = () => Promise<Record<string, unknown>>;
type SpawnBridge = (executable: string, args: string[]) => ChildProcess;

export type ControllerOptions = {
  probe?: Probe;
  spawnBridge?: SpawnBridge;
  resolveExecutable?: () => Promise<string>;
  startupTimeoutMs?: number;
  stopTimeoutMs?: number;
  pollIntervalMs?: number;
};

const MAX_DIAGNOSTIC_LINES = 40;
const MAX_DIAGNOSTIC_CHARS = 8_000;
const ALLOWED_WHILE_OFF = new Set(["resource", "status", "doctor"]);

function delay(milliseconds: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, milliseconds));
}

function defaultProbe(): Promise<Record<string, unknown>> {
  return new Promise((resolve, reject) => {
    execFile(
      "ableton-ctrl",
      [JSON.stringify({ action: "status" })],
      { encoding: "utf8", maxBuffer: 1024 * 1024 },
      (error, stdout) => {
        if (error && !stdout.trim()) return reject(error);
        try {
          resolve(JSON.parse(stdout));
        } catch (parseError) {
          reject(parseError);
        }
      },
    );
  });
}

async function defaultResolveExecutable(): Promise<string> {
  const configPath = join(
    homedir(),
    "Library",
    "Application Support",
    "ableton-ctrl",
    "config.json",
  );
  try {
    const parsed = JSON.parse(await readFile(configPath, "utf8"));
    if (typeof parsed.bridge_executable === "string" && parsed.bridge_executable.length > 0) {
      return parsed.bridge_executable;
    }
  } catch {
    // The installed executable name is resolved by the child's PATH.
  }
  return "ableton-ctrl-bridge";
}

function defaultSpawnBridge(executable: string, args: string[]): ChildProcess {
  return spawn(executable, args, {
    shell: false,
    detached: false,
    stdio: ["ignore", "pipe", "pipe", "pipe"],
  });
}

function responseIsAuthenticated(response: Record<string, unknown>): boolean {
  if (response.ok === true) return true;
  const error = response.error;
  return !(
    typeof error === "object" &&
    error !== null &&
    ["bridge_unavailable", "authentication_failed"].includes(
      String((error as Record<string, unknown>).code),
    )
  );
}

export class AbletonBridgeController {
  private enabled = false;
  private currentState: BridgeState = "off";
  private externalBridgeActive = false;
  private child?: ChildProcess;
  private supervision?: NodeJS.WritableStream;
  private instanceId?: string;
  private operation: Promise<unknown> = Promise.resolve();
  private pending = new Set<AbortController>();
  private diagnostics: string[] = [];
  private readonly probe: Probe;
  private readonly spawnBridge: SpawnBridge;
  private readonly resolveExecutable: () => Promise<string>;
  private readonly startupTimeoutMs: number;
  private readonly stopTimeoutMs: number;
  private readonly pollIntervalMs: number;

  constructor(options: ControllerOptions = {}) {
    this.probe = options.probe ?? defaultProbe;
    this.spawnBridge = options.spawnBridge ?? defaultSpawnBridge;
    this.resolveExecutable = options.resolveExecutable ?? defaultResolveExecutable;
    this.startupTimeoutMs = options.startupTimeoutMs ?? 5_000;
    this.stopTimeoutMs = options.stopTimeoutMs ?? 2_000;
    this.pollIntervalMs = options.pollIntervalMs ?? 100;
  }

  status(): ControllerStatus {
    const ownership = this.child ? "owned" : this.enabled ? "external" : "none";
    return {
      enabled: this.enabled,
      state: this.currentState,
      ownership,
      instanceId: this.instanceId,
      diagnostics: [...this.diagnostics],
    };
  }

  on(): Promise<ControllerStatus> {
    return this.serialize(() => this.start());
  }

  off(): Promise<ControllerStatus> {
    this.enabled = false;
    this.currentState = "off";
    for (const controller of this.pending) controller.abort();
    this.pending.clear();
    return this.serialize(() => this.stopOwned());
  }

  shutdown(): Promise<ControllerStatus> {
    return this.off();
  }

  async runInspection<T>(action: string, run: (signal: AbortSignal) => Promise<T>): Promise<T> {
    if (!this.enabled && !ALLOWED_WHILE_OFF.has(action)) {
      return {
        protocol_version: 1,
        ok: false,
        completeness: "unavailable",
        error: {
          code: "integration_disabled",
          message: "Ableton inspection is disabled for this Pi session.",
          recovery: { action: "run_ableton_on" },
        },
      } as T;
    }
    const cancellation = new AbortController();
    this.pending.add(cancellation);
    try {
      return await run(cancellation.signal);
    } finally {
      this.pending.delete(cancellation);
    }
  }

  private serialize<T>(work: () => Promise<T>): Promise<T> {
    const result = this.operation.then(work, work);
    this.operation = result.then(() => undefined, () => undefined);
    return result;
  }

  private async start(): Promise<ControllerStatus> {
    if (this.enabled) return this.status();
    this.currentState = "starting";
    try {
      const existing = await this.probe();
      if (responseIsAuthenticated(existing)) {
        this.enabled = true;
        this.externalBridgeActive = true;
        this.currentState = "external";
        return this.status();
      }
    } catch {
      // A stopped bridge is the expected path to managed startup.
    }

    const executable = await this.resolveExecutable();
    const instanceId = randomUUID();
    const child = this.spawnBridge(executable, [
      "--instance-id",
      instanceId,
      "--supervision-fd",
      "3",
    ]);
    this.child = child;
    this.externalBridgeActive = false;
    this.instanceId = instanceId;
    this.supervision = child.stdio?.[3] as NodeJS.WritableStream | undefined;
    this.capture(child.stdout);
    this.capture(child.stderr);
    child.once("exit", () => {
      if (this.child === child) {
        this.child = undefined;
        this.supervision = undefined;
        this.enabled = false;
        this.currentState = "error";
      }
    });

    const deadline = Date.now() + this.startupTimeoutMs;
    try {
      while (Date.now() < deadline) {
        if (child.exitCode !== null) throw new Error(`bridge exited with ${child.exitCode}`);
        try {
          const response = await this.probe();
          if (responseIsAuthenticated(response)) {
            this.enabled = true;
            this.currentState = this.classify(response);
            return this.status();
          }
          const code = (response.error as Record<string, unknown> | undefined)?.code;
          if (code === "authentication_failed") throw new Error("bridge authentication failed");
        } catch (error) {
          if (String(error).includes("authentication")) throw error;
        }
        await delay(this.pollIntervalMs);
      }
      throw new Error("bridge readiness timed out");
    } catch (error) {
      await this.terminate(child);
      if (this.child === child) this.child = undefined;
      this.enabled = false;
      this.currentState = "error";
      this.recordDiagnostic(String(error));
      throw error;
    }
  }

  private async stopOwned(): Promise<ControllerStatus> {
    const child = this.child;
    if (!child) {
      if (this.externalBridgeActive) {
        this.recordDiagnostic("External bridge remains active; it is not owned by this Pi session.");
      }
      this.externalBridgeActive = false;
      this.instanceId = undefined;
      return this.status();
    }
    await this.terminate(child);
    if (this.child === child) this.child = undefined;
    this.supervision = undefined;
    this.instanceId = undefined;
    this.currentState = "off";
    return this.status();
  }

  private classify(response: Record<string, unknown>): BridgeState {
    const result = response.result as Record<string, unknown> | undefined;
    if (result?.live_connected !== true) return "waiting";
    if (result.completeness === "partial") return "discovering";
    return "ready";
  }

  private async terminate(child: ChildProcess): Promise<void> {
    this.supervision?.end();
    if (child.exitCode !== null) return;
    const exited = new Promise<boolean>((resolve) => child.once("exit", () => resolve(true)));
    child.kill("SIGTERM");
    if (await Promise.race([exited, delay(this.stopTimeoutMs).then(() => false)])) return;
    if (this.child === child && child.exitCode === null) child.kill("SIGKILL");
    await Promise.race([exited, delay(this.stopTimeoutMs)]);
  }

  private capture(stream: NodeJS.ReadableStream | null | undefined): void {
    stream?.on("data", (chunk) => {
      for (const line of String(chunk).split(/\r?\n/).filter(Boolean)) {
        this.recordDiagnostic(line.replace(/"secret"\s*:\s*"[^"]+"/gi, '"secret":"[redacted]"'));
      }
    });
  }

  private recordDiagnostic(line: string): void {
    this.diagnostics.push(line.slice(0, MAX_DIAGNOSTIC_CHARS));
    if (this.diagnostics.length > MAX_DIAGNOSTIC_LINES) this.diagnostics.shift();
  }
}
