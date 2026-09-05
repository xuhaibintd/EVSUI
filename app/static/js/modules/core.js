(function (global) {
  "use strict";

  const app = (global.EVSUIApp = global.EVSUIApp || {});

  app.stepGate = null;
  app.binders = app.binders || [];

  app.escapeHtml = function escapeHtml(value) {
    return String(value)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/\"/g, "&quot;")
      .replace(/'/g, "&#39;");
  };

  app.registerBinder = function registerBinder(fn) {
    if (typeof fn === "function") {
      app.binders.push(fn);
    }
  };

  app.bindAll = function bindAll(scope) {
    app.binders.forEach((binder) => binder(scope || document));
  };

  app.setTopMessage = function setTopMessage(message, kind = "info") {
    const shell = document.querySelector("#top-op-stack-shell");
    if (!(shell instanceof HTMLElement)) {
      return;
    }
    const line = document.createElement("p");
    line.className = `top-op-line ${kind}`;
    line.textContent = String(message || "");
    line.title = String(message || "");
    shell.replaceChildren(line);
  };
})(window);
