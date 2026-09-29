import {
  CONTACT_METHODS,
  STATUS,
  ApiError,
  api,
  autosize,
  copyText,
  createSelect,
  formatDateTime,
  formatNumber,
  formatSeconds,
  formatTime,
  h,
  icon,
  initials,
  poll,
  relativeTime,
  setChildren,
  toast,
} from "/static/common.js";

const TOKEN_KEY = "oc-manager-token";
const CLIENT_TOKEN_KEY = "oc-client-token";
const SELECTED_KEY = "oc-manager-selected";
const MANAGER_ID = "demo-manager";
const COUNTER_FROM = 1500;
const MAX_LENGTH = 2000;
const CATEGORY_LABELS = {
  product: "Товар",
  kit: "Набор",
  delivery: "Доставка",
  payment: "Оплата",
  loyalty: "Лояльность",
  company: "О компании",
  instructions: "Инструкции",
  partnership: "Сотрудничество",
  certificates: "Сертификаты",
  other: "Прочее",
};
const FILTERS = [
  [null, "Все"],
  ["new", "Новые"],
  ["callback", "Просят связаться"],
  ["in_progress", "В работе"],
  ["waiting_client", "Ждём клиента"],
  ["closed", "Закрытые"],
];
const NEGATIVE_REASONS = ["Неверный факт", "Слишком длинно", "Сухо, шаблонно", "Неуместная допродажа", "Не ответил на вопрос"];

const $ = (selector) => document.querySelector(selector);
const els = {
  gateError: $("#gate-error"),
  console: $("#console"),
  status: $("#status"),
  awayOff: $("#away-off"),
  awayOn: $("#away-on"),
  modelChip: $("#model-chip"),
  modelList: $("#model-list"),
  stats: $("#stats"),
  search: $("#search"),
  filters: $("#filters"),
  list: $("#conv-list"),
  inboxCount: $("#inbox-count"),
  threadHead: $("#thread-head"),
  log: $("#log"),
  replyBox: $("#reply-box"),
  composer: $("#composer"),
  message: $("#message"),
  send: $("#send"),
  counter: $("#counter"),
  side: $("#side"),
};

const state = {
  token: sessionGet(),
  filter: null,
  query: "",
  list: null,
  selectedId: null,
  detail: null,
  sig: {},
  prevUnread: null,
  stops: [],
  demo: false,
  away: false,
  autoSelected: false,
};

function sessionGetKey(key) {
  try {
    return sessionStorage.getItem(key);
  } catch {
    return null;
  }
}

function sessionSetKey(key, value) {
  try {
    if (value === null) sessionStorage.removeItem(key);
    else sessionStorage.setItem(key, value);
  } catch {
    /* хранилище недоступно: состояние не сохранится между экранами */
  }
}

function sessionGet() {
  return sessionGetKey(TOKEN_KEY);
}

/** Демо: делает выбранный диалог текущим на экране клиента (тот же браузер), чтобы им можно было продолжить переписку. */
function shareWithClientScreen(token) {
  try {
    if (token && localStorage.getItem(CLIENT_TOKEN_KEY) !== token) localStorage.setItem(CLIENT_TOKEN_KEY, token);
  } catch {
    /* хранилище недоступно: экран клиента откроет свой прежний диалог */
  }
}

function sessionSet(value) {
  try {
    if (value === null) sessionStorage.removeItem(TOKEN_KEY);
    else sessionStorage.setItem(TOKEN_KEY, value);
  } catch {
    /* хранилище недоступно: код придётся вводить заново */
  }
}

/** Запрос к менеджерским эндпоинтам с кодом доступа; при 401 один раз пробует получить демо-сессию заново. */
async function managerApi(path, options = {}) {
  const request = () => api(path, { ...options, headers: { ...(options.headers || {}), "X-Manager-Token": state.token || "" } });
  try {
    return await request();
  } catch (error) {
    if (!(error instanceof ApiError && error.status === 401)) throw error;
    await openSession();
    return request();
  }
}

/* ---------- Сессия менеджера (экрана входа нет) ---------- */

/** Получает код менеджера у демо-эндпоинта; без DEMO_MODE на сервере консоль недоступна. */
async function openSession() {
  const session = await api("/api/demo/manager-session", { method: "POST" });
  state.token = session.token;
  sessionSet(session.token);
}

function showGateError(text) {
  els.gateError.textContent = text;
  els.gateError.hidden = false;
}

function enter() {
  els.gateError.hidden = true;
  renderThreadEmpty();
  renderSideEmpty();
  refreshList();
  refreshStats();
  checkStatus();
  refreshAway();
  refreshModel();
  state.stops = [poll(refreshList, 4000), poll(refreshDetail, 3000), poll(refreshStats, 15000), poll(checkStatus, 30000), poll(refreshAway, 20000), poll(refreshModel, 15000)];
}

/* ---------- Входящие ---------- */

async function refreshList() {
  const params = new URLSearchParams();
  if (state.filter) params.set("status", state.filter);
  if (state.query) params.set("q", state.query);
  const data = await managerApi(`/api/manager/conversations?${params}`).catch(() => null);
  if (!data) return;
  state.list = data;
  renderInbox();
  notifyAboutUnread(data);
  autoSelect(data);
}

