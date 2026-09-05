(function (global) {
  "use strict";

  const app = global.EVSUIApp;
  const formSelector = "#section-create form[hx-post='/ui/create/upload']";
  const providerLabels = {
    openai: "OpenAI",
    azure_openai: "Azure OpenAI",
    vertexai: "Vertex AI",
    bedrock: "Bedrock",
    anthropic: "Anthropic",
  };

  function setVisible(element, visible, className) {
    element.hidden = !visible;
    element.classList.toggle(className, !visible);
    element.setAttribute("aria-hidden", visible ? "false" : "true");
  }

  function syncGroups(form, selector, attribute, value, className, allowEmpty = true) {
    form.querySelectorAll(selector).forEach((group) => {
      const allowed = String(group.getAttribute(attribute) || "").toLowerCase().split(/\s+/).filter(Boolean);
      setVisible(group, (allowEmpty && !allowed.length) || allowed.includes(value), className);
    });
  }

  function syncProviderModels(form) {
    form.querySelectorAll("select[data-provider-model-key]").forEach((provider) => {
      const key = provider.dataset.providerModelKey;
      const model = Array.from(form.querySelectorAll("select[data-provider-model-target]"))
        .find((candidate) => candidate.dataset.providerModelTarget === key);
      if (!model) {
        return;
      }
      const providerValue = provider.value.trim().toLowerCase();
      // Preserve selected models during unrelated field changes.
      if (model.dataset.filteredProvider === providerValue) {
        return;
      }
      const originalMarkup = model.dataset.providerModelOptions || model.innerHTML;
      model.dataset.providerModelOptions = originalMarkup;
      const previousValue = model.value;
      const scratch = document.createElement("select");
      scratch.innerHTML = originalMarkup;
      model.replaceChildren();
      const wantedLabel = providerLabels[providerValue] || "";
      Array.from(scratch.children).forEach((child) => {
        if (child instanceof HTMLOptionElement ||
            (child instanceof HTMLOptGroupElement && (!wantedLabel || child.label === wantedLabel))) {
          model.appendChild(child.cloneNode(true));
        }
      });
      model.value = Array.from(model.options).some((option) => option.value === previousValue) ? previousValue : "";
      model.dataset.filteredProvider = providerValue;
    });
  }

  function syncCreateParameters(form) {
    const valueOf = (name, fallback = "") =>
      String(form.querySelector("[name='" + name + "']")?.value || fallback).trim().toLowerCase();
    syncGroups(form, "[data-doc-mode-for]", "data-doc-mode-for", valueOf("doc_pipeline_mode"), "doc-mode-hidden", false);
    const algorithm = valueOf("search_algorithm");
    syncGroups(form, "[data-algo-for]", "data-algo-for", algorithm, "algo-hidden", false);
    const hint = form.querySelector("[data-algo-hint]");
    if (hint) {
      hint.textContent = algorithm ? " " + algorithm.toUpperCase() : "";
      hint.hidden = !algorithm;
    }
    syncGroups(form, "[data-partition-routes]", "data-partition-routes", valueOf("multi_format_strategy", "auto"), "partition-route-hidden");
    syncGroups(form, "[data-bookrag-partition-routes]", "data-bookrag-partition-routes", valueOf("multi_format_bookrag_strategy", "auto"), "partition-route-hidden");
    syncGroups(form, "[data-chunk-strategies]", "data-chunk-strategies", valueOf("multi_format_chunk_strategy", "chunk_by_character"), "chunk-strategy-hidden");
    form.querySelectorAll("select[data-enrichment-toggle]").forEach((toggle) => {
      const key = toggle.dataset.enrichmentToggle;
      const panel = Array.from(form.querySelectorAll("[data-enrichment-panel-for]"))
        .find((candidate) => candidate.dataset.enrichmentPanelFor === key);
      if (panel) {
        setVisible(panel, toggle.value.trim().toLowerCase() === "true", "enrichment-panel-hidden");
      }
    });
    syncProviderModels(form);

    // Evaluate every ancestor after visibility rules. A nested field cannot be
    // enabled simply because its own route matches inside a hidden mode.
    const locked = form.classList.contains("disabled-block") || form.dataset.readOnly === "true";
    form.querySelectorAll("input, select, textarea").forEach((control) => {
      control.disabled = locked || Boolean(control.closest("[hidden]"));
    });
  }

  function bindCreateParameters(scope = document) {
    scope.querySelectorAll(formSelector).forEach((form) => {
      if (form.dataset.parametersBound !== "1") {
        form.dataset.parametersBound = "1";
        form.addEventListener("change", () => syncCreateParameters(form), true);
      }
      syncCreateParameters(form);
    });
  }

  app.syncCreateParameters = syncCreateParameters;
  app.registerBinder(bindCreateParameters);
})(window);
