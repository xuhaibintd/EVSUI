(function (global) {
  "use strict";

  const app = global.EVSUIApp;

  function registerNavigation() {
    if (document.body.dataset.navBound === "1") {
      return;
    }
    document.body.dataset.navBound = "1";

    document.addEventListener("click", (event) => {
      const menuButton = event.target.closest(".menu-item");
      if (menuButton) {
        if (app.stepGate) {
          app.stepGate.activateSection(menuButton.dataset.section);
        }
        return;
      }

      const navButton = event.target.closest(".wizard-btn[data-target]");
      if (navButton && app.stepGate) {
        app.stepGate.activateSection(navButton.dataset.target);
      }
    });
  }

  app.registerNavigation = registerNavigation;
})(window);
