(function (global) {
  "use strict";

  const app = global.EVSUIApp;

  function setProgressState(button, loading) {
    if (!button) {
      return;
    }

    if (loading) {
      button.dataset.wasDisabled = button.disabled ? "1" : "0";
      button.disabled = true;
      button.classList.add("is-loading");
      button.setAttribute("aria-busy", "true");
      return;
    }

    button.classList.remove("is-loading");
    if (button.dataset.wasDisabled !== "1") {
      button.disabled = false;
    }
    delete button.dataset.wasDisabled;
    button.removeAttribute("aria-busy");
  }

  function registerHtmxProgressButtons(selector = "[data-progress-button]") {
    if (document.body.dataset.progressButtonsBound === "1") {
      return;
    }
    document.body.dataset.progressButtonsBound = "1";

    const sourceToButton = new WeakMap();

    const resolveSource = (button) => {
      if (!(button instanceof Element)) {
        return null;
      }
      const form = button.closest("form[hx-post], form[hx-get], form[hx-put], form[hx-delete], form[hx-patch]");
      return form || button;
    };

    document.body.addEventListener(
      "click",
      (event) => {
        const button = event.target.closest(selector);
        if (!button) {
          return;
        }
        const source = resolveSource(button);
        if (source) {
          sourceToButton.set(source, button);
        }
      },
      true
    );

    document.body.addEventListener(
      "submit",
      (event) => {
        const form = event.target;
        if (!(form instanceof HTMLFormElement)) {
          return;
        }
        const submitter = event.submitter;
        if (!(submitter instanceof Element)) {
          return;
        }
        const button = submitter.closest(selector);
        if (button) {
          sourceToButton.set(form, button);
        }
      },
      true
    );

    const resolveButton = (event) => {
      const source = event.detail && event.detail.elt;
      if (!(source instanceof Element)) {
        return null;
      }
      if (source.matches(selector)) {
        return source;
      }
      const ancestorButton = source.closest(selector);
      if (ancestorButton) {
        return ancestorButton;
      }
      const mappedButton = sourceToButton.get(source);
      if (mappedButton && mappedButton.isConnected) {
        return mappedButton;
      }
      return null;
    };

    document.body.addEventListener("htmx:beforeRequest", (event) => {
      const button = resolveButton(event);
      if (button) {
        setProgressState(button, true);
      }
    });

    const clearProgress = (event) => {
      const button = resolveButton(event);
      if (button) {
        setProgressState(button, false);
      }
      const source = event.detail && event.detail.elt;
      if (source instanceof Element) {
        sourceToButton.delete(source);
      }
    };

    document.body.addEventListener("htmx:afterRequest", clearProgress);
    document.body.addEventListener("htmx:responseError", clearProgress);
    document.body.addEventListener("htmx:sendError", clearProgress);
    document.body.addEventListener("htmx:timeout", clearProgress);
  }

  function registerHtmxAfterSwap() {
    if (document.body.dataset.afterSwapBound === "1") {
      return;
    }
    document.body.dataset.afterSwapBound = "1";

    document.body.addEventListener("htmx:afterSwap", (event) => {
      const target = event.target;
      if (target && target.id === "chat-messages") {
        target.scrollTop = target.scrollHeight;
      }
      if (app.stepGate && target && target.id === "section-connect-content") {
        app.stepGate.syncStepConnectionState(target);
      }
      app.bindAll(document);
    });
  }

  app.registerHtmxProgressButtons = registerHtmxProgressButtons;
  app.registerHtmxAfterSwap = registerHtmxAfterSwap;
})(window);
