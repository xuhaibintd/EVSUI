(function (global) {
  "use strict";

  const app = global.EVSUIApp;

  function bindResourceFilter(scope = document) {
    scope.querySelectorAll("[data-resource-inventory]").forEach((inventory) => {
      const input = inventory.querySelector("[data-resource-filter]");
      const rows = Array.from(inventory.querySelectorAll("[data-resource-row]"));
      const empty = inventory.querySelector("[data-resource-filter-empty]");
      if (!(input instanceof HTMLInputElement) || input.dataset.filterBound === "1") {
        return;
      }
      input.dataset.filterBound = "1";
      input.addEventListener("input", () => {
        const query = input.value.trim().toLocaleLowerCase();
        let visible = 0;
        rows.forEach((row) => {
          const matches = !query || (row.textContent || "").toLocaleLowerCase().includes(query);
          row.hidden = !matches;
          if (matches) {
            visible += 1;
          }
        });
        if (empty instanceof HTMLElement) {
          empty.hidden = visible !== 0;
        }
      });
    });
  }

  function bindResourceKeyboardSelection(scope = document) {
    scope.querySelectorAll("[data-resource-row]").forEach((row) => {
      if (row.dataset.keyboardBound === "1") {
        return;
      }
      row.dataset.keyboardBound = "1";
      row.addEventListener("keydown", (event) => {
        if (event.key !== "Enter" && event.key !== " ") {
          return;
        }
        event.preventDefault();
        row.click();
      });
    });
  }

  function bindResourceSelection(scope = document) {
    scope.querySelectorAll("[data-resource-inventory]").forEach((inventory) => {
      if (inventory.dataset.selectionBound === "1") {
        return;
      }
      inventory.dataset.selectionBound = "1";
      const rows = Array.from(inventory.querySelectorAll("[data-resource-row]"));
      const selection = inventory.querySelector("[data-resource-selection]");
      if (!(selection instanceof HTMLElement)) {
        return;
      }
      const selectedName = selection.querySelector("[data-destroy-selected-name]");
      const nameInput = selection.querySelector("[data-destroy-vs-input]");
      const kindInput = selection.querySelector("[data-destroy-kind-input]");
      const deleteButton = selection.querySelector("[data-destroy-btn]");
      const userRole = selection.dataset.userRole || "viewer";

      const selectRow = (row) => {
        const name = row.dataset.vsName || "";
        const kind = row.dataset.resourceKind || "";
        rows.forEach((candidate) => {
          const active = candidate === row;
          candidate.classList.toggle("is-selected", active);
          candidate.setAttribute("aria-selected", active ? "true" : "false");
        });
        if (selectedName instanceof HTMLElement) {
          selectedName.textContent = name || "None";
        }
        if (nameInput instanceof HTMLInputElement) {
          nameInput.value = name;
        }
        if (kindInput instanceof HTMLInputElement) {
          kindInput.value = kind;
        }
        if (deleteButton instanceof HTMLButtonElement) {
          const allowed = Boolean(name) && (userRole === "admin" || (userRole === "operator" && kind === "v1"));
          deleteButton.disabled = !allowed;
          deleteButton.setAttribute("aria-disabled", allowed ? "false" : "true");
        }
      };

      rows.forEach((row) => row.addEventListener("click", () => selectRow(row)));
    });
  }

  app.bindResourceFilter = bindResourceFilter;
  app.bindResourceKeyboardSelection = bindResourceKeyboardSelection;
  app.bindResourceSelection = bindResourceSelection;
  app.registerBinder(bindResourceFilter);
  app.registerBinder(bindResourceKeyboardSelection);
  app.registerBinder(bindResourceSelection);
})(window);
