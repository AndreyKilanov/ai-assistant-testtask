import {
  CONTACT_METHODS,
  api,
  attachPhoneMask,
  autosize,
  createSelect,
  formatNumber,
  forbidEmoji,
  formatTime,
  h,
  icon,
  isValidRuPhone,
  poll,
  setChildren,
  toast,
} from "/static/common.js";

const TOKEN_KEY = "oc-client-token";
const MAX_LENGTH = 2000;
const COUNTER_FROM = 1500;
const POLL_MS = 2500;
const QUICK_QUESTIONS = ["Сколько стоит цеолит Макс?", "Есть ли доставка в мой город?", "Как оплатить заказ?", "Что такое O-Complex?"];
const STATE_TEXT = {
  new: "Менеджер скоро ответит",
  in_progress: "Менеджер читает ваше сообщение",
  waiting_client: "Менеджер ответил — ждём вас",
  callback: "Запрос на связь принят",
  closed: "Диалог завершён — напишите, если остались вопросы",
};

const $ = (selector) => document.querySelector(selector);
const els = {
  log: $("#log"),
  quick: $("#quick"),
  composer: $("#composer"),
  message: $("#message"),
  send: $("#send"),
  counter: $("#counter"),
  status: $("#status"),
  chatState: $("#chat-state"),
  newChat: $("#new-chat"),
  newChatDialog: $("#new-chat-dialog"),
  callbackCard: $("#callback-card"),
  openContact: $("#open-contact"),
  dialog: $("#contact-dialog"),
  form: $("#contact-form"),
  methods: $("#c-methods"),
  valueField: $("#c-value-field"),
  valueLabel: $("#c-value-label"),
  value: $("#c-value"),
  name: $("#c-name"),
  timeSlot: $("#c-time-slot"),
  valueError: $("#c-value-error"),
  comment: $("#c-comment"),
  error: $("#c-error"),
  submit: $("#contact-submit"),
};

const TIME_OPTIONS = ["Как можно скорее", "Сегодня в течение дня", "Завтра утром", "Вечером"].map((label) => ({ value: label, label }));
const timeSelect = createSelect({ options: TIME_OPTIONS, value: TIME_OPTIONS[0].value, ariaLabel: "Когда удобно", block: true });
els.timeSlot.append(timeSelect.node);
const PHONE_METHODS = new Set(["phone", "whatsapp", "max"]);
const TELEGRAM_NICK_RE = /^@?[A-Za-z0-9_]{5,32}$/;
const EMAIL_RE = /^[^@\s]+@[^@\s]+\.[^@\s]{2,}$/;

const state = {
  token: safeGet(TOKEN_KEY),
  messages: [],
  lastId: 0,
  status: "new",
  contactRequested: false,
  busy: false,
  unseen: 0,
  method: "phone",
  botMode: false,
};

function safeGet(key) {
  try {
    return localStorage.getItem(key);
  } catch {
    return null;
  }
}

function safeSet(key, value) {
  try {
    if (value === null) localStorage.removeItem(key);
    else localStorage.setItem(key, value);
  } catch {
    /* хранилище недоступно: диалог останется только на этой странице */
  }
}

/* ---------- Сообщения ---------- */

function contactActions() {
  return h(
    "div",
    { class: "quick-actions", role: "group", "aria-label": "Как с вами связаться" },
    Object.entries(CONTACT_METHODS).map(([key, method]) =>
      h("button", { type: "button", onclick: () => {
        state.method = key;
        openContact();
      } }, method.label),
    ),
  );
}

function linkButtons(links) {
  return h(
    "div",
    { class: "quick-actions", role: "group", "aria-label": "Ссылки на сайт" },
    links.map((link) => h("a", { class: "link-btn", href: link.url, target: "_blank", rel: "noopener noreferrer" }, h("span", { text: link.title }), icon("ext"))),
  );
}

