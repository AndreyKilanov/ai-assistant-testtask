/* Общие утилиты интерфейсов клиента и менеджера: разметка без innerHTML, иконки, запросы, форматирование. */

export const STATUS = {
  new: { label: "Новый", tone: "lime" },
  in_progress: { label: "В работе", tone: "blue" },
  waiting_client: { label: "Ждём клиента", tone: "neutral" },
  callback: { label: "Просит связаться", tone: "orange" },
  closed: { label: "Закрыт", tone: "muted" },
};

/* Платформа и подписи клавиш: на Mac ⌘ и ⌥, на остальных Ctrl и Alt. */
export const IS_MAC = /mac|iphone|ipad/i.test(navigator.userAgentData?.platform || navigator.platform || "");
export const MOD_LABEL = IS_MAC ? "⌘" : "Ctrl";
export const ALT_LABEL = IS_MAC ? "⌥" : "Alt";
const MAC_KEYS = { Enter: "↩", Shift: "⇧", Ctrl: "⌃", Alt: "⌥", Esc: "⎋" };
/** Подпись клавиши для текущей платформы: на Mac «↩» вместо «Enter», «⇧» вместо «Shift». */
export const keyLabel = (name) => (IS_MAC ? (MAC_KEYS[name] ?? name) : name);
// Подсказки, написанные прямо в HTML (<kbd>Enter</kbd>), подменяем один раз при загрузке модуля.
if (IS_MAC) document.querySelectorAll("kbd").forEach((node) => (node.textContent = keyLabel(node.textContent.trim())));
/** Склеивает подпись сочетания: «⌥1» на Mac, «Alt+1» на остальных. */
export const combo = (modifier, key) => (IS_MAC ? `${modifier}${key}` : `${modifier}+${key}`);

export const CONTACT_METHODS = {
  phone: { label: "Телефон", field: "Номер телефона", placeholder: "+7 (900) 000-00-00", inputmode: "tel" },
  telegram: { label: "Telegram", field: "Ник или номер в Telegram", placeholder: "@username или +7 (900) 000-00-00", inputmode: "text" },
  whatsapp: { label: "WhatsApp", field: "Номер в WhatsApp", placeholder: "+7 (900) 000-00-00", inputmode: "tel" },
  max: { label: "Max", field: "Номер в Max", placeholder: "+7 (900) 000-00-00", inputmode: "tel" },
  email: { label: "Email", field: "Адрес электронной почты", placeholder: "name@example.com", inputmode: "email" },
  chat: { label: "В этом чате", field: "", placeholder: "", inputmode: "text" },
};