/** В демо-режиме сразу открывает диалог (последний открытый или самый важный), чтобы переключение экранов не требовало кликов. */
function autoSelect(data) {
  if (!state.demo || state.selectedId || state.autoSelected || !data.items.length) return;
  state.autoSelected = true;
  const remembered = Number(sessionGetKey(SELECTED_KEY));
  const target = data.items.find((item) => item.id === remembered) || data.items[0];
  selectConversation(target.id);
}

function notifyAboutUnread(data) {
  const unread = data.items.reduce((sum, item) => sum + item.unread, 0);
  if (state.prevUnread !== null && unread > state.prevUnread) toast("Новое сообщение от клиента");
  state.prevUnread = unread;
  document.title = unread ? `(${unread}) Консоль менеджера · O-Complex` : "Консоль менеджера · O-Complex";
}

function renderInbox() {
  const { items, counts, total } = state.list;
  els.inboxCount.textContent = total ? String(total) : "";
  setChildren(
    els.filters,
    FILTERS.map(([value, label]) =>
      h(
        "button",
        {
          type: "button",
          "aria-pressed": String(state.filter === value),
          onclick: () => {
            state.filter = value;
            refreshList();
          },
        },
        label,
        h("span", { class: "n", text: String(value === null ? total : counts[value] || 0) }),
      ),
    ),
  );
  if (!items.length) {
    setChildren(els.list, h("li", { class: "list-empty", text: state.query || state.filter ? "Ничего не найдено" : "Пока нет обращений. Откройте главную страницу и напишите как клиент." }));
    return;
  }
  setChildren(
    els.list,
    items.map((item) => {
      const attention = item.status === "new" || item.status === "callback";
      return h(
        "li",
        {},
        h(
          "button",
          {
            type: "button",
            class: `conv${attention ? " attention" : ""}${item.unread ? " unread" : ""}${item.hot ? " hot" : ""}`,
            "aria-current": String(item.id === state.selectedId),
            onclick: () => selectConversation(item.id),
          },
          h("span", { class: "avatar", "aria-hidden": "true", text: initials(item.client_name) }),
          h(
            "span",
            { class: "conv-main" },
            h("span", { class: "conv-name" }, item.client_name || `Клиент №${item.id}`, item.callback_requested && icon("phone"), item.hot && h("span", { class: "hot-mark", title: "Клиент готов купить", "aria-label": "Клиент готов купить" }, icon("star"))),
            h("span", { class: "conv-preview", text: item.last_message_preview || "Без сообщений" }),
            h("span", {}, statusChip(item.status)),
          ),
          h("span", { class: "conv-side" }, h("span", { class: "conv-time", text: relativeTime(item.last_message_at) }), item.unread ? h("span", { class: "unread-badge", "aria-label": `Непрочитанных: ${item.unread}`, text: String(item.unread) }) : null),
        ),
      );
    }),
  );
}

function statusChip(status) {
  const meta = STATUS[status] || STATUS.new;
  return h("span", { class: `status-chip ${meta.tone}`, text: meta.label });
}

/* ---------- Диалог ---------- */

async function selectConversation(id) {
  state.selectedId = id;
  sessionSetKey(SELECTED_KEY, String(id));
  state.detail = null;
  state.sig = {};
  els.console.dataset.view = "thread";
  renderInbox();
  renderThreadEmpty("Загружаю диалог…");
  setChildren(els.side, h("div", { id: "client-slot" }), h("hr", { class: "divider" }), h("div", { id: "note-slot" }), h("hr", { class: "divider" }), h("div", { id: "ai-slot" }));
  await refreshDetail();
  refreshList();
}

async function refreshDetail() {
  const id = state.selectedId;
  if (!id) return;
  const detail = await managerApi(`/api/manager/conversations/${id}`).catch((error) => {
    if (error.status === 404) resetSelection();
    return null;
  });
  if (!detail || id !== state.selectedId) return;
  state.detail = detail;
  shareWithClientScreen(detail.client_token);
  const last = detail.messages.at(-1);
  const signature = {
    head: `${detail.status}|${detail.client.name}|${detail.client.created_at}`,
    messages: `${detail.messages.length}|${last?.id}`,
    client: `${detail.status}|${detail.client.name}|${detail.client.contact_method}|${detail.client.contact_value}|${detail.client.messages_count}|${detail.client.preferred_time}`,
    ai: `${detail.suggestion_state}|${detail.suggestion?.suggestion_id}`,
  };
  const changed = (key) => signature[key] !== state.sig[key];
  if (changed("head")) renderHead(detail);
  if (changed("messages")) renderMessages(detail);
  if (changed("client")) renderClientCard(detail);
  if (state.sig.note === undefined || (document.activeElement?.id !== "note" && detail.manager_note !== state.sig.note)) renderNote(detail);
  if (changed("ai")) renderAi(detail);
  Object.assign(state.sig, signature, { note: detail.manager_note });
}

