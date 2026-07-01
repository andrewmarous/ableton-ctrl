import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import { StringEnum } from "@earendil-works/pi-ai";
import { Type, type Static } from "typebox";
import { execFile } from "node:child_process";

const abletonCtrlSchema = Type.Object({
  action: StringEnum(["snapshot", "object", "children", "search", "schema", "changes", "resource"] as const, {
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
}, { additionalProperties: false });

export type AbletonCtrlInput = Static<typeof abletonCtrlSchema>;

function runAbletonCtrl(params: AbletonCtrlInput, signal?: AbortSignal): Promise<string> {
  return new Promise((resolve, reject) => {
    const child = execFile(
      "ableton-ctrl",
      [JSON.stringify(params)],
      { encoding: "utf8", signal },
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

export default function (pi: ExtensionAPI) {
  pi.registerTool({
    name: "ableton_ctrl",
    label: "Ableton Ctrl",
    description: "Read-only inspection of an Ableton Live Set through the installed ableton-ctrl CLI.",
    promptSnippet: "Inspect Ableton Live Sets using the read-only ableton-ctrl CLI bridge.",
    promptGuidelines: [
      "Use ableton_ctrl for read-only Ableton Live Set inspection tasks; never use it to mutate Live.",
      "Pass structured fields directly to ableton_ctrl; the extension shells out to ableton-ctrl with one JSON argument.",
    ],
    parameters: abletonCtrlSchema,
    async execute(_toolCallId, params, signal) {
      const jsonText = await runAbletonCtrl(params, signal);
      const parsed = JSON.parse(jsonText);
      return {
        content: [{ type: "text", text: jsonText }],
        details: parsed,
      };
    },
  });
}
