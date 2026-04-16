const captureButton = document.getElementById("capture-btn");
const sendButton = document.getElementById("send-btn");
const copyButton = document.getElementById("copy-btn");
const downloadButton = document.getElementById("download-btn");
const endpointInput = document.getElementById("endpoint-input");
const output = document.getElementById("output");
const summary = document.getElementById("summary");
const syncStatus = document.getElementById("sync-status");

const DEFAULT_ENDPOINT = "http://127.0.0.1:5000/api/ingest/chatgpt-browser";
const SYNC_STATE_KEY = "selfindexConversationSyncState";

let latestPayload = null;
let latestSyncPlan = null;

function setSummary(text) {
  summary.textContent = text;
}

function setSyncStatus(text) {
  syncStatus.textContent = text;
}

function getActiveTab() {
  return chrome.tabs.query({ active: true, currentWindow: true }).then((tabs) => tabs[0]);
}

function sanitizeFilename(value) {
  return String(value || "chatgpt-capture")
    .replace(/[<>:"/\\|?*]+/g, "-")
    .replace(/\s+/g, "-")
    .slice(0, 80);
}

async function loadSettings() {
  const stored = await chrome.storage.local.get(["selfindexEndpoint"]);
  endpointInput.value = stored.selfindexEndpoint || DEFAULT_ENDPOINT;
}

function saveSettings() {
  const endpoint = String(endpointInput.value || "").trim() || DEFAULT_ENDPOINT;
  endpointInput.value = endpoint;
  return chrome.storage.local.set({ selfindexEndpoint: endpoint });
}

async function loadSyncStateMap() {
  const stored = await chrome.storage.local.get([SYNC_STATE_KEY]);
  return stored[SYNC_STATE_KEY] || {};
}

async function getConversationSyncState(conversationId) {
  if (!conversationId) {
    return null;
  }
  const stateMap = await loadSyncStateMap();
  return stateMap[conversationId] || null;
}

async function saveConversationSyncState(payload) {
  const conversationId = payload?.conversation_id;
  const messages = Array.isArray(payload?.messages) ? payload.messages : [];
  if (!conversationId || messages.length === 0) {
    return null;
  }

  const lastMessage = messages[messages.length - 1];
  const stateMap = await loadSyncStateMap();
  const nextState = {
    last_message_id: lastMessage.message_id,
    last_capture_index: lastMessage.capture_index ?? null,
    synced_message_count: messages.length,
    synced_at: new Date().toISOString(),
    conversation_title: payload.conversation_title || null,
    page_url: payload.page_url || null
  };

  stateMap[conversationId] = nextState;
  await chrome.storage.local.set({ [SYNC_STATE_KEY]: stateMap });
  return nextState;
}

async function requestCapture() {
  const tab = await getActiveTab();
  if (!tab || !tab.id) {
    throw new Error("未找到当前标签页。");
  }
  if (!/^https:\/\/(chatgpt\.com|chat\.openai\.com)\//.test(tab.url || "")) {
    throw new Error("请先切到 ChatGPT 对话页面。");
  }

  const response = await chrome.tabs.sendMessage(tab.id, { type: "SELFINDEX_CAPTURE_CHATGPT" });
  if (!response) {
    throw new Error("没有收到页面响应，请刷新 ChatGPT 页面后重试。");
  }
  if (!response.ok) {
    throw new Error(response.error || "抓取失败。");
  }
  return response.payload;
}

function describeSyncPlan(plan, payload, syncState) {
  if (!plan) {
    return "还没有同步计划。";
  }

  if (plan.mode === "empty") {
    return "当前页面没有可同步的消息。";
  }

  if (plan.mode === "initial") {
    return `这是这个会话的首次同步，将写入当前已加载的 ${plan.sync_count} 条消息。`;
  }

  if (plan.mode === "incremental") {
    return `检测到 ${plan.sync_count} 条新增消息，上次同步停在 ${syncState?.last_message_id || "unknown"}。`;
  }

  if (plan.mode === "up_to_date") {
    return `当前会话没有新增消息，最近一次已同步到 ${syncState?.last_message_id || "unknown"}。`;
  }

  if (plan.mode === "resync") {
    return `当前页面没有找到上次同步锚点，将回退为重新同步当前已加载的 ${plan.sync_count} 条消息。`;
  }

  return `当前会话共有 ${payload?.message_count || 0} 条已加载消息。`;
}

function buildSyncPlan(payload, syncState) {
  const messages = Array.isArray(payload?.messages) ? payload.messages : [];
  if (messages.length === 0) {
    return {
      mode: "empty",
      payload: null,
      sync_count: 0,
      total_count: 0
    };
  }

  const lastSyncedMessageId = syncState?.last_message_id || null;
  if (!lastSyncedMessageId) {
    return {
      mode: "initial",
      payload,
      sync_count: messages.length,
      total_count: messages.length
    };
  }

  const anchorIndex = messages.findIndex((message) => message.message_id === lastSyncedMessageId);
  if (anchorIndex === -1) {
    return {
      mode: "resync",
      payload,
      sync_count: messages.length,
      total_count: messages.length
    };
  }

  const newMessages = messages.slice(anchorIndex + 1);
  if (newMessages.length === 0) {
    return {
      mode: "up_to_date",
      payload: null,
      sync_count: 0,
      total_count: messages.length
    };
  }

  return {
    mode: "incremental",
    payload: {
      ...payload,
      sync_mode: "incremental",
      sync_anchor_message_id: lastSyncedMessageId,
      message_count: newMessages.length,
      messages: newMessages
    },
    sync_count: newMessages.length,
    total_count: messages.length
  };
}

function updateSendButton(plan) {
  if (!plan || !plan.payload) {
    sendButton.disabled = true;
    sendButton.textContent = "同步新增内容";
    return;
  }

  sendButton.disabled = false;
  if (plan.mode === "initial") {
    sendButton.textContent = "首次同步到 SelfIndex";
    return;
  }
  if (plan.mode === "resync") {
    sendButton.textContent = "重新同步当前内容";
    return;
  }
  sendButton.textContent = "同步新增内容";
}

function setPayloadState(payload, plan) {
  latestPayload = payload;
  latestSyncPlan = plan;
  copyButton.disabled = !payload;
  downloadButton.disabled = !payload;
  updateSendButton(plan);
}

async function refreshConversationState() {
  setSummary("正在抓取当前页面里的已加载消息…");
  const payload = await requestCapture();
  const syncState = await getConversationSyncState(payload.conversation_id);
  const plan = buildSyncPlan(payload, syncState);

  output.value = JSON.stringify(payload, null, 2);
  setPayloadState(payload, plan);
  setSummary(
    `已抓取 ${payload.message_count} 条消息，conversation_id=${payload.conversation_id || "unknown"}`
  );
  setSyncStatus(describeSyncPlan(plan, payload, syncState));
  return { payload, plan, syncState };
}

async function ensureCaptureState() {
  if (latestPayload && latestSyncPlan) {
    return {
      payload: latestPayload,
      plan: latestSyncPlan,
      syncState: await getConversationSyncState(latestPayload.conversation_id)
    };
  }
  return refreshConversationState();
}

async function sendToSelfIndex(payload) {
  await saveSettings();
  const endpoint = endpointInput.value;
  const response = await fetch(endpoint, {
    method: "POST",
    headers: {
      "Content-Type": "application/json"
    },
    body: JSON.stringify(payload)
  });

  const result = await response.json().catch(() => ({}));
  if (!response.ok || !result.ok) {
    throw new Error(result.error || `发送失败，HTTP ${response.status}`);
  }
  return result;
}

captureButton.addEventListener("click", async () => {
  setPayloadState(null, null);
  output.value = "";
  setSyncStatus("正在检查当前会话同步状态…");

  try {
    await refreshConversationState();
  } catch (error) {
    setSummary(error.message || String(error));
    setSyncStatus("当前无法生成同步计划。");
  }
});

sendButton.addEventListener("click", async () => {
  try {
    const { payload, plan } = await ensureCaptureState();
    if (!plan || !plan.payload) {
      setSyncStatus("当前会话没有需要同步的新消息。");
      return;
    }

    if (plan.mode === "incremental") {
      setSummary(`正在发送 ${plan.sync_count} 条新增消息到本机 SelfIndex…`);
    } else {
      setSummary(`正在发送 ${plan.sync_count} 条消息到本机 SelfIndex…`);
    }

    const result = await sendToSelfIndex(plan.payload);
    const savedState = await saveConversationSyncState(payload);
    const nextPlan = buildSyncPlan(payload, savedState);
    setPayloadState(payload, nextPlan);
    setSummary(
      `已导入 ${result.raw_documents} 条消息，memory_units=${result.memory_units}，conversation_id=${result.conversation_id || payload.conversation_id || "unknown"}`
    );
    setSyncStatus(describeSyncPlan(nextPlan, payload, savedState));
  } catch (error) {
    setSummary(error.message || String(error));
  }
});

copyButton.addEventListener("click", async () => {
  if (!latestPayload) {
    return;
  }
  await navigator.clipboard.writeText(JSON.stringify(latestPayload, null, 2));
  setSummary("JSON 已复制到剪贴板。");
});

downloadButton.addEventListener("click", () => {
  if (!latestPayload) {
    return;
  }
  const blob = new Blob([JSON.stringify(latestPayload, null, 2)], { type: "application/json" });
  const url = URL.createObjectURL(blob);
  const filename = `${sanitizeFilename(latestPayload.conversation_id || latestPayload.conversation_title)}.json`;

  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = filename;
  anchor.click();
  URL.revokeObjectURL(url);
  setSummary(`JSON 已下载为 ${filename}`);
});

endpointInput.addEventListener("change", () => {
  saveSettings().catch(() => {});
});

async function initializePopup() {
  await loadSettings();
  try {
    setSyncStatus("正在检查当前会话同步状态…");
    await refreshConversationState();
  } catch (error) {
    setSummary(error.message || String(error));
    setSyncStatus("打开 ChatGPT 对话页后再试一次。");
    endpointInput.value = endpointInput.value || DEFAULT_ENDPOINT;
  }
}

initializePopup().catch(() => {
  endpointInput.value = DEFAULT_ENDPOINT;
  setSyncStatus("初始化失败，请重试。");
});
