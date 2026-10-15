const assert = require("node:assert/strict");
const crypto = require("node:crypto");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const elements = new Map();
const document = {
  getElementById(id) {
    if (!elements.has(id)) {
      elements.set(id, { value: "", textContent: "", disabled: false, addEventListener() {} });
    }
    return elements.get(id);
  }
};
const state = { selfindexEndpoint: "http://127.0.0.1:5050/api/ingest/browser-conversation" };
const context = vm.createContext({
  document,
  chrome: {
    tabs: { query: async () => [] },
    storage: { local: { get: async () => state, set: async (value) => Object.assign(state, value) } }
  },
  crypto: crypto.webcrypto,
  TextEncoder,
  URL,
  AbortController,
  setTimeout,
  clearTimeout,
  fetch: async () => ({ ok: true, json: async () => ({ service: "selfindex", profile_id: "a".repeat(32) }) })
});
const popupPath = path.join(__dirname, "..", "browser_capture", "ai_capture_extension", "popup.js");
vm.runInContext(fs.readFileSync(popupPath, "utf8"), context, { filename: popupPath });

async function main() {
  const firstProfile = "a".repeat(32);
  const secondProfile = "b".repeat(32);
  assert.notEqual(
    context.getConversationSyncKey(firstProfile, "chatgpt", "same-conversation"),
    context.getConversationSyncKey(secondProfile, "chatgpt", "same-conversation")
  );

  const messages = [
    { message_id: "old", role: "user", content: "original" },
    { message_id: "anchor", role: "assistant", content: "answer" }
  ];
  const payload = { platform: "chatgpt", conversation_id: "one", messages };
  const fingerprints = await context.fingerprintMessages(messages);
  assert.equal(context.buildSyncPlan(payload, null, fingerprints).mode, "initial");
  const synced = { last_message_id: "anchor", message_hashes: fingerprints };
  assert.equal(context.buildSyncPlan(payload, synced, fingerprints).mode, "up_to_date");

  const changed = { ...payload, messages: [{ ...messages[0], content: "edited" }, messages[1]] };
  const changedHashes = await context.fingerprintMessages(changed.messages);
  const changedPlan = context.buildSyncPlan(changed, synced, changedHashes);
  assert.equal(changedPlan.mode, "resync");
  assert.equal(changedPlan.payload.messages.length, 2);
  assert.equal(context.buildSyncPlan(payload, { last_message_id: "anchor" }, fingerprints).mode, "resync");

  const grown = { ...payload, messages: [...messages, { message_id: "new", role: "user", content: "next" }] };
  const grownPlan = context.buildSyncPlan(grown, synced, await context.fingerprintMessages(grown.messages));
  assert.equal(grownPlan.mode, "incremental");
  assert.equal(grownPlan.payload.messages.length, 1);
  assert.equal(grownPlan.payload.messages[0].message_id, "new");

  const profileId = await context.fetchProfileId();
  assert.equal(profileId, firstProfile);
  elements.get("endpoint-input").value = "https://example.com/ingest";
  await assert.rejects(context.fetchProfileId(), /本机/);
}

main().catch((error) => {
  process.stderr.write(`${error.stack || error}\n`);
  process.exitCode = 1;
});