export const ICONS = {
  lock: "M7 11V8a5 5 0 0 1 10 0v3M6 11h12v9H6z",
  check: "M5 12.5l4.5 4.5L19 7.5",
  checks: "M2 12.5l4 4L14 8M9 15.5l1.5 1.5L21 7",
  star: "M12 3l2.7 5.6 6.1.9-4.4 4.3 1 6.1L12 17l-5.4 2.9 1-6.1L3.2 9.5l6.1-.9z",
  spark: "M12 3v5M12 16v5M3 12h5M16 12h5M6 6l3 3M15 15l3 3M18 6l-3 3M9 15l-3 3",
  copy: "M9 9h11v11H9zM5 15V4h11",
  send: "M4 12l16-8-6 16-3-7z",
  undo: "M9 7H4v5M4 12a8 8 0 1 1 2.3 5.7",
  clock: "M12 7v5l3 2M21 12a9 9 0 1 1-18 0 9 9 0 0 1 18 0z",
  coins: "M12 6c4.4 0 8 1.1 8 2.5S16.4 11 12 11 4 9.9 4 8.5 7.6 6 12 6zM4 8.5v4C4 13.9 7.6 15 12 15s8-1.1 8-2.5v-4M4 12.5v4C4 17.9 7.6 19 12 19s8-1.1 8-2.5v-4",
  book: "M5 4h9a4 4 0 0 1 4 4v12H9a4 4 0 0 1-4-4zM9 4v16",
  ext: "M14 4h6v6M20 4l-9 9M18 14v6H4V6h6",
  up: "M14 9V5a3 3 0 0 0-3-3l-4 9v11h11.3a2 2 0 0 0 2-1.7l1.4-9a2 2 0 0 0-2-2.3zM7 22H4a2 2 0 0 1-2-2v-7a2 2 0 0 1 2-2h3",
  down: "M10 15v4a3 3 0 0 0 3 3l4-9V2H5.7a2 2 0 0 0-2 1.7l-1.4 9a2 2 0 0 0 2 2.3zM17 2h3a2 2 0 0 1 2 2v7a2 2 0 0 1-2 2h-3",
  phone: "M5 4h4l2 5-2.5 1.5a11 11 0 0 0 5 5L15 13l5 2v4a2 2 0 0 1-2 2A15 15 0 0 1 3 6a2 2 0 0 1 2-2z",
  mail: "M4 6h16v12H4zM4 7l8 6 8-6",
  chat: "M4 5h16v11H9l-5 4z",
  user: "M12 12a4 4 0 1 0 0-8 4 4 0 0 0 0 8zM4 21a8 8 0 0 1 16 0",
  search: "M11 4a7 7 0 1 0 0 14 7 7 0 0 0 0-14zM21 21l-4.5-4.5",
  back: "M15 5l-7 7 7 7",
  logout: "M10 5H5v14h5M15 8l4 4-4 4M9 12h10",
  bell: "M6 17V11a6 6 0 0 1 12 0v6l2 2H4zM10 21h4",
  note: "M5 4h14v16H5zM8 9h8M8 13h8M8 17h5",
  refresh: "M20 5v5h-5M4 19v-5h5M5.5 9A8 8 0 0 1 20 10M18.5 15A8 8 0 0 1 4 14",
  close: "M6 6l12 12M18 6L6 18",
};

/** Создаёт элемент; текст всегда вставляется как textContent (без HTML-инъекций). */
export function h(tag, props = {}, ...children) {
  const node = document.createElement(tag);
  for (const [key, value] of Object.entries(props)) {
    if (value === undefined || value === null || value === false) continue;
    if (key === "class") node.className = value;
    else if (key === "text") node.textContent = value;
    else if (key === "value") node.value = value;
    else if (key.startsWith("on")) node.addEventListener(key.slice(2).toLowerCase(), value);
    else node.setAttribute(key, value === true ? "" : value);
  }
  for (const child of children.flat()) {
    if (child === null || child === undefined || child === false) continue;
    node.append(child.nodeType ? child : document.createTextNode(String(child)));
  }
  return node;
}

/** Заменяет содержимое узла, пропуская пустые значения (replaceChildren превратил бы их в текст "null"). */
export function setChildren(node, ...children) {
  node.replaceChildren(...children.flat().filter((child) => child !== null && child !== undefined && child !== false));
}

/** SVG-иконка вместо символов и эмодзи: не зависит от запасных шрифтов и не сдвигает строку. */
export function icon(name) {
  const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
  svg.setAttribute("viewBox", "0 0 24 24");
  svg.setAttribute("class", "icon");
  svg.setAttribute("aria-hidden", "true");
  const path = document.createElementNS("http://www.w3.org/2000/svg", "path");
  path.setAttribute("d", ICONS[name]);
  svg.append(path);
  return svg;
}

export const formatTime = (value) => new Date(value).toLocaleTimeString("ru-RU", { hour: "2-digit", minute: "2-digit" });
export const formatNumber = (value) => Number(value).toLocaleString("ru-RU");
export const formatSeconds = (ms) => (ms < 100 ? "< 0,1 с" : `${(ms / 1000).toFixed(1).replace(".", ",")} с`);

export function formatDateTime(value) {
  const date = new Date(value);
  return `${date.toLocaleDateString("ru-RU", { day: "numeric", month: "long" })}, ${formatTime(date)}`;
}

/** Короткая относительная метка времени для списка входящих. */
export function relativeTime(value) {
  const date = new Date(value);
  const seconds = Math.max(0, (Date.now() - date.getTime()) / 1000);
  if (seconds < 45) return "сейчас";
  if (seconds < 3600) return `${Math.round(seconds / 60)} мин`;
  if (date.toDateString() === new Date().toDateString()) return formatTime(date);
  return date.toLocaleDateString("ru-RU", { day: "numeric", month: "short" });
}

