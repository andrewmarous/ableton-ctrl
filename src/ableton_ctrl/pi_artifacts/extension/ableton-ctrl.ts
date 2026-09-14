import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import {
  DEFAULT_MAX_BYTES,
  DEFAULT_MAX_LINES,
  formatSize,
  truncateHead,
} from "@earendil-works/pi-coding-agent";
import { StringEnum } from "@earendil-works/pi-ai";
import { Type, type Static } from "typebox";
import { execFile } from "node:child_process";
import { mkdtemp, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { AbletonBridgeController, type ControllerStatus } from "./ableton-controller.ts";

const MAX_CLI_BUFFER_BYTES = 2 * 1024 * 1024;

const abletonCtrlSchema = Type.Object({
  action: StringEnum(["status", "doctor", "snapshot", "object", "children", "search", "schema", "changes", "project_summary", "track_summary", "device_tree", "selection", "project_diff", "clip_notes", "resource"] as const, {
    description: "Ableton inspection action to run through the ableton-ctrl CLI.",
  }),
  depth: Type.Optional(Type.Number({ minimum: 0, maximum: 8 })),
  page_size: Type.Optional(Type.Number({ minimum: 1, maximum: 200 })),
  object_id: Type.Optional(Type.String()),
  relationship: Type.Optional(Type.String()),
  revision: Type.Optional(Type.Number({ minimum: 1 })),
  offset: Type.Optional(Type.Number({ minimum: 0 })),
  limit: Type.Optional(Type.Number({ minimum: 1, maximum: 500 })),
  start_index: Type.Optional(Type.Number({ minimum: 0 })),
  name: Type.Optional(Type.String()),
  object_type: Type.Optional(Type.String()),
  path: Type.Optional(Type.String()),
  session_id: Type.Optional(Type.String()),
  after_revision: Type.Optional(Type.Number({ minimum: 0 })),
  from_beat: Type.Optional(Type.Number()),
  beat_span: Type.Optional(Type.Number({ exclusiveMinimum: 0, maximum: 256 })),
  from_pitch: Type.Optional(Type.Number({ minimum: 0, maximum: 127 })),
  pitch_span: Type.Optional(Type.Number({ minimum: 1, maximum: 128 })),
  note_limit: Type.Optional(Type.Number({ minimum: 1, maximum: 1000 })),
  deadline_ms: Type.Optional(Type.Number({ minimum: 100, maximum: 5000 })),
}, { additionalProperties: false });

export type AbletonCtrlInput = Static<typeof abletonCtrlSchema>;

function runAbletonCtrl(params: AbletonCtrlInput, signal?: AbortSignal): Promise<string> {
  return new Promise((resolve, reject) => {
    const child = execFile(
      "ableton-ctrl",
      [JSON.stringify(params)],
      { encoding: "utf8", signal, maxBuffer: MAX_CLI_BUFFER_BYTES },
      (error, stdout, stderr) => {
        const output = stdout.trim();
        if (error && output.length === 0) {
          reject(new Error(stderr.trim() || error.message));
          return;
        }
        resolve(output);
      },
    );
    child.stdin?.end();
  });
}

async function truncatedToolContent(jsonText: string): Promise<string> {
  const truncated = truncateHead(jsonText, {
    maxLines: DEFAULT_MAX_LINES,
    maxBytes: DEFAULT_MAX_BYTES,
  });
  if (!truncated.truncated) return jsonText;

  let savedNotice = "Parsed response is available in tool details.";
  try {
    const directory = await mkdtemp(join(tmpdir(), "ableton-ctrl-"));
    const fullOutputPath = join(directory, "response.json");
    await writeFile(fullOutputPath, jsonText, "utf8");
    savedNotice = `Full JSON saved to: ${fullOutputPath}. Parsed response is also available in tool details.`;
  } catch {
    savedNotice = "Full JSON could not be saved, but parsed response is available in tool details.";
  }

  return `${truncated.content}\n\n[ableton_ctrl output truncated: ${truncated.outputLines} of ${truncated.totalLines} lines (${formatSize(truncated.outputBytes)} of ${formatSize(truncated.totalBytes)}). ${savedNotice}]`;
}

export default function (pi: ExtensionAPI) {
  const controller = new AbletonBridgeController();
  let lastContext: { ui: { setStatus(key: string, value: string | undefined): void } } | undefined;

  function statusText(status: ControllerStatus): string {
    if (!status.enabled) return "Ableton: off";
    if (status.ownership === "external") return "Ableton: external bridge";
    if (status.state === "partial") return "Ableton: on · partial/stale";
    if (status.state === "discovering") return "Ableton: on · discovering";
    if (status.state === "waiting") return "Ableton: on · waiting for Live";
    return "Ableton: on · read-only";
  }

  function updateStatus(status = controller.status()): ControllerStatus {
    lastContext?.ui.setStatus("ableton-ctrl", statusText(status));
    return status;
  }

  pi.registerCommand("ableton", {
    description: "Start, stop, or diagnose the read-only Ableton bridge",
    getArgumentCompletions: (prefix: string) =>
      ["on", "off", "status", "doctor"]
        .filter((value) => value.startsWith(prefix))
        .map((value) => ({ value, label: value })),
    handler: async (rawArgs, ctx) => {
      lastContext = ctx;
      let action = rawArgs.trim();
      if (!action) {
        action = await ctx.ui.select("Ableton", ["status", "on", "off", "doctor"]) ?? "status";
      }
      try {
        if (action === "on") {
          ctx.ui.setStatus("ableton-ctrl", "Ableton: starting");
          const status = updateStatus(await controller.on());
          ctx.ui.notify(JSON.stringify(status), "info");
        } else if (action === "off") {
          const status = updateStatus(await controller.off());
          ctx.ui.notify(JSON.stringify(status), "info");
        } else if (action === "status" || action === "doctor") {
          const output = await runAbletonCtrl({ action } as AbletonCtrlInput);
          updateStatus();
          ctx.ui.notify(output, "info");
        } else {
          ctx.ui.notify("Usage: /ableton [on|off|status|doctor]", "error");
        }
      } catch (error) {
        ctx.ui.setStatus("ableton-ctrl", "Ableton: error");
        ctx.ui.notify(String(error), "error");
      }
    },
  });

  pi.on("session_start", async (_event, ctx) => {
    lastContext = ctx;
    updateStatus();
  });
  pi.on("session_shutdown", async () => {
    await controller.shutdown();
    lastContext = undefined;
  });

  pi.registerTool({
    name: "ableton_ctrl",
    label: "Ableton Ctrl",
    description: "Read-only inspection of an Ableton Live Set through the installed ableton-ctrl CLI.",
    promptSnippet: "Inspect Ableton Live Sets using the read-only ableton-ctrl CLI bridge.",
    promptGuidelines: [
      "Use ableton_ctrl for read-only Ableton Live Set inspection tasks; never use it to mutate Live.",
      "Pass structured fields directly to ableton_ctrl; the extension shells out to ableton-ctrl with one JSON argument.",
      "If ableton_ctrl output is truncated, use pagination, narrower searches, or the saved JSON path to inspect details.",
    ],
    parameters: abletonCtrlSchema,
    async execute(_toolCallId, params, signal) {
      const result = await controller.runInspection(params.action, async (ownedSignal) => {
        const combined = AbortSignal.any([signal, ownedSignal]);
        const jsonText = await runAbletonCtrl(params, combined);
        return JSON.parse(jsonText);
      });
      const jsonText = JSON.stringify(result);
      const parsed = JSON.parse(jsonText);
      const contentText = await truncatedToolContent(jsonText);
      return {
        content: [{ type: "text", text: contentText }],
        details: parsed,
      };
    },
  });
}
