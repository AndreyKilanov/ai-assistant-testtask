(function () {
  "use strict";
  var KEY = "theme";
  var root = document.documentElement;
  var query = window.matchMedia ? window.matchMedia("(prefers-color-scheme: dark)") : null;

  function saved() {
    try {
      var value = localStorage.getItem(KEY);
      return value === "light" || value === "dark" ? value : null;
    } catch (error) {
      return null;
    }
  }

  function apply(theme) {
    root.setAttribute("data-theme", theme);
    var button = document.getElementById("theme-toggle");
    if (button) {
      var label = theme === "dark" ? "Включить светлую тему" : "Включить тёмную тему";
      button.setAttribute("aria-label", label);
      button.title = label;
    }
  }

  function system() {
    return query && query.matches ? "dark" : "light";
  }

  apply(saved() || system());

  if (query && query.addEventListener) {
    query.addEventListener("change", function () {
      if (!saved()) apply(system());
    });
  }

  document.addEventListener("DOMContentLoaded", function () {
    var button = document.getElementById("theme-toggle");
    if (!button) return;
    apply(root.getAttribute("data-theme") || system());
    button.addEventListener("click", function () {
      var next = root.getAttribute("data-theme") === "dark" ? "light" : "dark";
      try {
        localStorage.setItem(KEY, next);
      } catch (error) {
        /* хранилище недоступно: тема останется до перезагрузки страницы */
      }
      apply(next);
    });
  });
})();
