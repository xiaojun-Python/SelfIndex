function normalizeWhitespace(value) {
  return String(value || "")
    .replace(/\r\n/g, "\n")
    .replace(/\u00a0/g, " ")
    .replace(/\n{3,}/g, "\n\n")
    .trim();
}

function detectProvider() {
  const hostname = String(window.location.hostname || "").toLowerCase();
  if (hostname === "chatgpt.com" || hostname === "chat.openai.com") {
    return "chatgpt";
  }
  if (hostname === "grok.com") {
    return "grok";
  }
  return null;
}

function contentHash(text) {
  let hash = 2166136261;
  for (let index = 0; index < text.length; index += 1) {
    hash ^= text.charCodeAt(index);
    hash = Math.imul(hash, 16777619);
  }
  return `fnv1a:${(hash >>> 0).toString(16).padStart(8, "0")}`;
}

function extractConversationId() {
  const match = window.location.pathname.match(/\/c\/([^/?#]+)/);
  return match ? match[1] : null;
}

function extractCanonicalConversationId() {
  const canonical = document.querySelector("link[rel='canonical']");
  const href = String(canonical?.getAttribute("href") || "").trim();
  const match = href.match(/\/c\/([^/?#]+)/);
  return match ? match[1] : null;
}

function extractConversationTitle() {
  const title = normalizeWhitespace(document.title || "");
  return title.replace(/\s*-\s*ChatGPT\s*$/i, "").trim() || null;
}

function extractGrokConversationTitle() {
  const title = normalizeWhitespace(document.title || "");
  return title.replace(/\s*-\s*Grok\s*$/i, "").trim() || null;
}

function removeNoiseNodes(container) {
  const selectors = [
    "button",
    "svg",
    "textarea",
    "input",
    "form",
    "nav",
    "script",
    "style",
    ".sr-only",
    "[aria-hidden='true']",
    "[role='group']",
    "[data-testid$='action-button']",
    "[data-testid='webpage-citation-pill']"
  ];

  container.querySelectorAll(selectors.join(",")).forEach((node) => node.remove());
}

function uniqueNonEmptyText(values) {
  const seen = new Set();
  const results = [];

  values.forEach((value) => {
    const normalized = normalizeWhitespace(value);
    if (!normalized || seen.has(normalized)) {
      return;
    }
    seen.add(normalized);
    results.push(normalized);
  });

  return results;
}

function chooseLongestText(values) {
  const candidates = uniqueNonEmptyText(values);
  if (candidates.length === 0) {
    return "";
  }
  return candidates.sort((left, right) => right.length - left.length)[0];
}

function normalizeInlineWhitespace(value) {
  return String(value || "")
    .replace(/\u00a0/g, " ")
    .replace(/[ \t\r\f\v]+/g, " ");
}

function preferredContentSelectors() {
  return [
    ".markdown.prose",
    ".markdown",
    ".prose",
    ".whitespace-pre-wrap",
    "[data-message-content]",
    "[dir='auto']"
  ];
}

function extractStructuredText(container) {
  const blockTags = new Set([
    "P",
    "DIV",
    "SECTION",
    "ARTICLE",
    "UL",
    "OL",
    "LI",
    "PRE",
    "BLOCKQUOTE",
    "H1",
    "H2",
    "H3",
    "H4",
    "H5",
    "H6"
  ]);

  const pieces = [];

  function appendText(text) {
    const normalized = String(text || "").replace(/\u00a0/g, " ");
    if (!normalized) {
      return;
    }
    pieces.push(normalized);
  }

  function appendBreak(count = 1) {
    const token = "\n".repeat(count);
    if (pieces.length === 0) {
      pieces.push(token);
      return;
    }
    const last = pieces[pieces.length - 1];
    if (last.endsWith("\n\n")) {
      return;
    }
    if (last.endsWith("\n")) {
      if (count > 1) {
        pieces[pieces.length - 1] = `${last}\n`;
      }
      return;
    }
    pieces.push(token);
  }

  function walk(node) {
    if (!node) {
      return;
    }

    if (node.nodeType === Node.TEXT_NODE) {
      appendText(node.nodeValue || "");
      return;
    }

    if (node.nodeType !== Node.ELEMENT_NODE) {
      return;
    }

    const element = node;
    const tag = element.tagName;

    if (tag === "BR") {
      appendBreak(1);
      return;
    }

    const isListItem = tag === "LI";
    const isBlock = blockTags.has(tag);

    if (isBlock && pieces.length > 0) {
      appendBreak(isListItem ? 1 : 2);
    }
    if (isListItem) {
      appendText("- ");
    }

    for (const child of element.childNodes) {
      walk(child);
    }
  }

  walk(container);
  return normalizeWhitespace(pieces.join(""));
}

function selectPreferredContentRoot(container) {
  for (const selector of preferredContentSelectors()) {
    const root = container.querySelector(selector);
    if (root) {
      return {
        root,
        selector
      };
    }
  }
  return {
    root: container,
    selector: "self"
  };
}

function trimMarkdownLines(value) {
  const text = String(value || "").replace(/\r\n/g, "\n");
  const lines = text.split("\n");
  const cleaned = [];

  for (const line of lines) {
    cleaned.push(line.replace(/[ \t]+$/g, ""));
  }

  return cleaned.join("\n").replace(/\n{3,}/g, "\n\n").trim();
}

function detectCodeLanguage(element) {
  const classNames = String(element.getAttribute("class") || "");
  const candidates = classNames.split(/\s+/).filter(Boolean);
  for (const className of candidates) {
    const match = className.match(/(?:language-|lang-)([a-z0-9_+-]+)/i);
    if (match) {
      return match[1].toLowerCase();
    }
  }
  return "";
}

function wrapIfNotEmpty(prefix, value, suffix) {
  const text = String(value || "").trim();
  if (!text) {
    return "";
  }
  return `${prefix}${text}${suffix}`;
}

function renderInlineMarkdown(node) {
  if (!node) {
    return "";
  }

  if (node.nodeType === Node.TEXT_NODE) {
    return normalizeInlineWhitespace(node.nodeValue || "");
  }

  if (node.nodeType !== Node.ELEMENT_NODE) {
    return "";
  }

  const element = node;
  const tag = element.tagName;

  if (tag === "BR") {
    return "\n";
  }

  if (tag === "STRONG" || tag === "B") {
    return wrapIfNotEmpty("**", renderInlineMarkdownChildren(element), "**");
  }

  if (tag === "EM" || tag === "I") {
    return wrapIfNotEmpty("*", renderInlineMarkdownChildren(element), "*");
  }

  if (tag === "CODE" && element.parentElement?.tagName !== "PRE") {
    return wrapIfNotEmpty("`", normalizeWhitespace(element.textContent || ""), "`");
  }

  if (tag === "A") {
    const label = trimMarkdownLines(renderInlineMarkdownChildren(element)) || normalizeWhitespace(element.textContent || "");
    const href = String(element.getAttribute("href") || "").trim();
    if (!href) {
      return label;
    }
    return `[${label}](${href})`;
  }

  return renderInlineMarkdownChildren(element);
}

function renderInlineMarkdownChildren(element) {
  let result = "";
  for (const child of element.childNodes) {
    result += renderInlineMarkdown(child);
  }

  return result
    .replace(/[ \t]+\n/g, "\n")
    .replace(/\n[ \t]+/g, "\n")
    .replace(/[ ]{2,}/g, " ");
}

function indentMarkdownBlock(value, prefix) {
  return String(value || "")
    .split("\n")
    .map((line) => (line ? `${prefix}${line}` : prefix.trimEnd()))
    .join("\n");
}

function renderListItemMarkdown(listItem, ordered, depth, index) {
  const bullet = ordered ? `${index}. ` : "- ";
  const indent = "  ".repeat(depth);
  const nestedIndent = "  ".repeat(depth + 1);
  const inlineParts = [];
  const nestedBlocks = [];

  for (const child of listItem.childNodes) {
    if (child.nodeType === Node.TEXT_NODE) {
      inlineParts.push(renderInlineMarkdown(child));
      continue;
    }
    if (child.nodeType !== Node.ELEMENT_NODE) {
      continue;
    }

    const tag = child.tagName;
    if (tag === "UL" || tag === "OL") {
      nestedBlocks.push(renderListMarkdown(child, tag === "OL", depth + 1).trim());
      continue;
    }
    if (tag === "P") {
      inlineParts.push(renderInlineMarkdownChildren(child));
      continue;
    }
    if (tag === "PRE" || tag === "BLOCKQUOTE" || /^H[1-6]$/.test(tag)) {
      nestedBlocks.push(indentMarkdownBlock(renderBlockMarkdown(child).trim(), nestedIndent));
      continue;
    }

    inlineParts.push(renderInlineMarkdown(child));
  }

  const firstLineContent = trimMarkdownLines(inlineParts.join(""))
    .replace(/\n+/g, " ")
    .trim();
  const firstLine = `${indent}${bullet}${firstLineContent}`.trimEnd();

  if (nestedBlocks.length === 0) {
    return firstLine;
  }

  return `${firstLine}\n${nestedBlocks.join("\n")}`;
}

function renderListMarkdown(listNode, ordered, depth = 0) {
  const items = [];
  let index = 1;
  for (const child of Array.from(listNode.children)) {
    if (child.tagName !== "LI") {
      continue;
    }
    items.push(renderListItemMarkdown(child, ordered, depth, index));
    index += 1;
  }
  return `${items.join("\n")}\n\n`;
}

function renderBlockquoteMarkdown(element) {
  const inner = trimMarkdownLines(renderChildrenMarkdown(element));
  if (!inner) {
    return "";
  }
  const quoted = inner
    .split("\n")
    .map((line) => (line ? `> ${line}` : ">"))
    .join("\n");
  return `${quoted}\n\n`;
}

function extractPreformattedText(node) {
  const parts = [];

  function append(value) {
    if (!value) {
      return;
    }
    parts.push(value);
  }

  function ensureLineBreak() {
    if (parts.length === 0) {
      return;
    }
    const last = parts[parts.length - 1];
    if (!String(last).endsWith("\n")) {
      parts.push("\n");
    }
  }

  function walk(current) {
    if (!current) {
      return;
    }

    if (current.nodeType === Node.TEXT_NODE) {
      append(current.nodeValue || "");
      return;
    }

    if (current.nodeType !== Node.ELEMENT_NODE) {
      return;
    }

    const element = current;
    const tag = element.tagName;

    if (tag === "BR") {
      append("\n");
      return;
    }

    const isLineWrapper =
      tag === "DIV" ||
      tag === "P" ||
      tag === "LI" ||
      tag === "TR";

    if (isLineWrapper && parts.length > 0) {
      ensureLineBreak();
    }

    for (const child of element.childNodes) {
      walk(child);
    }

    if (isLineWrapper) {
      ensureLineBreak();
    }
  }

  walk(node);
  return String(parts.join(""))
    .replace(/\r\n/g, "\n")
    .replace(/\n{3,}/g, "\n\n")
    .replace(/\n$/, "");
}

function renderCodeBlockMarkdown(element) {
  const codeRoot = element.querySelector(".cm-content, code") || element;
  const language = detectCodeLanguage(codeRoot || element);
  const codeText = extractPreformattedText(codeRoot);
  return `\`\`\`${language}\n${codeText}\n\`\`\`\n\n`;
}

function renderBlockMarkdown(node) {
  if (!node) {
    return "";
  }

  if (node.nodeType === Node.TEXT_NODE) {
    return normalizeInlineWhitespace(node.nodeValue || "");
  }

  if (node.nodeType !== Node.ELEMENT_NODE) {
    return "";
  }

  const element = node;
  const tag = element.tagName;

  if (/^H[1-6]$/.test(tag)) {
    const level = Number(tag.slice(1));
    const text = trimMarkdownLines(renderInlineMarkdownChildren(element));
    return text ? `${"#".repeat(level)} ${text}\n\n` : "";
  }

  if (tag === "P") {
    const text = trimMarkdownLines(renderInlineMarkdownChildren(element));
    return text ? `${text}\n\n` : "";
  }

  if (tag === "PRE") {
    return renderCodeBlockMarkdown(element);
  }

  if (tag === "UL") {
    return renderListMarkdown(element, false);
  }

  if (tag === "OL") {
    return renderListMarkdown(element, true);
  }

  if (tag === "BLOCKQUOTE") {
    return renderBlockquoteMarkdown(element);
  }

  if (tag === "HR") {
    return "---\n\n";
  }

  if (tag === "TABLE") {
    const text = trimMarkdownLines(extractStructuredText(element));
    return text ? `${text}\n\n` : "";
  }

  const renderedChildren = renderChildrenMarkdown(element);
  if (renderedChildren.trim()) {
    return renderedChildren;
  }

  const inline = trimMarkdownLines(renderInlineMarkdownChildren(element));
  return inline ? `${inline}\n\n` : "";
}

function renderChildrenMarkdown(element) {
  let result = "";
  for (const child of element.childNodes) {
    result += renderBlockMarkdown(child);
  }
  return result;
}

function extractMarkdownContent(container) {
  return trimMarkdownLines(renderChildrenMarkdown(container));
}

function extractMessageContentArtifacts(messageNode) {
  const clone = messageNode.cloneNode(true);
  removeNoiseNodes(clone);
  const selected = selectPreferredContentRoot(clone);
  const selectedRoot = selected.root;

  const candidateTexts = [];
  for (const selector of preferredContentSelectors()) {
    const root = clone.querySelector(selector);
    if (root) {
      candidateTexts.push(extractStructuredText(root));
      candidateTexts.push(root.textContent || "");
    }
  }
  candidateTexts.push(extractStructuredText(selectedRoot));
  candidateTexts.push(selectedRoot.textContent || "");
  candidateTexts.push(extractStructuredText(clone));
  candidateTexts.push(clone.textContent || "");

  const plainText = chooseLongestText(candidateTexts);
  const markdownContent = extractMarkdownContent(selectedRoot);
  const content =
    markdownContent && markdownContent.length >= Math.max(plainText.length * 0.35, 24)
      ? markdownContent
      : plainText;
  return { content };
}

function findLastMatchingNode(nodes, predicate) {
  for (let index = nodes.length - 1; index >= 0; index -= 1) {
    if (predicate(nodes[index])) {
      return nodes[index];
    }
  }
  return null;
}

function selectMessageNode(turnNode) {
  const messageNodes = Array.from(
    turnNode.querySelectorAll("[data-message-id][data-message-author-role]")
  );
  if (messageNodes.length === 0) {
    return null;
  }

  const turnRole = turnNode.getAttribute("data-turn");
  const roleMatchedNodes = turnRole
    ? messageNodes.filter(
        (node) => node.getAttribute("data-message-author-role") === turnRole
      )
    : messageNodes;
  const candidates = roleMatchedNodes.length > 0 ? roleMatchedNodes : messageNodes;

  if (turnRole === "assistant") {
    return (
      findLastMatchingNode(
        candidates,
        (node) => node.getAttribute("data-turn-start-message") === "true"
      ) ||
      candidates[candidates.length - 1]
    );
  }

  return candidates[0];
}

function buildMessageRecord(turnNode, captureIndex, conversationId, conversationTitle) {
  const messageNode = selectMessageNode(turnNode);
  if (!messageNode) {
    return null;
  }

  const messageId = messageNode.getAttribute("data-message-id");
  const role = messageNode.getAttribute("data-message-author-role");
  const modelSlug = normalizeWhitespace(
    messageNode.getAttribute("data-message-model-slug") || ""
  ) || null;
  const contentArtifacts = extractMessageContentArtifacts(messageNode);
  const content = contentArtifacts.content;

  if (!messageId || !role || !content) {
    return null;
  }

  return {
    platform: "chatgpt",
    source_label: "browser",
    conversation_id: conversationId,
    conversation_title: conversationTitle,
    message_id: messageId,
    parent_message_id: null,
    role,
    model: modelSlug,
    model_slug: modelSlug,
    content,
    content_hash: contentHash(content),
    timestamp: null,
    sequence: null,
    capture_index: captureIndex,
    dom_turn_testid: turnNode.getAttribute("data-testid"),
    dom_turn_id: turnNode.getAttribute("data-turn-id"),
    page_url: window.location.href
  };
}

function captureVisibleConversation() {
  const conversationId = extractConversationId();
  const conversationTitle = extractConversationTitle();
  const turnNodes = Array.from(document.querySelectorAll("section[data-testid^='conversation-turn-']"));
  const messages = [];
  const duplicates = [];
  const seenMessageIds = new Set();

  turnNodes.forEach((turnNode, index) => {
    const record = buildMessageRecord(turnNode, index, conversationId, conversationTitle);
    if (!record) {
      return;
    }
    if (seenMessageIds.has(record.message_id)) {
      duplicates.push(record.message_id);
      return;
    }
    seenMessageIds.add(record.message_id);
    messages.push(record);
  });

  return {
    platform: "chatgpt",
    source_label: "browser",
    page_url: window.location.href,
    conversation_id: conversationId,
    conversation_title: conversationTitle,
    captured_at: new Date().toISOString(),
    message_count: messages.length,
    duplicates,
    order_strategy: "capture_index",
    messages
  };
}

function extractGrokConversationId() {
  return extractConversationId() || extractCanonicalConversationId();
}

function grokMessageContainers() {
  return Array.from(document.querySelectorAll("div[id^='response-']")).filter((node) => {
    if (!(node instanceof HTMLElement)) {
      return false;
    }
    return Boolean(node.querySelector(".response-content-markdown.markdown"));
  });
}

function grokRoleFromNode(messageNode) {
  const className = String(messageNode.getAttribute("class") || "");
  if (/\bitems-end\b/.test(className)) {
    return "user";
  }
  if (/\bitems-start\b/.test(className)) {
    return "assistant";
  }
  return null;
}

function grokMessageId(messageNode) {
  const rawId = String(messageNode.getAttribute("id") || "").trim();
  if (!rawId) {
    return null;
  }
  return rawId.replace(/^response-/, "") || rawId;
}

function buildGrokMessageRecord(messageNode, captureIndex, conversationId, conversationTitle) {
  const messageId = grokMessageId(messageNode);
  const role = grokRoleFromNode(messageNode);
  const content = extractMessageContentArtifacts(messageNode).content;

  if (!messageId || !role || !content) {
    return null;
  }

  return {
    platform: "grok",
    source_label: "browser",
    conversation_id: conversationId,
    conversation_title: conversationTitle,
    message_id: messageId,
    parent_message_id: null,
    role,
    model: null,
    model_slug: null,
    content,
    content_hash: contentHash(content),
    timestamp: null,
    sequence: null,
    capture_index: captureIndex,
    dom_turn_testid: null,
    dom_turn_id: messageNode.getAttribute("id"),
    page_url: window.location.href
  };
}

function captureVisibleGrokConversation() {
  const conversationId = extractGrokConversationId();
  const conversationTitle = extractGrokConversationTitle();
  const messageNodes = grokMessageContainers();
  const messages = [];
  const duplicates = [];
  const seenMessageIds = new Set();

  messageNodes.forEach((messageNode, index) => {
    const record = buildGrokMessageRecord(messageNode, index, conversationId, conversationTitle);
    if (!record) {
      return;
    }
    if (seenMessageIds.has(record.message_id)) {
      duplicates.push(record.message_id);
      return;
    }
    seenMessageIds.add(record.message_id);
    messages.push(record);
  });

  return {
    platform: "grok",
    source_label: "browser",
    page_url: window.location.href,
    conversation_id: conversationId,
    conversation_title: conversationTitle,
    captured_at: new Date().toISOString(),
    message_count: messages.length,
    duplicates,
    order_strategy: "capture_index",
    messages
  };
}

function captureActiveConversation() {
  const provider = detectProvider();
  if (provider === "chatgpt") {
    return captureVisibleConversation();
  }
  if (provider === "grok") {
    return captureVisibleGrokConversation();
  }
  throw new Error("当前页面还不在已支持的 AI 平台列表里。");
}

chrome.runtime.onMessage.addListener((message, _sender, sendResponse) => {
  if (
    !message ||
    !["SELFINDEX_CAPTURE_CHATGPT", "SELFINDEX_CAPTURE_CONVERSATION"].includes(message.type)
  ) {
    return;
  }

  try {
    const payload = captureActiveConversation();
    if (!payload.conversation_id) {
      sendResponse({
        ok: false,
        error: "当前页面没有识别出 conversation_id。请确认你在具体的 AI 对话页。"
      });
      return;
    }
    sendResponse({ ok: true, payload });
  } catch (error) {
    sendResponse({
      ok: false,
      error: error instanceof Error ? error.message : String(error)
    });
  }
});

window.SELFINDEX_CAPTURE_CHATGPT = captureVisibleConversation;
window.SELFINDEX_CAPTURE_GROK = captureVisibleGrokConversation;
window.SELFINDEX_CAPTURE_CONVERSATION = captureActiveConversation;
