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

  app.registerBinder(bindAlgorithmParams);
  app.registerBinder(bindDocPipelineParams);
  app.registerBinder(bindPartitionRouteParams);
})(window);