function resetSelection() {
  state.selectedId = null;
  state.detail = null;
  renderThreadEmpty();
  renderSideEmpty();
  renderInbox();
}

function renderThreadEmpty(text = "Выберите диалог слева, чтобы увидеть переписку и подсказку ИИ.") {
  setChildren(els.threadHead, h("h2", { id: "thread-title", text: "Переписка" }));
  setChildren(els.log, h("li", { class: "thread-empty" }, h("div", { class: "spark" }, icon("chat")), h("b", { text: "Диалог не выбран" }), text));
  els.replyBox.hidden = true;
}

function renderSideEmpty() {
  setChildren(els.side, h("div", { class: "ai-empty" }, h("div", { class: "ai-head" }, h("h2", {}, icon("spark"), "Подсказка ИИ")), "Здесь появятся данные клиента, заметка и подсказка ИИ к его последнему сообщению."));
}

function renderHead(detail) {
  const name = detail.client.name || `Клиент №${detail.id}`;
  const menu = statusMenu(detail.status, setStatus);
  setChildren(
    els.threadHead,
    h(
      "div",
      { class: "thread-title" },
      h("button", { type: "button", class: "icon-btn back", "aria-label": "К списку", onclick: () => (els.console.dataset.view = "list") }, icon("back")),
      h("span", { class: "avatar", "aria-hidden": "true", text: initials(detail.client.name) }),
      h("div", { style: "min-width: 0" }, h("b", { id: "thread-title", text: name }), h("small", { text: `Веб-чат · с ${formatDateTime(detail.client.created_at)}` })),
    ),
    h(
      "div",
      { class: "thread-actions" },
      menu,
      detail.status === "closed"
        ? h("button", { type: "button", class: "ghost", onclick: () => setStatus("in_progress") }, "Открыть заново")
        : h("button", { type: "button", class: "ghost", onclick: () => setStatus("closed") }, "Закрыть"),
    ),
  );
  els.replyBox.hidden = false;
}

/** Выпадающий список статусов диалога. */
function statusMenu(current, onSelect) {
  const options = Object.entries(STATUS).map(([value, meta]) => ({ value, label: meta.label, tone: meta.tone }));
  return createSelect({ options, value: current, ariaLabel: "Статус диалога", onChange: onSelect }).node;
}

function dayLabel(value) {
  const date = new Date(value);
  const today = new Date();
  const yesterday = new Date(Date.now() - 86_400_000);
  if (date.toDateString() === today.toDateString()) return "Сегодня";
  if (date.toDateString() === yesterday.toDateString()) return "Вчера";
  return date.toLocaleDateString("ru-RU", { day: "numeric", month: "long" });
}

function renderMessages(detail) {
  const nearBottom = els.log.scrollHeight - els.log.scrollTop - els.log.clientHeight < 80 || state.sig.messages === undefined;
  const nodes = [];
  let day = null;
  for (const message of detail.messages) {
    const label = dayLabel(message.created_at);
    if (label !== day) {
      nodes.push(h("li", { class: "date-sep", text: label }));
      day = label;
    }
    if (message.sender === "system") {
      nodes.push(h("li", { class: "sys", text: message.text }));
      continue;
    }
    const fromClient = message.sender === "client";
    nodes.push(
      h(
        "li",
        { class: `msg ${message.sender}` },
        h("span", { class: "avatar", "aria-hidden": "true", text: fromClient ? initials(detail.client.name) : message.auto ? "ИИ" : "М" }),
        h(
          "div",
          { class: "msg-body" },
          h("div", { class: "bubble", text: message.text }),
          h(
            "div",
            { class: "msg-meta" },
            h("time", { text: formatTime(message.created_at) }),
            !fromClient && icon("checks"),
            !fromClient && message.auto ? h("span", { class: "tag", text: "автоответ ассистента" }) : null,
            !fromClient && !message.auto && message.suggestion_id ? h("span", { class: "tag", text: message.edited ? "по подсказке ИИ, с правками" : "по подсказке ИИ" }) : null,
          ),
        ),
      ),
    );
  }
  if (!detail.messages.length) nodes.push(h("li", { class: "thread-empty" }, h("b", { text: "Сообщений пока нет" }), "Клиент оставил только запрос на связь."));
  setChildren(els.log, nodes);
  if (nearBottom) els.log.scrollTop = els.log.scrollHeight;
}

async function setStatus(status) {
  if (!state.selectedId) return;
  try {
    await managerApi(`/api/manager/conversations/${state.selectedId}/status`, { body: { status } });
    toast(`Статус: ${STATUS[status].label}`);
    await refreshDetail();
    refreshList();
  } catch (error) {
    toast(error.message);
  }
}

async function sendReply(text, suggestionId = null) {
  const value = text.trim();
  if (!value || !state.selectedId) return false;
  try {
    await managerApi(`/api/manager/conversations/${state.selectedId}/messages`, { body: { text: value, suggestion_id: suggestionId } });
    toast("Ответ отправлен клиенту");
    await refreshDetail();
    refreshList();
    return true;
  } catch (error) {
    toast(error.message);
    return false;
  }
}

/* ---------- Карточка клиента и заметка ---------- */