export function initials(name, fallback = "К") {
  const parts = (name || "").trim().split(/\s+/).filter(Boolean);
  return parts.length ? parts.slice(0, 2).map((part) => part[0].toUpperCase()).join("") : fallback;
}

export function toast(text) {
  const box = document.querySelector("#toasts");
  const node = h("div", { class: "toast" }, icon("check"), text);
  box.append(node);
  setTimeout(() => node.remove(), 2400);
}

export async function copyText(text) {
  try {
    await navigator.clipboard.writeText(text);
    toast("Скопировано");
  } catch {
    toast("Не удалось скопировать");
  }
}

export class ApiError extends Error {
  constructor(message, status, retryAfter = null) {
    super(message);
    this.status = status;
    this.retryAfter = retryAfter;
  }
}

/** Запрос к API с единым разбором ошибок; headers — дополнительные заголовки (например, код менеджера). */
export async function api(path, { method, body, headers = {} } = {}) {
  let response;
  try {
    response = await fetch(path, {
      method: method || (body ? "POST" : "GET"),
      headers: { ...(body ? { "Content-Type": "application/json" } : {}), ...headers },
      body: body ? JSON.stringify(body) : undefined,
    });
  } catch {
    throw new ApiError("Нет связи с сервером. Проверьте подключение.", 0);
  }
  if (response.ok) return response.json();
  let detail = "";
  try {
    const data = await response.json();
    if (typeof data.detail === "string") detail = data.detail;
    else if (Array.isArray(data.detail)) detail = data.detail.map((item) => (item.msg || "").replace(/^Value error, /, "")).join(". ");
  } catch {
    /* тело ответа не JSON */
  }
  const retryAfter = Number(response.headers.get("Retry-After")) || null;
  if (response.status === 429) throw new ApiError(`${detail || "Слишком много обращений"}. Повторите через ${retryAfter || 60} с.`, 429, retryAfter);
  if (response.status === 503) throw new ApiError(detail || "Сервис временно недоступен, попробуйте позже.", 503, retryAfter);
  if (response.status === 401) throw new ApiError(detail || "Нужна авторизация", 401);
  if (response.status === 404) throw new ApiError(detail || "Не найдено", 404);
  if (response.status === 422) throw new ApiError(detail || "Проверьте введённые данные.", 422);
  throw new ApiError(detail || `Ошибка сервера (${response.status})`, response.status);
}

/** Повторяет функцию по таймеру; пропускает тик, если предыдущий ещё выполняется; возвращает функцию остановки. */
export function poll(task, intervalMs) {
  let running = false;
  const tick = async () => {
    if (running || document.hidden) return;
    running = true;
    try {
      await task();
    } finally {
      running = false;
    }
  };
  const id = setInterval(tick, intervalMs);
  return () => clearInterval(id);
}

/** Автоматическая высота поля ввода. */
export function autosize(textarea, max = 140) {
  textarea.style.height = "auto";
  textarea.style.height = `${Math.min(textarea.scrollHeight + 2, max)}px`;
}

/* ---------- Телефон: маска и проверка ---------- */

/** Оставляет 10 цифр номера без кода страны: ведущие 7 и 8 считаются кодом страны и trunk-префиксом. */
function nationalDigits(raw) {
  let digits = String(raw).replace(/\D/g, "");
  if (digits.startsWith("7") || digits.startsWith("8")) digits = digits.slice(1);
  return digits.slice(0, 10);
}

function formatNationalDigits(digits) {
  if (!digits) return "";
  let out = `+7 (${digits.slice(0, 3)}`;
  if (digits.length >= 3) out += ")";
  if (digits.length > 3) out += ` ${digits.slice(3, 6)}`;
  if (digits.length > 6) out += `-${digits.slice(6, 8)}`;
  if (digits.length > 8) out += `-${digits.slice(8, 10)}`;
  return out;
}

/** Приводит ввод к виду +7 (900) 000-00-00. */
export function formatRuPhone(raw) {
  return formatNationalDigits(nationalDigits(raw));
}

