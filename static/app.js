async function requestJson(url, options = {}) {
  const response = await fetch(url, {
    headers: { 'Content-Type': 'application/json' },
    ...options,
  });

  if (!response.ok) {
    const detail = await response.text();
    throw new Error(detail || `Request failed: ${response.status}`);
  }
  return response.json();
}

const SESSION_STORAGE_KEY = 'patent-chat-sessions-v1';
const ACTIVE_SESSION_STORAGE_KEY = 'patent-chat-active-session-v1';
const MAX_SESSION_COUNT = 30;

const appState = {
  sessions: [],
  activeSessionId: null,
  isStreaming: false,
};

function getElement(id) {
  return document.getElementById(id);
}

function setFeedback(scope, message = '', type = '') {
  const feedback = getElement(`${scope}-feedback`);
  if (!feedback) {
    return;
  }

  feedback.textContent = message;
  feedback.className = `feedback${type ? ` ${type}` : ''}`;

  const form = scope === 'chat' ? getElement('chat-form') : getElement('search-form');
  if (form) {
    form.classList.toggle('has-error', type === 'error');
  }
}

function clearFeedback(scope) {
  setFeedback(scope, '');
}

function showToast(message, type = 'info') {
  const stack = getElement('toast-stack');
  if (!stack) {
    return;
  }

  const toast = document.createElement('div');
  toast.className = `toast ${type}`;
  toast.textContent = message;
  stack.appendChild(toast);

  globalThis.setTimeout(() => {
    toast.remove();
  }, 3000);
}

function renderSearchLoading() {
  const container = getElement('search-results');
  container.className = 'result-list';
  container.innerHTML = Array.from({ length: 4 }, () => `
    <div class="skeleton-card" aria-hidden="true">
      <div class="skeleton-line short"></div>
      <div class="skeleton-line long"></div>
      <div class="skeleton-line medium"></div>
    </div>
  `).join('');
}

function showChatLoadingSkeleton() {
  const container = getElement('chat-messages');
  removeChatLoadingSkeleton();
  const skeleton = document.createElement('article');
  skeleton.id = 'chat-loading-skeleton';
  skeleton.className = 'message assistant loading';
  skeleton.setAttribute('aria-hidden', 'true');

  const bubble = document.createElement('div');
  bubble.className = 'skeleton-bubble';
  skeleton.appendChild(bubble);

  if (container.querySelector('.empty-chat')) {
    container.innerHTML = '';
  }
  container.appendChild(skeleton);
  container.scrollTop = container.scrollHeight;
}

function removeChatLoadingSkeleton() {
  getElement('chat-loading-skeleton')?.remove();
}

function getSelectedModel() {
  return getElement('model-picker')?.value || null;
}

function nowIso() {
  return new Date().toISOString();
}

function generateSessionId() {
  if (globalThis.crypto?.randomUUID) {
    return crypto.randomUUID();
  }
  return `session-${Date.now()}-${Math.random().toString(16).slice(2)}`;
}

function createSession() {
  const timestamp = nowIso();
  return {
    id: generateSessionId(),
    title: '新会话',
    model: getSelectedModel(),
    createdAt: timestamp,
    updatedAt: timestamp,
    history: [],
    messages: [],
  };
}

function deriveSessionTitle(text) {
  const trimmed = (text || '').replace(/\s+/g, ' ').trim();
  if (!trimmed) {
    return '新会话';
  }
  return trimmed.length > 24 ? `${trimmed.slice(0, 24)}...` : trimmed;
}

function formatSessionTime(timestamp) {
  try {
    return new Date(timestamp).toLocaleString('zh-CN', {
      month: 'numeric',
      day: 'numeric',
      hour: '2-digit',
      minute: '2-digit',
    });
  } catch {
    return '';
  }
}

function persistSessions() {
  localStorage.setItem(SESSION_STORAGE_KEY, JSON.stringify(appState.sessions.slice(0, MAX_SESSION_COUNT)));
  if (appState.activeSessionId) {
    localStorage.setItem(ACTIVE_SESSION_STORAGE_KEY, appState.activeSessionId);
  }
}

function sortSessions() {
  appState.sessions.sort((left, right) => String(right.updatedAt).localeCompare(String(left.updatedAt)));
}

function getActiveSession() {
  return appState.sessions.find((session) => session.id === appState.activeSessionId) || null;
}