function contactLink(method, value) {
  const digits = value.replace(/\D/g, "");
  if (method === "phone") return `tel:+${digits}`;
  if (method === "whatsapp") return `https://wa.me/${digits}`;
  if (method === "email") return `mailto:${encodeURIComponent(value).replace("%40", "@")}`;
  if (method === "telegram") {
    const nick = value.replace(/^@/, "");
    return /^[A-Za-z0-9_]+$/.test(nick) ? `https://t.me/${nick}` : `https://t.me/+${digits}`;
  }
  return null;
}

function renderClientCard(detail) {
  const slot = $("#client-slot");
  if (!slot) return;
  const c = detail.client;
  const link = c.contact_value ? contactLink(c.contact_method, c.contact_value) : null;
  setChildren(
    slot,
    h(
      "div",
      { class: "client-card" },
      h("h3", { text: "Клиент" }),
      h("div", { class: "client-head" }, h("span", { class: "avatar", "aria-hidden": "true", text: initials(c.name) }), h("div", {}, h("b", { text: c.name || `Клиент №${detail.id}` }), h("small", { text: c.channel === "web" ? "Веб-чат" : c.channel }))),
      c.contact_requested_at
        ? h(
            "div",
            { class: "callback-box" },
            h("h3", {}, icon("phone"), "Просит связаться"),
            h(
              "div",
              { class: "contact-line" },
              h("span", { text: CONTACT_METHODS[c.contact_method]?.label || "" }),
              c.contact_value ? h("b", {}, link ? h("a", { href: link, target: "_blank", rel: "noopener noreferrer", text: c.contact_value }) : c.contact_value) : h("b", { text: "ответить в чате" }),
              c.contact_value && h("button", { type: "button", class: "ghost", onclick: () => copyText(c.contact_value) }, icon("copy"), "Копировать"),
            ),
            h("div", { text: `Удобное время: ${c.preferred_time || "не указано"}` }),
            c.contact_comment && h("div", { text: `Комментарий: ${c.contact_comment}` }),
            h("small", { text: `Запрос от ${formatDateTime(c.contact_requested_at)}` }),
          )
        : null,
      h(
        "dl",
        { class: "facts-grid" },
        h("dt", { text: "Сообщений" }), h("dd", { text: `${c.messages_count} (клиент: ${c.client_messages_count})` }),
        h("dt", { text: "Начало" }), h("dd", { text: formatDateTime(c.created_at) }),
        h("dt", { text: "Статус" }), h("dd", {}, statusChip(detail.status)),
        h("dt", { text: "Диалог №" }), h("dd", { text: String(detail.id) }),
      ),
    ),
  );
}

function renderNote(detail) {
  const slot = $("#note-slot");
  if (!slot) return;
  const area = h("textarea", { id: "note", maxlength: "2000", "aria-label": "Внутренняя заметка", placeholder: "Например: перезвонить после 18:00, интересует опт" });
  area.value = detail.manager_note || "";
  const saved = h("span", { class: "saved", role: "status" });
  let original = area.value;
  const save = async () => {
    if (area.value === original) return;
    try {
      await managerApi(`/api/manager/conversations/${detail.id}/note`, { method: "PUT", body: { note: area.value } });
      original = area.value;
      state.sig.note = area.value;
      saved.textContent = "Сохранено";
      setTimeout(() => (saved.textContent = ""), 1800);
    } catch (error) {
      toast(error.message);
    }
  };
  area.addEventListener("blur", save);
  setChildren(slot, h("div", { class: "note-block" }, h("h3", {}, "Заметка менеджера ", h("span", { class: "lock-note" }, icon("lock"), "клиент не видит")), area, h("div", { class: "note-row" }, h("button", { type: "button", class: "ghost", onclick: save }, icon("note"), "Сохранить"), saved)));
}

/* ---------- Подсказка ИИ ---------- */

const MODEL_PROBLEMS = {
  rate_limit: "Лимит модели исчерпан",
  budget: "Дневной лимит запросов исчерпан",
  unavailable: "Модель недоступна",
};

function shortModel(name) {
  return String(name || "").split("/").pop();
}

/** Шапка показывает, какая модель подключена и работает ли она; клик открывает выбор модели. */
async function refreshModel() {
  try {
    renderModel(await managerApi("/api/manager/model-status"));
  } catch {
    /* связь пропала: оставляем последнее известное состояние */
  }
}