/** Номер полный: 10 цифр после +7, первая цифра не 0 и не 1. */
export function isValidRuPhone(value) {
  return /^[2-9]\d{9}$/.test(nationalDigits(value));
}

/** Включает маску на поле, пока `isActive()` возвращает true; Backspace по символу оформления стирает цифру. */
export function attachPhoneMask(input, isActive = () => true) {
  let previous = "";
  input.addEventListener("input", (event) => {
    if (!isActive()) {
      previous = input.value;
      return;
    }
    let digits = nationalDigits(input.value);
    if (String(event.inputType).startsWith("delete") && digits === nationalDigits(previous)) digits = digits.slice(0, -1);
    input.value = formatNationalDigits(digits);
    previous = input.value;
  });
}

/* ---------- Выпадающий список ---------- */

/**
 * Свой выпадающий список вместо системного: стрелки, Enter, Escape, закрытие по клику снаружи.
 * options: [{ value, label, tone? }]; возвращает { node, value }.
 */
export function createSelect({ options, value, ariaLabel, onChange = () => {}, block = false }) {
  let current = options.some((option) => option.value === value) ? value : options[0].value;
  const find = (v) => options.find((option) => option.value === v);
  const dot = (tone) => (tone ? h("i", { class: `dot ${tone}`, "aria-hidden": "true" }) : null);
  const button = h("button", { type: "button", class: "menu-btn", "aria-haspopup": "listbox", "aria-expanded": "false" });
  const items = options.map((option) =>
    h("li", { role: "option", tabindex: "-1", onclick: () => choose(option.value) }, dot(option.tone), h("span", { text: option.label })),
  );
  const list = h("ul", { class: "menu-list", role: "listbox", "aria-label": ariaLabel, hidden: true }, items);
  const wrap = h("div", { class: `menu${block ? " menu-full" : ""}` }, button, list);

  const render = () => {
    const selected = find(current);
    button.setAttribute("aria-label", `${ariaLabel}: ${selected.label}`);
    setChildren(button, dot(selected.tone), h("span", { class: "menu-label", text: selected.label }));
    options.forEach((option, index) => {
      const isCurrent = option.value === current;
      items[index].setAttribute("aria-selected", String(isCurrent));
      items[index].querySelector("svg")?.remove();
      if (isCurrent) items[index].append(icon("check"));
    });
  };
  const outside = (event) => {
    if (!wrap.isConnected) return document.removeEventListener("pointerdown", outside, true);
    if (!wrap.contains(event.target)) close(false);
  };
  const open = () => {
    list.hidden = false;
    button.setAttribute("aria-expanded", "true");
    document.addEventListener("pointerdown", outside, true);
    items[options.findIndex((option) => option.value === current)].focus();
  };
  const close = (returnFocus = true) => {
    list.hidden = true;
    button.setAttribute("aria-expanded", "false");
    document.removeEventListener("pointerdown", outside, true);
    if (returnFocus) button.focus();
  };
  const choose = (next) => {
    close();
    if (next === current) return;
    current = next;
    render();
    onChange(next);
  };

  button.addEventListener("click", () => (list.hidden ? open() : close()));
  button.addEventListener("keydown", (event) => {
    if (event.key === "ArrowDown" && list.hidden) {
      event.preventDefault();
      open();
    }
  });
  list.addEventListener("keydown", (event) => {
    const index = items.indexOf(document.activeElement);
    if (event.key === "ArrowDown") items[(index + 1) % items.length].focus();
    else if (event.key === "ArrowUp") items[(index - 1 + items.length) % items.length].focus();
    else if (event.key === "Home") items[0].focus();
    else if (event.key === "End") items.at(-1).focus();
    else if (event.key === "Enter" || event.key === " ") items[index]?.click();
    else if (event.key === "Escape") close();
    else if (event.key === "Tab") close(false);
    else return;
    event.preventDefault();
    event.stopPropagation();
  });
  render();
  return {
    node: wrap,
    get value() {
      return current;
    },
    set value(next) {
      if (find(next)) {
        current = next;
        render();
      }
    },
  };
}