function ensureSessionState() {
  try {
    const rawSessions = JSON.parse(localStorage.getItem(SESSION_STORAGE_KEY) || '[]');
    if (Array.isArray(rawSessions)) {
      appState.sessions = rawSessions
        .filter((session) => session && typeof session.id === 'string')
        .map((session) => ({
          id: session.id,
          title: session.title || '新会话',
          model: session.model || null,
          createdAt: session.createdAt || nowIso(),
          updatedAt: session.updatedAt || session.createdAt || nowIso(),
          history: Array.isArray(session.history) ? session.history.filter((item) => item && typeof item.role === 'string' && typeof item.content === 'string') : [],
          messages: Array.isArray(session.messages) ? session.messages : [],
        }));
    }
  } catch {
    appState.sessions = [];
  }

  if (appState.sessions.length === 0) {
    const initialSession = createSession();
    appState.sessions = [initialSession];
    appState.activeSessionId = initialSession.id;
    persistSessions();
    return;
  }

  sortSessions();
  const storedActiveSessionId = localStorage.getItem(ACTIVE_SESSION_STORAGE_KEY);
  appState.activeSessionId = appState.sessions.some((session) => session.id === storedActiveSessionId)
    ? storedActiveSessionId
    : appState.sessions[0].id;
}

function escapeHtml(value) {
  return String(value)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;');
}

function escapeAttribute(value) {
  return String(value).replace(/"/g, '&quot;');
}

function applyInlineMarkdown(text) {
  const htmlTokens = [];
  const createToken = (html) => {
    const token = `__HTML_TOKEN_${htmlTokens.length}__`;
    htmlTokens.push({ token, html });
    return token;
  };

  let value = String(text || '');
  value = value.replace(/\[([^\]]+)\]\((https?:\/\/[^\s)]+)\)/g, (_, label, url) => createToken(
    `<a href="${escapeAttribute(url)}" target="_blank" rel="noopener noreferrer">${escapeHtml(label)}</a>`
  ));
  value = value.replace(/`([^`]+)`/g, (_, code) => createToken(`<code>${escapeHtml(code)}</code>`));
  value = escapeHtml(value);
  value = value.replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>');
  value = value.replace(/__([^_]+)__/g, '<strong>$1</strong>');

  htmlTokens.forEach(({ token, html }) => {
    value = value.replaceAll(token, html);
  });
  return value;
}

function isTableSeparator(line) {
  return /^\s*\|?(\s*:?-{3,}:?\s*\|)+\s*:?-{3,}:?\s*\|?\s*$/.test(line);
}

function isTableRow(line) {
  const trimmed = line.trim();
  return trimmed.includes('|') && /^\|?.+\|.+\|?$/.test(trimmed);
}

function splitTableCells(line) {
  const trimmed = line.trim().replace(/^\|/, '').replace(/\|$/, '');
  return trimmed.split('|').map((cell) => cell.trim());
}

function renderMarkdownTable(lines) {
  const headerCells = splitTableCells(lines[0]);
  const bodyRows = lines.slice(2).map(splitTableCells);
  const headerHtml = headerCells.map((cell) => `<th>${applyInlineMarkdown(cell)}</th>`).join('');
  const bodyHtml = bodyRows.map((row) => `
    <tr>${row.map((cell) => `<td>${applyInlineMarkdown(cell)}</td>`).join('')}</tr>
  `).join('');

  return `
    <div class="markdown-table-wrap">
      <table>
        <thead><tr>${headerHtml}</tr></thead>
        <tbody>${bodyHtml}</tbody>
      </table>
    </div>
  `;
}

function renderMarkdownList(lines, ordered) {
  const tagName = ordered ? 'ol' : 'ul';
  const items = lines.map((line) => line.replace(/^\s*(?:[-*+]|\d+\.)\s+/, '').trim());
  return `<${tagName}>${items.map((item) => `<li>${applyInlineMarkdown(item)}</li>`).join('')}</${tagName}>`;
}

function renderMarkdownBlockquote(lines) {
  const content = lines.map((line) => line.replace(/^\s*>\s?/, '').trim()).join('<br>');
  return `<blockquote>${applyInlineMarkdown(content)}</blockquote>`;
}

function renderMarkdownParagraph(lines) {
  return `<p>${lines.map((line) => applyInlineMarkdown(line)).join('<br>')}</p>`;
}

function isListLine(line) {
  return /^\s*(?:[-*+]|\d+\.)\s+/.test(line);
}

function isBlockBoundary(line) {
  return !line.trim()
    || /^\s*```/.test(line)
    || /^\s*#{1,6}\s+/.test(line)
    || /^\s*>\s?/.test(line)
    || isListLine(line)
    || isTableRow(line);
}