function messageNode(message) {
  if (message.sender === "system") return h("li", { class: "sys", text: message.text });
  const mine = message.sender === "client";
  return h(
    "li",
    { class: `msg ${mine ? "me" : "them"}` },
    !mine && h("span", { class: "avatar", "aria-hidden": "true", text: message.auto ? "ИИ" : "М" }),
    h(
      "div",
      { class: "msg-body" },
      !mine && h("span", { class: "who", text: message.auto ? "Ассистент O-Complex (ИИ)" : "Менеджер O-Complex" }),
      h("div", { class: "bubble", text: message.text }),
      !mine && !state.contactRequested && message.actions?.includes("contact_methods") ? contactActions() : null,
      !mine && message.links?.length ? linkButtons(message.links) : null,
      h("div", { class: "msg-meta" }, h("time", { text: formatTime(message.created_at) }), mine && icon("checks")),
    ),
  );
}

function helloNode() {
  return h(
    "li",
    { class: "msg them brand-hello" },
    h("span", { class: "avatar", "aria-hidden": "true", text: "O" }),
    h(
      "div",
      { class: "msg-body" },
      h("span", { class: "who", text: "O-Complex" }),
      h("div", {
        class: "bubble",
        text: "Здравствуйте! Задайте вопрос о продуктах, доставке или оплате — менеджер ответит вам здесь. Если удобнее по телефону или в мессенджере, нажмите «Связаться с менеджером».",
      }),
    ),
  );
}

/** Клиент ждёт ответа, пока последнее сообщение в чате — его собственное. */
function awaitingReply() {
  return state.messages.at(-1)?.sender === "client";
}

function pendingNode() {
  const bot = state.botMode;
  return h(
    "li",
    { class: "msg them pending", role: "status" },
    h("span", { class: "avatar", "aria-hidden": "true", text: bot ? "ИИ" : "М" }),
    h(
      "div",
      { class: "msg-body" },
      h("span", { class: "who", text: bot ? "Ассистент O-Complex (ИИ)" : "Менеджер O-Complex" }),
      h(
        "div",
        { class: "bubble" },
        h("span", { text: bot ? "Ассистент готовит ответ" : "Ожидайте ответа менеджера" }),
        h("span", { class: "dots", "aria-hidden": "true" }, h("i"), h("i"), h("i")),
      ),
    ),
  );
}

/** Запоминает, кто сейчас отвечает (менеджер или бот), и обновляет подпись ожидания. */
function setBotMode(value) {
  const next = Boolean(value);
  if (next === state.botMode) return;
  state.botMode = next;
  renderLog();
}

function renderLog() {
  setChildren(els.log, helloNode(), state.messages.map(messageNode), awaitingReply() ? pendingNode() : null);
  els.log.scrollTop = els.log.scrollHeight;
  setChildren(els.quick, state.messages.length ? [] : QUICK_QUESTIONS.map((question) => h("button", { type: "button", onclick: () => send(question) }, question)));
}

function appendMessages(newMessages) {
  const fresh = newMessages.filter((message) => message.id > state.lastId);
  if (!fresh.length) return;
  state.messages.push(...fresh);
  state.lastId = fresh[fresh.length - 1].id;
  const fromManager = fresh.filter((message) => message.sender !== "client");
  if (fromManager.length && document.hidden) {
    state.unseen += fromManager.length;
    document.title = `(${state.unseen}) Новое сообщение · O-Complex`;
  }
  renderLog();
}

function renderState(status) {
  state.status = status;
  els.chatState.textContent = STATE_TEXT[status] || STATE_TEXT.new;
  renderCallbackCard();
  updateNewChatButton();
}

function renderCallbackCard() {
  setChildren(
    els.callbackCard,
    state.contactRequested
      ? [
          h("div", { class: "callback-ok" }, icon("check"), "Запрос на связь принят"),
          h("p", { text: "Менеджер свяжется с вами выбранным способом. Пока можно продолжать переписку здесь." }),
        ]
      : [
          h("h2", { text: "Нужен живой разговор?" }),
          h("p", { class: "address", text: "Оставьте телефон, Telegram, WhatsApp или email — менеджер свяжется с вами." }),
          h("button", { type: "button", class: "ghost", onclick: openContact }, icon("phone"), "Оставить контакт"),
        ],
  );
  setChildren(els.openContact, icon("phone"), h("span", { text: state.contactRequested ? "Запрос отправлен" : "Связаться с менеджером" }));
  els.openContact.disabled = state.contactRequested;
}

/* ---------- Отправка ---------- */

