/* Демо-переключатель экранов «Клиент | Менеджер». Показывается, только если на сервере включён DEMO_MODE. */
import { h, icon, setChildren } from "/static/common.js";

const VIEWS = [
  { id: "client", path: "/", label: "Клиент", glyph: "user", key: "1" },
  { id: "manager", path: "/manager", label: "Менеджер", glyph: "chat", key: "2" },
];

async function isDemo() {
  try {
    const response = await fetch("/api/demo/config");
    return response.ok && (await response.json()).enabled === true;
  } catch {
    return false;
  }
}

function mount() {
  const current = location.pathname.startsWith("/manager") ? "manager" : "client";
  const nav = h("nav", { class: "demo-switch", "aria-label": "Демо: переключение экранов" });
  setChildren(
    nav,
    h("span", { class: "demo-label", text: "Демо" }),
    VIEWS.map((view) =>
      h(
        "a",
        {
          href: view.path,
          class: "demo-link",
          "aria-current": view.id === current ? "page" : null,
          title: `${view.label} · Alt+${view.key}`,
        },
        icon(view.glyph),
        h("span", { text: view.label }),
        h("kbd", { text: `Alt+${view.key}` }),
      ),
    ),
  );
  document.body.append(nav);
  document.body.classList.add("has-demo");
  document.addEventListener("keydown", (event) => {
    if (!event.altKey || event.ctrlKey || event.metaKey) return;
    const target = VIEWS.find((view) => view.key === event.key && view.id !== current);
    if (target) {
      event.preventDefault();
      location.assign(target.path);
    }
  });
}

if (await isDemo()) mount();