function renderModel(s) {
  const prompt = s.prompt_version ? ` · промпт ${s.prompt_version}` : "";
  let text;
  let tone = "ok";
  if (s.state === "offline") {
    text = "Офлайн-режим: ИИ не подключён";
    tone = "warn";
  } else if (MODEL_PROBLEMS[s.state]) {
    text = `${MODEL_PROBLEMS[s.state]} · ${s.selected ? shortModel(s.selected) : "все модели"}`;
    tone = "bad";
  } else if (s.selected) {
    // выбрана вручную: если она не ответила, показываем, какая ответила вместо неё
    const instead = s.last_model && s.last_model !== s.selected ? ` → ${shortModel(s.last_model)}` : "";
    text = `${shortModel(s.selected)}${instead}${prompt}`;
  } else {
    text = `Авто · ${shortModel(s.last_model || s.model)}${prompt}`;
  }
  els.modelChip.textContent = text;
  els.modelChip.className = `model-chip on ${tone}`;
  const mode = s.selected ? `Выбрана вручную: ${shortModel(s.selected)}` : `Авто: сначала ${shortModel(s.model)}, затем остальные`;
  const last = s.last_model ? `Последний ответ дала ${shortModel(s.last_model)}` : "Свежих ответов модели ещё не было";
  els.modelChip.title = `${mode}. ${last}${s.checked_at ? ` (${formatDateTime(s.checked_at)})` : ""}. Нажмите, чтобы выбрать модель`;
  lastModelStatus = s;
  if (els.modelList.hidden) renderModelOptions(s); // открытый список не перерисовываем
}

let lastModelStatus = null;

function modelState(info) {
  const minutes = info.retry_in ? Math.max(1, Math.ceil(info.retry_in / 60)) : null;
  switch (info.state) {
    case "ok":
      return { dot: "ok", text: "работает" };
    case "rate_limit":
      return { dot: "bad", text: minutes ? `лимит, ещё ~${minutes} мин` : "лимит исчерпан" };
    case "limit_expired":
      return { dot: "orange", text: "лимит мог освободиться" };
    case "unavailable":
      return { dot: "bad", text: "недоступна" };
    case "bad_format":
      return { dot: "orange", text: "ответ не по формату" };
    default:
      return { dot: "muted", text: "не проверялась" };
  }
}

function renderModelOptions(s) {
  const options = [
    { value: "", label: "Авто: основная, затем запасные", status: null },
    ...s.models.map((m) => ({ value: m, label: shortModel(m) + (m === s.model ? " · основная" : ""), status: modelState((s.per_model || {})[m] || { state: "unknown" }) })),
  ];
  const current = s.selected || "";
  setChildren(
    els.modelList,
    options.map((option) =>
      h(
        "li",
        { role: "option", tabindex: "-1", "aria-selected": String(option.value === current), onclick: () => chooseModel(option.value) },
        option.status ? h("i", { class: `dot ${option.status.dot}`, "aria-hidden": "true" }) : null,
        h("span", { text: option.label }),
        option.status ? h("small", { class: "menu-status", text: option.status.text }) : null,
        option.value === current ? icon("check") : null,
      ),
    ),
  );
}

function closeModelMenu(returnFocus = true) {
  els.modelList.hidden = true;
  els.modelChip.setAttribute("aria-expanded", "false");
  if (returnFocus) els.modelChip.focus();
}

async function chooseModel(value) {
  closeModelMenu();
  try {
    renderModel(await managerApi("/api/manager/model", { method: "PUT", body: { model: value || null } }));
    toast(value ? `Модель: ${shortModel(value)}` : "Модель: автоматический выбор");
  } catch (error) {
    toast(error.message);
  }
}

els.modelChip.addEventListener("click", () => {
  if (!els.modelList.hidden) return closeModelMenu();
  if (lastModelStatus) renderModelOptions(lastModelStatus); // актуальные статусы на момент открытия
  els.modelList.hidden = false;
  els.modelChip.setAttribute("aria-expanded", "true");
  (els.modelList.querySelector('[aria-selected="true"]') || els.modelList.firstElementChild)?.focus();
});
els.modelList.addEventListener("keydown", (event) => {
  const items = [...els.modelList.children];
  const index = items.indexOf(document.activeElement);
  if (event.key === "ArrowDown") items[(index + 1) % items.length].focus();
  else if (event.key === "ArrowUp") items[(index - 1 + items.length) % items.length].focus();
  else if (event.key === "Enter" || event.key === " ") items[index]?.click();
  else if (event.key === "Escape") closeModelMenu();
  else return;
  event.preventDefault();
});
document.addEventListener("pointerdown", (event) => {
  if (!els.modelList.hidden && !els.modelList.parentElement.contains(event.target)) closeModelMenu(false);
});

function aiHeader() {
  return h("div", { class: "ai-head" }, h("h2", {}, icon("spark"), "Подсказка ИИ"), h("span", { class: "lock-note" }, icon("lock"), "только для менеджера"));
}

