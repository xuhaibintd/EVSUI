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
          hint.textContent = labels[current] || "";
        }
      };

      algorithmSelect.addEventListener("change", syncByAlgorithm);
      syncByAlgorithm();
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
      }

      syncByMode();
    });
  }

  app.bindAlgorithmParams = bindAlgorithmParams;
  app.bindDocPipelineParams = bindDocPipelineParams;

  app.registerBinder(bindAlgorithmParams);
  app.registerBinder(bindDocPipelineParams);
})(window);