async function ensureConversation(firstText = null) {
  if (state.token) return null;
  const session = await api("/api/chat/conversations", { body: { text: firstText } });
  state.token = session.token;
  safeSet(TOKEN_KEY, session.token);
  return session;
}

async function send(text) {
  const value = text.trim();
  if (!value || state.busy) return;
  state.busy = true;
  els.send.disabled = true;
  try {
    const session = await ensureConversation(value);
    if (session) {
      state.botMode = Boolean(session.bot_mode);
      appendMessages(session.messages);
      renderState(session.status);
    } else {
      const message = await api(`/api/chat/conversations/${state.token}/messages`, { body: { text: value } });
      appendMessages([message]);
    }
    els.message.value = "";
    updateComposer();
  } catch (error) {
    toast(error.message);
  } finally {
    state.busy = false;
    els.send.disabled = false;
    els.message.focus();
  }
}

function updateComposer() {
  autosize(els.message);
  const length = els.message.value.length;
  els.counter.classList.toggle("on", length >= COUNTER_FROM);
  els.counter.classList.toggle("warn", length >= MAX_LENGTH - 100);
  els.counter.textContent = `${formatNumber(length)} / ${formatNumber(MAX_LENGTH)}`;
}

/* ---------- Синхронизация ---------- */

async function refresh() {
  if (!state.token) return;
  try {
    const data = await api(`/api/chat/conversations/${state.token}/messages?after=${state.lastId}`);
    appendMessages(data.messages);
    setBotMode(data.bot_mode);
    renderState(data.status);
  } catch (error) {
    if (error.status === 404) resetSession();
  }
}

function resetSession() {
  state.token = null;
  state.messages = [];
  state.lastId = 0;
  state.contactRequested = false;
  state.unseen = 0;
  safeSet(TOKEN_KEY, null);
  document.title = "Онлайн-консультант O-Complex";
  renderLog();
  renderState("new");
}

/** Кнопка доступна, пока у клиента есть диалог: пустой чат начинать заново незачем. */
function updateNewChatButton() {
  els.newChat.disabled = !state.token;
}

function askNewChat() {
  if (!state.token) return;
  if (state.messages.length || state.contactRequested) els.newChatDialog.showModal();
  else startNewChat();
}

function startNewChat() {
  if (els.newChatDialog.open) els.newChatDialog.close();
  resetSession();
  els.message.value = "";
  updateComposer();
  toast("Новый чат начат");
  els.message.focus();
}

async function restore() {
  if (!state.token) return;
  try {
    const session = await api(`/api/chat/conversations/${state.token}`);
    state.contactRequested = session.contact_requested;
    state.botMode = Boolean(session.bot_mode);
    appendMessages(session.messages);
    renderState(session.status);
  } catch (error) {
    if (error.status === 404 || error.status === 422) resetSession();
  }
}

async function checkStatus() {
  try {
    await api("/health");
    els.status.className = "status ok";
    setChildren(els.status, h("i"), h("span", { text: "На связи" }));
  } catch {
    els.status.className = "status bad";
    setChildren(els.status, h("i"), h("span", { text: "Нет связи" }));
  }
}

/* ---------- Запрос на связь ---------- */

function renderMethods() {
  setChildren(
    els.methods,
    Object.entries(CONTACT_METHODS).map(([key, method]) =>
      h(
        "label",
        { class: "method" },
        h("input", { type: "radio", name: "method", value: key, checked: key === state.method, onchange: () => {
            els.value.value = "";
            selectMethod(key);
          } }),
        h("span", { text: method.label }),
      ),
    ),
  );
}

function selectMethod(key) {
  state.method = key;
  const method = CONTACT_METHODS[key];
  els.valueField.hidden = key === "chat";
  els.valueLabel.textContent = method.field;
  els.value.placeholder = method.placeholder;
  els.value.setAttribute("inputmode", method.inputmode);
  els.value.setAttribute("autocomplete", PHONE_METHODS.has(key) ? "tel" : key === "email" ? "email" : "off");
  clearValueError();
  hideError();
}

