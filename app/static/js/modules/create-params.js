(function (global) {
  "use strict";

  const app = global.EVSUIApp;

  function bindAlgorithmParams(scope = document) {
    const forms = scope.querySelectorAll("#section-create form[hx-post='/ui/create/upload']");
    forms.forEach((form) => {
      const algorithmSelect = form.querySelector("select[name='search_algorithm']");
      const fields = form.querySelectorAll("[data-algo-for]");
      const hint = form.querySelector("[data-algo-hint]");
      if (!(algorithmSelect instanceof HTMLSelectElement) || !fields.length) {
        return;
      }
      if (algorithmSelect.dataset.algoBound === "1") {
        return;
      }
      algorithmSelect.dataset.algoBound = "1";

      const labels = {
        VECTORDISTANCE: "VECTORDISTANCE",
        KMEANS: "KMEANS",
        HNSW: "HNSW",
      };

      const isFormLocked = () => form.classList.contains("disabled-block");

      const syncByAlgorithm = () => {
        const current = (algorithmSelect.value || "").trim().toUpperCase();
        const locked = isFormLocked();
        fields.forEach((field) => {
          if (!(field instanceof HTMLElement)) {
            return;
          }
          const allowed = (field.dataset.algoFor || "")
            .split(/\s+/)
            .map((item) => item.trim().toUpperCase())
            .filter(Boolean);
          const show = allowed.includes(current);
          field.classList.toggle("algo-hidden", !show);

          const controls = field.querySelectorAll("input, select, textarea");
          controls.forEach((control) => {
            control.disabled = !show || locked;
          });
        });

        if (hint instanceof HTMLElement) {
          const label = labels[current] || "";
          hint.textContent = label ? ` ${label}` : "";
          hint.hidden = !label;
        }
      };

      algorithmSelect.addEventListener("change", syncByAlgorithm);
      syncByAlgorithm();
    });
  }

  function normalizeProviderLabel(value) {
    const current = (value || "").trim().toLowerCase();
    if (!current) {
      return "";
    }
    if (current === "openai") {
      return "OpenAI";
    }
    if (current === "vertexai") {
      return "Vertex AI";
    }
    if (current === "bedrock") {
      return "Bedrock";
    }
    if (current === "anthropic") {
      return "Anthropic";
    }
    return "";
  }

  function bindProviderModelFilters(scope = document) {
    const forms = scope.querySelectorAll("#section-create form[hx-post='/ui/create/upload']");
    forms.forEach((form) => {
      const providers = form.querySelectorAll("select[data-provider-model-key]");
      if (!providers.length) {
        return;
      }
      if (form.dataset.providerModelBound === "1") {
        return;
      }
      form.dataset.providerModelBound = "1";

      const syncPair = (providerSelect) => {
        if (!(providerSelect instanceof HTMLSelectElement)) {
          return;
        }
        const key = (providerSelect.dataset.providerModelKey || "").trim();
        if (!key) {
          return;
        }
        const modelSelect = form.querySelector(`select[data-provider-model-target='${key}']`);
        if (!(modelSelect instanceof HTMLSelectElement)) {
          return;
        }
        const originalMarkup = modelSelect.dataset.providerModelOptions || modelSelect.innerHTML;
        modelSelect.dataset.providerModelOptions = originalMarkup;

        const wantedLabel = normalizeProviderLabel(providerSelect.value);
        const previousValue = modelSelect.value;
        const scratch = document.createElement("select");
        scratch.innerHTML = originalMarkup;
        modelSelect.innerHTML = "";

        Array.from(scratch.children).forEach((child) => {
          if (child instanceof HTMLOptionElement) {
            modelSelect.appendChild(child.cloneNode(true));
            return;
          }
          if (!(child instanceof HTMLOptGroupElement)) {
            return;
          }
          if (wantedLabel && child.label !== wantedLabel) {
            return;
          }
          modelSelect.appendChild(child.cloneNode(true));
        });

        const hasPreviousValue = Array.from(modelSelect.options).some((option) => option.value === previousValue);
        if (hasPreviousValue) {
          modelSelect.value = previousValue;
        } else {
          modelSelect.value = "";
        }
      };

      providers.forEach((providerSelect) => {
        providerSelect.addEventListener("change", () => syncPair(providerSelect));
        syncPair(providerSelect);
      });
    });
  }

  function bindPartitionRouteParams(scope = document) {
    const forms = scope.querySelectorAll("#section-create form[hx-post='/ui/create/upload']");
    forms.forEach((form) => {
      const routeSelect = form.querySelector("select[name='multi_format_strategy']");
      const fields = form.querySelectorAll("[data-partition-routes]");
      if (!(routeSelect instanceof HTMLSelectElement) || !fields.length) {
        return;
      }
      if (routeSelect.dataset.partitionRouteBound === "1") {
        return;
      }
      routeSelect.dataset.partitionRouteBound = "1";

      const syncByRoute = () => {
        const current = (routeSelect.value || "").trim().toLowerCase() || "auto";
        const locked = form.classList.contains("disabled-block");
        fields.forEach((field) => {
          if (!(field instanceof HTMLElement)) {
            return;
          }
          const allowed = (field.dataset.partitionRoutes || "")
            .split(/\s+/)
            .map((item) => item.trim().toLowerCase())
            .filter(Boolean);
          const show = !allowed.length || allowed.includes(current);
          field.classList.toggle("partition-route-hidden", !show);
          field.hidden = !show;
          const controls = field.querySelectorAll("input, select, textarea");
          controls.forEach((control) => {
            control.disabled = !show || locked;
          });
        });
      };

      routeSelect.addEventListener("change", syncByRoute);
      syncByRoute();
    });
  }

  function bindChunkStrategyParams(scope = document) {
    const forms = scope.querySelectorAll("#section-create form[hx-post='/ui/create/upload']");
    forms.forEach((form) => {
      const strategySelect = form.querySelector("select[name='multi_format_chunk_strategy']");
      const fields = form.querySelectorAll("[data-chunk-strategies]");
      if (!(strategySelect instanceof HTMLSelectElement) || !fields.length) {
        return;
      }
      if (strategySelect.dataset.chunkStrategyBound === "1") {
        return;
      }
      strategySelect.dataset.chunkStrategyBound = "1";

      const syncByChunkStrategy = () => {
        const current = (strategySelect.value || "").trim().toLowerCase() || "chunk_by_character";
        const locked = form.classList.contains("disabled-block");
        fields.forEach((field) => {
          if (!(field instanceof HTMLElement)) {
            return;
          }
          const allowed = (field.dataset.chunkStrategies || "")
            .split(/\s+/)
            .map((item) => item.trim().toLowerCase())
            .filter(Boolean);
          const show = !allowed.length || allowed.includes(current);
          field.classList.toggle("chunk-strategy-hidden", !show);
          field.hidden = !show;
          field.querySelectorAll("input, select, textarea").forEach((control) => {
            control.disabled = !show || locked;
          });
        });
      };

      strategySelect.addEventListener("change", syncByChunkStrategy);
      syncByChunkStrategy();
    });
  }

  function bindEnrichmentParams(scope = document) {
    const forms = scope.querySelectorAll("#section-create form[hx-post='/ui/create/upload']");
    forms.forEach((form) => {
      const toggles = form.querySelectorAll("select[data-enrichment-toggle]");
      if (!toggles.length) {
        return;
      }
      if (form.dataset.enrichmentParamsBound === "1") {
        return;
      }
      form.dataset.enrichmentParamsBound = "1";

      const syncByEnrichment = () => {
        const locked = form.classList.contains("disabled-block");
        toggles.forEach((toggle) => {
          if (!(toggle instanceof HTMLSelectElement)) {
            return;
          }
          const key = (toggle.dataset.enrichmentToggle || "").trim();
          if (!key) {
            return;
          }
          const card = form.querySelector(`[data-enrichment-card='${key}']`);
          const panel = form.querySelector(`[data-enrichment-panel-for='${key}']`);
          if (!(panel instanceof HTMLElement)) {
            return;
          }
          const enabled = (toggle.value || "").trim().toLowerCase() === "true";
          const cardHidden = card instanceof HTMLElement && card.hidden;
          panel.hidden = !enabled || cardHidden;
          panel.classList.toggle("enrichment-panel-hidden", !enabled || cardHidden);
          panel.querySelectorAll("input, select, textarea").forEach((control) => {
            control.disabled = !enabled || locked || cardHidden;
          });
        });
      };

      toggles.forEach((toggle) => {
        toggle.addEventListener("change", syncByEnrichment);
      });
      form.addEventListener("change", syncByEnrichment, true);
      syncByEnrichment();
    });
  }

  function bindDocPipelineParams(scope = document) {
    const forms = scope.querySelectorAll("#section-create form[hx-post='/ui/create/upload']");
    forms.forEach((form) => {
      const modeSelect = form.querySelector("select[name='doc_pipeline_mode'][data-doc-pipeline-mode]");
      const modeGroups = form.querySelectorAll("[data-doc-mode-for]");
      if (!(modeSelect instanceof HTMLSelectElement) || !modeGroups.length) {
        return;
      }

      const syncByMode = () => {
        const currentMode = (modeSelect.value || "").trim().toLowerCase();
        modeGroups.forEach((group) => {
          if (!(group instanceof HTMLElement)) {
            return;
          }
          const targetModes = (group.dataset.docModeFor || "")
            .trim()
            .toLowerCase()
            .split(/\s+/)
            .filter(Boolean);
          const show = targetModes.includes(currentMode);
          group.classList.toggle("doc-mode-hidden", !show);
          group.hidden = !show;
          group.setAttribute("aria-hidden", show ? "false" : "true");

          const controls = group.querySelectorAll("input, select, textarea");
          const locked = form.classList.contains("disabled-block");
          controls.forEach((control) => {
            control.disabled = !show || locked;
          });
        });
      };

      if (modeSelect.dataset.docModeBound !== "1") {
        modeSelect.dataset.docModeBound = "1";
        modeSelect.addEventListener("change", syncByMode);
        form.addEventListener("change", syncByMode, true);
      }

      syncByMode();
    });
  }

  app.bindAlgorithmParams = bindAlgorithmParams;
  app.bindDocPipelineParams = bindDocPipelineParams;
  app.bindPartitionRouteParams = bindPartitionRouteParams;
  app.bindProviderModelFilters = bindProviderModelFilters;
  app.bindEnrichmentParams = bindEnrichmentParams;
  app.bindChunkStrategyParams = bindChunkStrategyParams;

  app.registerBinder(bindAlgorithmParams);
  app.registerBinder(bindDocPipelineParams);
  app.registerBinder(bindPartitionRouteParams);
  app.registerBinder(bindProviderModelFilters);
  app.registerBinder(bindEnrichmentParams);
  app.registerBinder(bindChunkStrategyParams);
})(window);