function renderAi(detail) {
  const slot = $("#ai-slot");
  if (!slot) return;
  const regenerate = h("button", { type: "button", class: "ghost", onclick: () => regenerateSuggestion() }, icon("refresh"), "Обновить подсказку");
  if (detail.suggestion_state === "none") {
    setChildren(slot, aiHeader(), h("div", { class: "ai-empty", text: "Подсказка появится, когда клиент напишет сообщение." }));
    return;
  }
  if (detail.suggestion_state === "pending") {
    const line = (width) => h("div", { class: "sk-line", style: width ? `width: ${width}` : null });
    setChildren(slot, aiHeader(), h("div", { class: "loading", role: "status" }, h("p", { class: "loading-note", text: "Готовлю подсказку к последнему сообщению клиента…" }), h("div", { class: "sk-card" }, line("30%"), line(), line("80%")), h("div", { class: "sk-card" }, line("40%"), line())));
    return;
  }
  if (detail.suggestion_state === "failed" || !detail.suggestion) {
    setChildren(slot, aiHeader(), h("div", { class: "block error", role: "alert" }, h("h3", { text: "Подсказку подготовить не удалось" }), h("p", { text: "Модель недоступна или исчерпан лимит. Ответьте клиенту вручную или повторите попытку." }), h("div", { class: "actions" }, regenerate)));
    return;
  }
  const data = detail.suggestion;
  const warnings = data.warnings.length ? h("div", { class: "block warn", role: "note" }, h("h3", { text: "Проверьте перед отправкой" }), h("ul", {}, data.warnings.map((warning) => h("li", { text: warning })))) : null;
  setChildren(slot, aiHeader(), badgesFor(data), factsRow(data), ...suggestionBlocks(data, { interactive: true }), warnings, sourcesBlock(data), feedbackBlock(data), h("div", { class: "actions" }, regenerate, h("button", { type: "button", class: "ghost", id: "compare", onclick: () => compareWithoutRag() }, "Сравнить без базы знаний")), metaBlock(data), h("div", { id: "compare-slot" }));
}

async function regenerateSuggestion() {
  const slot = $("#ai-slot");
  if (!slot || !state.selectedId) return;
  const id = state.selectedId;
  setChildren(slot, aiHeader(), h("div", { class: "ai-empty", role: "status", text: "Готовлю подсказку…" }));
  try {
    await managerApi(`/api/manager/conversations/${id}/suggestion`, { method: "POST" });
    state.sig.ai = undefined;
    await refreshDetail();
  } catch (error) {
    setChildren(slot, aiHeader(), h("div", { class: "block error", role: "alert" }, h("p", { text: error.message }), h("div", { class: "actions" }, h("button", { type: "button", class: "ghost", onclick: () => regenerateSuggestion() }, icon("refresh"), "Повторить"))));
  }
}

function badgesFor(data) {
  const badges = [];
  if (data.mode === "no_rag") badges.push(h("span", { class: "badge demo", text: "Без базы знаний (демо)" }));
  if (data.mode === "offline") badges.push(h("span", { class: "badge neutral", text: "Офлайн-режим без ИИ" }));
  if (data.priority) badges.push(h("span", { class: "badge priority" }, icon("star"), "Клиент готов купить"));
  if (data.needs_escalation) badges.push(h("span", { class: "badge escalate", text: "Нужен менеджер или врач" }));
  if (data.cache_status === "hit") badges.push(h("span", { class: "badge cache", text: "Из кеша · 0 токенов" }));
  return badges.length ? h("div", { class: "badges" }, badges) : null;
}

function factsRow(data) {
  const used = data.sources.filter((source) => source.used).length;
  const tokens = data.usage.tokens_in + data.usage.tokens_out;
  return h(
    "div",
    { class: "facts" },
    h("span", {}, icon("clock"), formatSeconds(data.usage.latency_ms)),
    h("span", {}, icon("coins"), `${formatNumber(tokens)} токенов`),
    data.sources.length ? h("span", {}, icon("book"), `источников: ${used} из ${data.sources.length}`) : null,
  );
}

function relevance(score) {
  if (score === null || score === undefined) return { pct: 0, label: "найдено по ключевым словам" };
  const pct = Math.max(6, Math.min(100, Math.round(((score - 0.7) / 0.25) * 100)));
  return { pct, label: `схожесть ${score.toFixed(2).replace(".", ",")}` };
}

function sourcesBlock(data) {
  if (!data.sources.length) return null;
  const ordered = [...data.sources].sort((a, b) => Number(b.used) - Number(a.used));
  return h(
    "div",
    { class: "block" },
    h("h3", {}, "Источники из базы знаний", h("span", { class: "right", text: "клик — страница на сайте" })),
    h(
      "div",
      { class: "sources" },
      ordered.map((source) => {
        const { pct, label } = relevance(source.dense_score);
        return h(
          "a",
          { class: `source-card${source.used ? " used" : ""}`, href: source.source_url, target: "_blank", rel: "noopener noreferrer", title: source.used ? "Использовано в ответе" : "Найдено, но не использовано" },
          h("div", { class: "source-top" }, h("span", { class: "cat" }, source.used ? icon("check") : icon("book"), CATEGORY_LABELS[source.category] || "Прочее"), icon("ext")),
          h("div", { class: "source-title", text: source.title }),
          h("div", { class: "score" }, h("span", { class: "bar", "aria-hidden": "true" }, h("i", { style: `width: ${pct}%` })), h("span", { text: label })),
        );
      }),
    ),
  );
}

