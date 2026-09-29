// Перетаскиваемые разделители между панелями консоли менеджера.
// Ширина хранится в CSS-переменной контейнера и в localStorage (если доступен).
const STEP = 16;

const storageGet = (key) => {
  try { return localStorage.getItem(key); } catch { return null; }
};
const storageSet = (key, value) => {
  try {
    if (value === null) localStorage.removeItem(key);
    else localStorage.setItem(key, value);
  } catch { /* приватный режим — просто не запоминаем */ }
};

function setupResizer(handle) {
  const container = handle.parentElement;
  const { var: cssVar, target, side, min, max, def, reserve, key } = {
    var: handle.dataset.var,
    target: handle.dataset.target,
    side: handle.dataset.side, // с какой стороны от разделителя панель, которую тянем
    min: Number(handle.dataset.min),
    max: Number(handle.dataset.max),
    def: Number(handle.dataset.default),
    reserve: Number(handle.dataset.reserve),
    key: `resize:${handle.dataset.var}`,
  };
  const pane = container.querySelector(target);

  // Не даём панели занять всё место: остальным должно остаться не меньше reserve px
  const limit = () => {
    if (!container.clientWidth) return max; // контейнер скрыт — не зажимаем
    const free = container.clientWidth - reserve - handle.offsetWidth;
    return Math.max(min, Math.min(max, free));
  };
  const apply = (width, persist = true) => {
    const value = Math.round(Math.min(limit(), Math.max(min, width)));
    container.style.setProperty(cssVar, `${value}px`);
    handle.setAttribute("aria-valuenow", String(value));
    if (persist) storageSet(key, String(value));
    return value;
  };

  handle.setAttribute("aria-valuemin", String(min));
  handle.setAttribute("aria-valuemax", String(max));
  const saved = Number(storageGet(key));
  apply(saved >= min ? saved : def, false);

  handle.addEventListener("pointerdown", (event) => {
    if (event.button !== 0) return;
    event.preventDefault();
    handle.setPointerCapture(event.pointerId);
    const startX = event.clientX;
    const startWidth = pane.getBoundingClientRect().width;
    const sign = side === "left" ? 1 : -1;
    handle.classList.add("dragging");
    document.body.classList.add("resizing");

    const move = (e) => apply(startWidth + sign * (e.clientX - startX));
    const stop = () => {
      handle.classList.remove("dragging");
      document.body.classList.remove("resizing");
      handle.removeEventListener("pointermove", move);
      handle.removeEventListener("pointerup", stop);
      handle.removeEventListener("pointercancel", stop);
    };
    handle.addEventListener("pointermove", move);
    handle.addEventListener("pointerup", stop);
    handle.addEventListener("pointercancel", stop);
  });

  handle.addEventListener("keydown", (event) => {
    const current = pane.getBoundingClientRect().width;
    const dir = side === "left" ? 1 : -1;
    if (event.key === "ArrowLeft") apply(current - dir * STEP);
    else if (event.key === "ArrowRight") apply(current + dir * STEP);
    else if (event.key === "Home") apply(min);
    else if (event.key === "End") apply(max);
    else return;
    event.preventDefault();
  });

  // Двойной клик — вернуть ширину по умолчанию
  handle.addEventListener("dblclick", () => {
    storageSet(key, null);
    apply(def, false);
  });

  // При сужении окна подрезаем ширину, чтобы центральная панель не схлопнулась
  window.addEventListener("resize", () => {
    if (handle.offsetParent === null) return;
    apply(pane.getBoundingClientRect().width, false);
  });
}

document.querySelectorAll(".resizer").forEach(setupResizer);