/** Поле «телефон» маскируется для номерных способов и для Telegram, пока вместо ника вводят цифры. */
function phoneMaskActive() {
  if (PHONE_METHODS.has(state.method)) return true;
  return state.method === "telegram" && /^[+\d]/.test(els.value.value.trim());
}

function validateValue() {
  const method = state.method;
  const value = els.value.value.trim();
  if (method === "chat") return "";
  if (!value) return `Заполните поле «${CONTACT_METHODS[method].field}».`;
  if (PHONE_METHODS.has(method) || (method === "telegram" && /^[+\d]/.test(value))) {
    return isValidRuPhone(value) ? "" : "Введите номер полностью: +7 (900) 000-00-00.";
  }
  if (method === "telegram") return TELEGRAM_NICK_RE.test(value) ? "" : "Ник Telegram: 5–32 латинских букв, цифр или «_», например @name.";
  return EMAIL_RE.test(value) ? "" : "Проверьте адрес почты, например name@example.com.";
}

function showValueError(text) {
  els.value.setAttribute("aria-invalid", "true");
  els.valueError.textContent = text;
  els.valueError.hidden = false;
}

function clearValueError() {
  els.value.removeAttribute("aria-invalid");
  els.valueError.hidden = true;
}

function showError(text) {
  els.error.textContent = text;
  els.error.hidden = false;
}

function hideError() {
  els.error.hidden = true;
}

function openContact() {
  hideError();
  renderMethods();
  selectMethod(state.method);
  els.dialog.showModal();
  els.name.focus();
}

async function submitContact(event) {
  event.preventDefault();
  hideError();
  const name = els.name.value.trim();
  const value = els.value.value.trim();
  if (!name) return showError("Укажите, как к вам обращаться.");
  const problem = validateValue();
  if (problem) {
    showValueError(problem);
    return els.value.focus();
  }
  els.submit.disabled = true;
  try {
    const session = await ensureConversation();
    if (session) renderState(session.status);
    await api(`/api/chat/conversations/${state.token}/contact-request`, {
      body: {
        name,
        method: state.method,
        value: state.method === "chat" ? null : value,
        preferred_time: timeSelect.value,
        comment: els.comment.value.trim() || null,
      },
    });
    state.contactRequested = true;
    renderLog();
    els.dialog.close();
    toast("Запрос передан менеджеру");
    await refresh();
    renderCallbackCard();
  } catch (error) {
    showError(error.message);
  } finally {
    els.submit.disabled = false;
  }
}

/* ---------- Инициализация ---------- */

els.composer.addEventListener("submit", (event) => {
  event.preventDefault();
  send(els.message.value);
});
els.message.addEventListener("keydown", (event) => {
  if (event.key === "Enter" && !event.shiftKey && !event.isComposing) {
    event.preventDefault();
    els.composer.requestSubmit();
  }
});
forbidEmoji(els.message);
els.message.addEventListener("input", updateComposer);
els.form.addEventListener("submit", submitContact);
attachPhoneMask(els.value, phoneMaskActive);
els.value.addEventListener("input", clearValueError);
els.value.addEventListener("blur", () => {
  if (!els.value.value.trim()) return;
  const problem = validateValue();
  if (problem) showValueError(problem);
});
$("#contact-close").append(icon("close"));
$("#contact-close").addEventListener("click", () => els.dialog.close());
$("#contact-cancel").addEventListener("click", () => els.dialog.close());
els.dialog.addEventListener("click", (event) => {
  if (event.target === els.dialog) els.dialog.close();
});
els.openContact.addEventListener("click", openContact);
els.newChat.addEventListener("click", askNewChat);
$("#new-chat-confirm").addEventListener("click", startNewChat);
$("#new-chat-cancel").addEventListener("click", () => els.newChatDialog.close());
els.newChatDialog.addEventListener("click", (event) => {
  if (event.target === els.newChatDialog) els.newChatDialog.close();
});
document.addEventListener("visibilitychange", () => {
  if (!document.hidden) {
    state.unseen = 0;
    document.title = "Онлайн-консультант O-Complex";
    refresh();
  }
});

setChildren(els.send, icon("send"), "Отправить");
renderLog();
renderState("new");
await restore();
renderLog();
checkStatus();
poll(refresh, POLL_MS);
poll(checkStatus, 30_000);