function suggestionBlocks(data, { interactive }) {
  const original = data.reply;
  const reply = h("textarea", { "aria-label": "Ответ клиенту, можно отредактировать", spellcheck: "true" });
  reply.value = original;
  const edited = h("span", { class: "tag", text: "изменено", hidden: true });
  const count = h("span", { class: "tnum" });
  const undo = h("button", { type: "button", class: "ghost", hidden: true, onclick: () => { reply.value = original; refresh(); } }, icon("undo"), "Вернуть исходный");
  const grow = () => {
    reply.style.height = "auto";
    reply.style.height = `${reply.scrollHeight + 2}px`;
  };
  const refresh = () => {
    grow();
    const changed = reply.value !== original;
    edited.hidden = !changed;
    undo.hidden = !changed;
    count.textContent = `${reply.value.length} симв.`;
  };
  requestAnimationFrame(() => {
    refresh();
    setTimeout(refresh, 150);
  });
  reply.addEventListener("input", refresh);
  const copy = h("button", { type: "button", class: "ghost", onclick: () => copyText(reply.value) }, icon("copy"), "Копировать");
  const sendButton = interactive
    ? h(
        "button",
        {
          type: "button",
          class: "primary",
          onclick: async (event) => {
            const button = event.currentTarget;
            button.disabled = true;
            if (await sendReply(reply.value, data.suggestion_id)) setChildren(button, icon("check"), "Отправлено");
            else button.disabled = false;
          },
        },
        icon("send"),
        "Отправить клиенту",
      )
    : null;
  if (interactive) {
    reply.addEventListener("keydown", (event) => {
      if (event.key === "Enter" && (event.ctrlKey || event.metaKey)) {
        event.preventDefault();
        sendButton.click();
      }
    });
  }
  return [
    h("div", { class: "block reply" }, h("h3", {}, "Ответ клиенту", h("span", { class: "right" }, edited, count)), reply, h("div", { class: "actions" }, sendButton, copy, undo, interactive && h("span", { class: "hint" }, h("kbd", { text: "Ctrl" }), " + ", h("kbd", { text: "Enter" })))),
    h("div", { class: "block upsell" }, h("h3", {}, "Подсказка по допродаже", h("span", { class: "right" }, icon("lock"), "только для менеджера")), h("p", { text: data.upsell_hint })),
  ];
}

function feedbackBlock(data) {
  if (!data.suggestion_id) return null;
  const box = h("div", { class: "feedback" });
  const up = h("button", { type: "button", class: "icon-btn", "aria-label": "Подсказка полезна", "aria-pressed": "false" }, icon("up"));
  const down = h("button", { type: "button", class: "icon-btn", "aria-label": "Подсказка не подошла", "aria-pressed": "false" }, icon("down"));
  const status = h("span", { role: "status" });
  let form = null;
  let reasonsNode = null;
  const chosen = new Set();
  const submit = async (rating, comment) => {
    up.disabled = down.disabled = true;
    try {
      await managerApi("/api/feedback", { body: { suggestion_id: data.suggestion_id, rating, comment: comment || null, manager_id: MANAGER_ID } });
      status.className = "thanks";
      setChildren(status, icon("check"), "Спасибо, оценка сохранена");
      (rating === 1 ? up : down).setAttribute("aria-pressed", "true");
      form?.remove();
      reasonsNode?.remove();
    } catch (error) {
      status.className = "";
      status.textContent = error.message;
      up.disabled = down.disabled = false;
    }
  };
  up.addEventListener("click", () => submit(1));
  down.addEventListener("click", () => {
    if (form) return;
    const input = h("input", { type: "text", maxlength: "900", placeholder: "Что не так? (необязательно)", "aria-label": "Комментарий к оценке" });
    reasonsNode = h(
      "div",
      { class: "reasons", role: "group", "aria-label": "Причина" },
      NEGATIVE_REASONS.map((reason) =>
        h("button", {
          type: "button",
          "aria-pressed": "false",
          text: reason,
          onclick: (event) => {
            const on = event.currentTarget.getAttribute("aria-pressed") !== "true";
            event.currentTarget.setAttribute("aria-pressed", String(on));
            if (on) chosen.add(reason);
            else chosen.delete(reason);
          },
        }),
      ),
    );
    form = h("form", { class: "feedback-form", onsubmit: (event) => { event.preventDefault(); submit(-1, `${chosen.size ? `[${[...chosen].join("; ")}] ` : ""}${input.value.trim()}`.trim()); } }, input, h("button", { type: "submit", class: "primary" }, "Отправить"));
    box.append(reasonsNode, form);
    input.focus();
  });
  box.append(h("span", { text: "Подсказка полезна?" }), up, down, status);
  return box;
}

function metaBlock(data) {
  return h(
    "details",
    { class: "meta" },
    h("summary", { text: "Как ИИ рассуждал и сколько это стоило" }),
    h("p", { class: "analysis", text: data.analysis || "—" }),
    h("dl", {}, h("dt", { text: "Модель" }), h("dd", { text: data.model }), h("dt", { text: "Промпт" }), h("dd", { text: data.prompt_version }), h("dt", { text: "Токены" }), h("dd", { text: `${formatNumber(data.usage.tokens_in)} на входе, ${formatNumber(data.usage.tokens_out)} на выходе` }), h("dt", { text: "Время" }), h("dd", { text: formatSeconds(data.usage.latency_ms) }), h("dt", { text: "Кеш" }), h("dd", { text: data.cache_status === "hit" ? "ответ из кеша" : "сгенерирован заново" }), h("dt", { text: "Подсказка №" }), h("dd", { text: data.suggestion_id ? String(data.suggestion_id) : "не сохранена" })),
  );
}

