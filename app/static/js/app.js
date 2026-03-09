(function (global) {
  "use strict";

  const app = global.EVSUIApp || {};

  document.addEventListener("DOMContentLoaded", () => {
    if (typeof global.createStepGate === "function") {
      app.stepGate = global.createStepGate();
      app.stepGate.initialize();
    }

    if (typeof app.registerNavigation === "function") {
      app.registerNavigation();
    }
    if (typeof app.registerHtmxProgressButtons === "function") {
      app.registerHtmxProgressButtons();
    }
    if (typeof app.registerHtmxAfterSwap === "function") {
      app.registerHtmxAfterSwap();
    }
    if (typeof app.bindAll === "function") {
      app.bindAll(document);
    }
  });
})(window);
