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
})(window);