function renderMarkdown(text) {
  const lines = String(text || '').replace(/\r\n?/g, '\n').split('\n');
  const blocks = [];

  for (let index = 0; index < lines.length;) {
    const line = lines[index];

    if (!line.trim()) {
      index += 1;
      continue;
    }

    if (/^\s*```/.test(line)) {
      const language = line.replace(/^\s*```/, '').trim();
      const codeLines = [];
      index += 1;
      while (index < lines.length && !/^\s*```/.test(lines[index])) {
        codeLines.push(lines[index]);
        index += 1;
      }
      if (index < lines.length) {
        index += 1;
      }
      blocks.push(`
        <pre class="markdown-code-block"${language ? ` data-language="${escapeAttribute(language)}"` : ''}><code>${escapeHtml(codeLines.join('\n'))}</code></pre>
      `);
      continue;
    }

    if (/^\s*#{1,6}\s+/.test(line)) {
      const match = line.match(/^\s*(#{1,6})\s+(.*)$/);
      const level = Math.min(match[1].length, 6);
      blocks.push(`<h${level}>${applyInlineMarkdown(match[2].trim())}</h${level}>`);
      index += 1;
      continue;
    }

    if (isTableRow(line) && index + 1 < lines.length && isTableSeparator(lines[index + 1])) {
      const tableLines = [line, lines[index + 1]];
      index += 2;
      while (index < lines.length && lines[index].trim() && isTableRow(lines[index])) {
        tableLines.push(lines[index]);
        index += 1;
      }
      blocks.push(renderMarkdownTable(tableLines));
      continue;
    }

    if (/^\s*>\s?/.test(line)) {
      const quoteLines = [];
      while (index < lines.length && /^\s*>\s?/.test(lines[index])) {
        quoteLines.push(lines[index]);
        index += 1;
      }
      blocks.push(renderMarkdownBlockquote(quoteLines));
      continue;
    }

    if (isListLine(line)) {
      const ordered = /^\s*\d+\.\s+/.test(line);
      const listLines = [];
      while (index < lines.length) {
        const currentLine = lines[index];
        if (!currentLine.trim()) {
          break;
        }
        if (ordered !== /^\s*\d+\.\s+/.test(currentLine) || !isListLine(currentLine)) {
          break;
        }
        listLines.push(currentLine);
        index += 1;
      }
      blocks.push(renderMarkdownList(listLines, ordered));
      continue;
    }

    const paragraphLines = [];
    while (index < lines.length && !isBlockBoundary(lines[index])) {
      paragraphLines.push(lines[index].trim());
      index += 1;
    }
    if (paragraphLines.length === 0) {
      paragraphLines.push(line.trim());
      index += 1;
    }
    blocks.push(renderMarkdownParagraph(paragraphLines));
  }

  return blocks.join('');
}

function createMessageElement(message) {
  const article = document.createElement('article');
  article.className = `message ${message.role}${message.variant ? ` ${message.variant}` : ''}`;

  if (message.title) {
    const label = document.createElement('strong');
    label.className = 'trace-label';
    label.textContent = message.title;
    article.appendChild(label);

    const content = document.createElement('pre');
    content.className = 'trace-content';
    content.textContent = message.text;
    article.appendChild(content);
    return article;
  }

  const shouldRenderMarkdown = message.role === 'assistant' && !message.variant;
  if (shouldRenderMarkdown) {
    const content = document.createElement('div');
    content.className = 'message-markdown';
    content.innerHTML = renderMarkdown(message.text);
    article.appendChild(content);
    return article;
  }

  const paragraph = document.createElement('p');
  paragraph.textContent = message.text;
  article.appendChild(paragraph);
  return article;
}

function renderCurrentSession() {
  const container = getElement('chat-messages');
  const session = getActiveSession();
  container.innerHTML = '';

  if (!session || session.messages.length === 0) {
    const placeholder = document.createElement('article');
    placeholder.className = 'message assistant empty-chat';
    const paragraph = document.createElement('p');
    paragraph.textContent = '开始一个新问题，系统会把这一轮对话保存到左侧历史会话。';
    placeholder.appendChild(paragraph);
    container.appendChild(placeholder);
    return;
  }

  session.messages.forEach((message) => {
    container.appendChild(createMessageElement(message));
  });
  container.scrollTop = container.scrollHeight;
}

function renderSessionList() {
  const container = getElement('session-list');
  sortSessions();
  container.innerHTML = '';

  appState.sessions.forEach((session) => {
    const button = document.createElement('button');
    button.type = 'button';
    button.className = `session-item${session.id === appState.activeSessionId ? ' active' : ''}`;
    button.disabled = appState.isStreaming;

    const title = document.createElement('strong');
    title.textContent = session.title;

    button.appendChild(title);
    button.addEventListener('click', () => {
      if (appState.isStreaming) {
        return;
      }
      appState.activeSessionId = session.id;
      persistSessions();
      if (session.model && getElement('model-picker')) {
        getElement('model-picker').value = session.model;
      }
      renderSessionList();
      renderCurrentSession();
    });
    container.appendChild(button);
  });
}

function addMessageToActiveSession(message, options = {}) {
  const session = getActiveSession();
  if (!session) {
    return;
  }

  session.messages.push(message);
  session.updatedAt = nowIso();
  if (message.role === 'user' && session.title === '新会话') {
    session.title = deriveSessionTitle(message.text);
  }
  if (!session.model) {
    session.model = getSelectedModel();
  }
  persistSessions();
  renderSessionList();

  if (options.render !== false) {
    const container = getElement('chat-messages');
    if (container.querySelector('.empty-chat')) {
      container.innerHTML = '';
    }
    container.appendChild(createMessageElement(message));
    container.scrollTop = container.scrollHeight;
  }
}

function appendHistoryTurn(role, content) {
  const session = getActiveSession();
  if (!session) {
    return;
  }

  const trimmedContent = String(content || '').trim();
  if (!trimmedContent) {
    return;
  }

  session.history.push({ role, content: trimmedContent });
  session.updatedAt = nowIso();
  persistSessions();
  renderSessionList();
}

function setStreamingState(isStreaming) {
  appState.isStreaming = isStreaming;
  const submitButton = document.querySelector('#chat-form button[type="submit"]');
  const newSessionButton = getElement('new-session-button');
  getElement('chat-input').disabled = isStreaming;
  submitButton.disabled = isStreaming;
  newSessionButton.disabled = isStreaming;
  renderSessionList();
}

function createAndActivateSession() {
  if (appState.isStreaming) {
    return;
  }
  const session = createSession();
  appState.sessions.unshift(session);
  appState.activeSessionId = session.id;
  persistSessions();
  renderSessionList();
  renderCurrentSession();
  clearFeedback('chat');
  showToast('已创建新会话。', 'success');
}

async function requestNdjsonStream(url, options, onEvent) {
  const response = await fetch(url, options);
  if (!response.ok) {
    const detail = await response.text();
    throw new Error(detail || `Request failed: ${response.status}`);
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = '';
  let finalPayload = null;

  while (true) {
    const { done, value } = await reader.read();
    buffer += decoder.decode(value || new Uint8Array(), { stream: !done });

    const lines = buffer.split('\n');
    buffer = lines.pop() || '';

    for (const line of lines) {
      if (!line.trim()) {
        continue;
      }
      const event = JSON.parse(line);
      onEvent(event);
      if (event.type === 'final') {
        finalPayload = event.payload;
      }
    }

    if (done) {
      break;
    }
  }

  if (buffer.trim()) {
    const event = JSON.parse(buffer);
    onEvent(event);
    if (event.type === 'final') {
      finalPayload = event.payload;
    }
  }

  return finalPayload;
}

function appendMessage(role, text, variant = '') {
  addMessageToActiveSession({ role, variant, text });
}

function appendTraceBlock(title, text, variant) {
  addMessageToActiveSession({ role: 'assistant', variant: `trace ${variant}`, title, text });
}

function handleChatStreamEvent(event) {
  removeChatLoadingSkeleton();
  clearFeedback('chat');

  if (event.type === 'status') {
    appendMessage('assistant', event.text, 'status');
    return;
  }

  if (event.type === 'reasoning') {
    appendTraceBlock('思考过程', event.text, 'reasoning');
    return;
  }

  if (event.type === 'tool_call') {
    const call = event.call;
    appendTraceBlock(
      `工具调用 · ${call.tool}`,
      `${JSON.stringify(call.arguments, null, 2)}\n\n结果摘要: ${call.result_preview}`,
      'tool-call'
    );
    return;
  }

  if (event.type === 'answer') {
    appendMessage('assistant', event.text);
  }
}

async function loadPatentDetails(patentId) {
  const detail = await requestJson(`/api/patents/${encodeURIComponent(patentId)}`);
  showToast(`已加载 ${detail.patent_id} 的详情。`, 'info');
  return detail;
}

function renderSearchResults(items) {
  const container = getElement('search-results');
  if (!items || items.length === 0) {
    container.className = 'result-list empty-state';
    container.textContent = '没有命中结果';
    return;
  }

  container.className = 'result-list';
  container.innerHTML = items.map((item) => `
    <button class="result-item" data-patent-id="${item.patent_id}">
      <strong>${item.patent_id}</strong>
      <span>${item.title}</span>
      <small>${item.assignee || '未知申请人'} · ${item.filing_date || '未知日期'} · ${item.ipc_main || '未知IPC'}</small>
    </button>
  `).join('');

  container.querySelectorAll('.result-item').forEach((button) => {
    button.addEventListener('click', () => loadPatentDetails(button.dataset.patentId));
  });
}

async function submitSearch(event) {
  event.preventDefault();
  clearFeedback('search');
  const payload = {
    keyword: getElement('keyword').value,
    assignee: getElement('assignee').value || null,
    year_start: Number(getElement('year-start').value) || null,
    year_end: Number(getElement('year-end').value) || null,
    limit: 20,
  };

  try {
    renderSearchLoading();
    const results = await requestJson('/api/search', {
      method: 'POST',
      body: JSON.stringify(payload),
    });
    renderSearchResults(results);
    setFeedback('search', `已返回 ${results.length} 条结果。`, 'success');
    showToast(`检索完成，返回 ${results.length} 条结果。`, 'success');
  } catch (error) {
    const container = getElement('search-results');
    container.className = 'result-list error-state';
    container.textContent = '检索失败，请检查筛选条件或稍后重试。';
    setFeedback('search', error instanceof Error ? error.message : '检索失败。', 'error');
    showToast('结构化检索失败。', 'error');
  }
}

async function submitChat(event) {
  event.preventDefault();
  clearFeedback('chat');
  const input = getElement('chat-input');
  const message = input.value.trim();
  if (!message) {
    setFeedback('chat', '请输入问题后再发送。', 'error');
    return;
  }

  const session = getActiveSession();
  const priorHistory = Array.isArray(session?.history) ? [...session.history] : [];
  if (session) {
    session.model = getSelectedModel();
    persistSessions();
    renderSessionList();
  }

  appendMessage('user', message);
  appendHistoryTurn('user', message);
  input.value = '';
  setStreamingState(true);
  showChatLoadingSkeleton();

  try {
    const payload = await requestNdjsonStream('/api/chat/stream', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ message, model: getSelectedModel(), history: priorHistory }),
    }, handleChatStreamEvent);

    if (payload?.answer) {
      appendHistoryTurn('assistant', payload.answer);
    }

    if (payload && Array.isArray(payload.data)) {
      if (payload.data.length > 0 && payload.data[0].patent_id) {
        renderSearchResults(payload.data);
        setFeedback('search', `已同步展示 ${payload.data.length} 条相关专利。`, 'success');
      }
    }
  } catch (error) {
    removeChatLoadingSkeleton();
    setFeedback('chat', '请求失败，请稍后重试。', 'error');
    appendMessage('assistant', '本轮请求失败，请稍后重试。');
    appendTraceBlock('错误', error instanceof Error ? error.message : '未知错误', 'error');
    showToast('聊天请求失败。', 'error');
  } finally {
    removeChatLoadingSkeleton();
    setStreamingState(false);
    input.focus();
  }
}

function handleModelChange(event) {
  const session = getActiveSession();
  if (session) {
    session.model = event.target.value;
    session.updatedAt = nowIso();
    persistSessions();
    renderSessionList();
  }
  showToast(`已切换模型：${event.target.value}`, 'info');
}

ensureSessionState();
renderSessionList();
renderCurrentSession();

getElement('search-form').addEventListener('submit', submitSearch);
getElement('chat-form').addEventListener('submit', submitChat);
getElement('new-session-button').addEventListener('click', createAndActivateSession);
getElement('model-picker')?.addEventListener('change', handleModelChange);
