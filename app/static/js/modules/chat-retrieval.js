(function (global) {
  "use strict";

  const app = (global.EVSUIApp = global.EVSUIApp || {});

  function initializeForm(form) {
    if (!form || form.dataset.retrievalModeBound === "1") {
      return;
    }
    form.dataset.retrievalModeBound = "1";

    const radios = Array.from(form.querySelectorAll("[data-retrieval-mode-toggle]"));
    const nativeOnly = Array.from(form.querySelectorAll("[data-native-only]"));
    const cards = Array.from(form.querySelectorAll("[data-retrieval-option]"));

    nativeOnly.forEach((element) => {
      if (!element.hasAttribute("data-native-base-disabled")) {
        element.setAttribute("data-native-base-disabled", element.disabled ? "1" : "0");
      }
    });

    function applyState() {
      const active = radios.find((radio) => radio.checked);
      const mode = active ? active.value : "native";
      const nativeSelected = mode === "native";

      cards.forEach((card) => {
        const selected = card.getAttribute("data-retrieval-option") === mode;
        card.classList.toggle("is-selected", selected);
        card.classList.toggle("is-unselected", !selected);
      });

      nativeOnly.forEach((element) => {
        const baseDisabled = element.getAttribute("data-native-base-disabled") === "1";
        element.disabled = baseDisabled || !nativeSelected;
      });
    }

    radios.forEach((radio) => radio.addEventListener("change", applyState));
    applyState();
  }

  app.registerBinder(function bindChatRetrieval(scope) {
    const root = scope || document;
    root.querySelectorAll("[data-retrieval-mode-form]").forEach(initializeForm);
  });
})(window);
