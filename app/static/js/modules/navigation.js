(function (global) {
  "use strict";

  const app = global.EVSUIApp;

  function activateFromButton(button) {
    if (!(button instanceof HTMLElement) || !app.stepGate) {
      return;
    }
    if ('disabled' in button && button.disabled) {
      return;
    }
    const force = button.dataset.allowLocked === 'true';
    const section = button.dataset.section;
    const target = button.dataset.target;
    if (section) {
      app.stepGate.activateSection(section, force);
      return;
    }
    if (target) {
      app.stepGate.activateSection(target, force);
    }
  }

  function bindNavigationButtons(scope = document) {
    const buttons = scope.querySelectorAll('.menu-item[data-section], .wizard-btn[data-target]');
    buttons.forEach((button) => {
      if (!(button instanceof HTMLElement) || button.dataset.navClickBound === "1") {
        return;
      }
      button.dataset.navClickBound = "1";
      button.addEventListener('click', (event) => {
        event.preventDefault();
        event.stopPropagation();
        activateFromButton(button);
      });
    });
  }

  function registerNavigation() {
    if (document.body.dataset.navBound !== "1") {
      document.body.dataset.navBound = "1";
      document.addEventListener('click', (event) => {
        const trigger = event.target.closest('.menu-item[data-section], .wizard-btn[data-target]');
        if (!trigger) {
          return;
        }
        activateFromButton(trigger);
      }, true);
    }

    bindNavigationButtons(document);
  }

  app.bindNavigationButtons = bindNavigationButtons;
  app.registerNavigation = registerNavigation;
  app.registerBinder(bindNavigationButtons);
})(window);
