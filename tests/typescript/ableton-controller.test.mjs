import assert from "node:assert/strict";
import { EventEmitter } from "node:events";
import test from "node:test";

import { AbletonBridgeController } from "../../src/ableton_ctrl/pi_artifacts/extension/ableton-controller.ts";

function unavailable() {
  return { ok: false, error: { code: "bridge_unavailable" } };
}

function fakeChild() {
  const child = new EventEmitter();
  child.exitCode = null;
  child.stdout = new EventEmitter();
  child.stderr = new EventEmitter();
  child.stdio = [null, child.stdout, child.stderr, { end() {} }];
  child.signals = [];
  child.kill = (signal) => {
    child.signals.push(signal);
    child.exitCode = 0;
    queueMicrotask(() => child.emit("exit", 0, signal));
    return true;
  };
  return child;
}

test("starts at most one managed bridge under concurrent on calls", async () => {
  const child = fakeChild();
  let probes = 0;
  let spawns = 0;
  const controller = new AbletonBridgeController({
    probe: async () => (++probes === 1 ? unavailable() : { ok: true }),
    spawnBridge: (_executable, args) => {
      spawns += 1;
      assert.deepEqual(args.slice(-2), ["--supervision-fd", "3"]);
      return child;
    },
    resolveExecutable: async () => "/trusted/ableton-ctrl-bridge",
    pollIntervalMs: 1,
  });

  const [first, second] = await Promise.all([controller.on(), controller.on()]);
  assert.equal(spawns, 1);
  assert.equal(first.ownership, "owned");
  assert.equal(second.ownership, "owned");
  await controller.off();
  assert.deepEqual(child.signals, ["SIGTERM"]);
});

test("attaches to but never terminates an authenticated external bridge", async () => {
  let spawns = 0;
  const controller = new AbletonBridgeController({
    probe: async () => ({ ok: true }),
    spawnBridge: () => {
      spawns += 1;
      return fakeChild();
    },
  });
  assert.equal((await controller.on()).ownership, "external");
  assert.equal((await controller.off()).ownership, "none");
  assert.equal(spawns, 0);
});

test("does not auto-start for inspection and cancels pending work on off", async () => {
  const controller = new AbletonBridgeController();
  const disabled = await controller.runInspection("snapshot", async () => {
    throw new Error("must not execute");
  });
  assert.equal(disabled.error.code, "integration_disabled");

  const local = await controller.runInspection("resource", async () => ({ ok: true }));
  assert.equal(local.ok, true);
});
