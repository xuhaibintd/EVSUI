(function (global) {
  "use strict";

  const app = global.EVSUIApp;

  function pretty(value) {
    try {
      return JSON.stringify(value, null, 2);
    } catch (error) {
      return String(value || "");
    }
  }

  function normalize(value) {
    return String(value || "").toLowerCase();
  }

  function parseItemJson(item) {
    try {
      return JSON.parse(item.dataset.json || "{}");
    } catch (error) {
      return { error: "Invalid embedded JSON", detail: String(error) };
    }
  }

  function setActiveTab(viewer, activeName) {
    viewer.querySelectorAll("[data-json-viewer-tab]").forEach((button) => {
      button.classList.toggle("is-active", button.dataset.jsonViewerTab === activeName);
    });
  }

  function renderSelection(viewer, item, mode) {
    if (!item) {
      return;
    }
    const data = parseItemJson(item);
    const activeMode = mode || viewer.dataset.activeJsonViewerTab || "json";
    viewer.dataset.activeJsonViewerTab = activeMode;
    setActiveTab(viewer, activeMode);

    viewer.querySelectorAll("[data-json-viewer-item]").forEach((candidate) => {
      candidate.classList.toggle("is-selected", candidate === item);
    });

    const title = viewer.querySelector("[data-json-viewer-title]");
    const subtitle = viewer.querySelector("[data-json-viewer-subtitle]");
    const path = viewer.querySelector("[data-json-viewer-path]");
    const code = viewer.querySelector("[data-json-viewer-code]");

    if (title) {
      title.textContent = `#${item.dataset.index || ""} ${item.dataset.type || "UNKNOWN"}`;
    }
    if (subtitle) {
      subtitle.textContent = `page=${item.dataset.page || "-"}  element_id=${item.dataset.elementId || ""}`;
    }
    if (path) {
      path.textContent = `metadata.parent_id=${item.dataset.parentId || "-"}  category_depth=${item.dataset.depth || "-"}`;
    }
    if (!code) {
      return;
    }

    if (activeMode === "metadata") {
      code.textContent = pretty(data.metadata || {});
    } else if (activeMode === "text") {
      code.textContent = String(data.text || "");
    } else {
      code.textContent = pretty(data);
    }
  }

  function applyFilters(viewer) {
    const query = normalize(viewer.querySelector("[data-json-viewer-filter]")?.value);
    const type = normalize(viewer.querySelector("[data-json-viewer-type]")?.value);
    const items = Array.from(viewer.querySelectorAll("[data-json-viewer-item]"));
    let firstVisible = null;

    items.forEach((item) => {
      const haystack = normalize([
        item.dataset.type,
        item.dataset.page,
        item.dataset.elementId,
        item.dataset.parentId,
        item.dataset.depth,
        item.dataset.text,
      ].join(" "));
      const matchesType = !type || normalize(item.dataset.type) === type;
      const matchesQuery = !query || haystack.includes(query);
      const visible = matchesType && matchesQuery;
      item.hidden = !visible;
      if (visible && !firstVisible) {
        firstVisible = item;
      }
    });

    const selected = viewer.querySelector("[data-json-viewer-item].is-selected:not([hidden])");
    if (!selected && firstVisible) {
      renderSelection(viewer, firstVisible, viewer.dataset.activeJsonViewerTab || "json");
    }
  }

  function bindViewer(viewer) {
    if (!(viewer instanceof HTMLElement) || viewer.dataset.jsonViewerBound === "1") {
      return;
    }
    viewer.dataset.jsonViewerBound = "1";
    viewer.dataset.activeJsonViewerTab = "json";

    viewer.addEventListener("click", (event) => {
      const item = event.target.closest("[data-json-viewer-item]");
      if (item && viewer.contains(item)) {
        event.preventDefault();
        renderSelection(viewer, item, viewer.dataset.activeJsonViewerTab || "json");
        return;
      }
      const tab = event.target.closest("[data-json-viewer-tab]");
      if (tab && viewer.contains(tab)) {
        event.preventDefault();
        const selected = viewer.querySelector("[data-json-viewer-item].is-selected") || viewer.querySelector("[data-json-viewer-item]:not([hidden])");
        renderSelection(viewer, selected, tab.dataset.jsonViewerTab || "json");
      }
    });

    viewer.querySelectorAll("[data-json-viewer-filter], [data-json-viewer-type]").forEach((control) => {
      control.addEventListener("input", () => applyFilters(viewer));
      control.addEventListener("change", () => applyFilters(viewer));
    });

    renderSelection(viewer, viewer.querySelector("[data-json-viewer-item]"), "json");
  }

  function bindJsonInspectors(scope = document) {
    scope.querySelectorAll("[data-json-viewer]").forEach(bindViewer);
  }

  app.bindJsonInspectors = bindJsonInspectors;
  app.registerBinder(bindJsonInspectors);
})(window);