async function compareWithoutRag() {
  const detail = state.detail;
  const button = $("#compare");
  const slot = $("#compare-slot");
  if (!detail || !button || !slot) return;
  const lastIndex = detail.messages.findLastIndex((message) => message.sender === "client");
  if (lastIndex < 0) return;
  const history = detail.messages
    .slice(0, lastIndex)
    .filter((message) => message.sender !== "system")
    .map(({ sender, text }) => ({ role: sender, text }))
    .slice(-20);
  button.disabled = true;
  button.textContent = "Считаю…";
  try {
    const data = await managerApi("/api/analyze", { body: { message: detail.messages[lastIndex].text, history, lead_id: `chat-${detail.id}`, mode: "no_rag" } });
    setChildren(slot, h("div", { class: "compare" }, h("div", { class: "compare-title", text: "Без базы знаний — модель отвечает по общим знаниям" }), badgesFor(data), factsRow(data), ...suggestionBlocks(data, { interactive: false }), data.warnings.length ? h("div", { class: "block warn" }, h("h3", { text: "Проверьте перед отправкой" }), h("ul", {}, data.warnings.map((warning) => h("li", { text: warning })))) : null));
    button.remove();
  } catch (error) {
    button.disabled = false;
    button.textContent = "Сравнить без базы знаний";
    setChildren(slot, h("div", { class: "block error", role: "alert" }, h("p", { text: error.message })));
  }
}

/* ---------- Режим «менеджер ушёл» ---------- */

let awayBusy = false;

function renderAway() {
  els.awayOff.setAttribute("aria-pressed", String(!state.away));
  els.awayOn.setAttribute("aria-pressed", String(state.away));
}

async function refreshAway() {
  if (awayBusy) return;
  try {
    state.away = (await managerApi("/api/manager/away")).enabled;
    renderAway();
  } catch {
    /* связь пропала: оставляем последнее известное состояние */
  }
}

async function setAway(next) {
  if (next === state.away || awayBusy) return;
  awayBusy = true;
  try {
    state.away = (await managerApi("/api/manager/away", { method: "PUT", body: { enabled: next } })).enabled;
    renderAway();
    toast(state.away ? "Отвечает ассистент: он сам ответит на все входящие" : "Отвечаете вы: ассистент молчит");
  } catch (error) {
    toast(error.message);
  } finally {
    awayBusy = false;
  }
}

/* ---------- Статистика и связь ---------- */

async function refreshStats() {
  try {
    const s = await managerApi("/api/stats");
    const pill = (label, value, hint) => h("li", { title: hint }, `${label}: `, h("b", { text: value }));
    setChildren(els.stats, pill("Сегодня", `${formatNumber(s.requests_total)} подсказ.`, "Выдано подсказок за сутки"), pill("Из кеша", `${Math.round(s.cache_hit_ratio * 100)}%`, "Доля ответов без вызова модели"), pill("Токенов", formatNumber(s.tokens_in + s.tokens_out), "Потрачено токенов за сутки"));
  } catch {
    setChildren(els.stats);
  }
}

async function checkStatus() {
  try {
    await api("/health");
    els.status.className = "status ok";
    setChildren(els.status, h("i"), h("span", { text: "Онлайн" }));
  } catch {
    els.status.className = "status bad";
    setChildren(els.status, h("i"), h("span", { text: "Нет связи" }));
  }
}

/* ---------- Инициализация ---------- */

function updateComposer() {
  autosize(els.message);
  const length = els.message.value.length;
  els.counter.classList.toggle("on", length >= COUNTER_FROM);
  els.counter.classList.toggle("warn", length >= MAX_LENGTH - 100);
  els.counter.textContent = `${formatNumber(length)} / ${formatNumber(MAX_LENGTH)}`;
}

els.awayOff.addEventListener("click", () => setAway(false));
els.awayOn.addEventListener("click", () => setAway(true));
els.search.addEventListener("input", () => {
  state.query = els.search.value.trim();
  refreshList();
});
els.composer.addEventListener("submit", async (event) => {
  event.preventDefault();
  els.send.disabled = true;
  if (await sendReply(els.message.value)) {
    els.message.value = "";
    updateComposer();
  }
  els.send.disabled = false;
});
els.message.addEventListener("keydown", (event) => {
  if (event.key === "Enter" && !event.shiftKey && !event.isComposing) {
    event.preventDefault();
    els.composer.requestSubmit();
  }
});
els.message.addEventListener("input", updateComposer);
setChildren(els.send, icon("send"), "Отправить");

async function start() {
  try {
    const config = await api("/api/demo/config");
    state.demo = config.enabled;
  } catch {
    state.demo = false;
  }
  try {
    await openSession();
  } catch {
    showGateError("Консоль недоступна: на сервере выключен демо-режим (DEMO_MODE=true), а отдельного входа больше нет.");
    return;
  }
  enter();
}

await start();
