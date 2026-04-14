(function (global) {
  "use strict";

  const app = global.EVSUIApp;

  function bindListRowSelection(scope = document) {
    const tables = scope.querySelectorAll("[data-vs-select-table]");
    tables.forEach((table) => {
      const card = table.closest(".monitor-card-list");
      const hiddenInput = card ? card.querySelector("[data-destroy-vs-input]") : null;
      const selectedName = card ? card.querySelector("[data-destroy-selected-name]") : null;
      const destroyButton = card ? card.querySelector("[data-destroy-btn]") : null;
      const feedback = card ? card.querySelector("[data-destroy-feedback]") : null;

      const rows = table.querySelectorAll("tbody tr[data-vs-name]");
      rows.forEach((row) => {
        if (row.dataset.selectBound === "1") {
          return;
        }
        row.dataset.selectBound = "1";
        row.addEventListener("click", () => {
          const vsName = (row.dataset.vsName || "").trim();
          if (!vsName) {
            return;
          }
          rows.forEach((item) => item.classList.remove("is-selected"));
          row.classList.add("is-selected");
          if (hiddenInput instanceof HTMLInputElement) {
            hiddenInput.value = vsName;
          }
          if (selectedName instanceof HTMLElement) {
            selectedName.textContent = vsName;
          }
          if (destroyButton instanceof HTMLButtonElement) {
            destroyButton.disabled = false;
          }
          if (feedback) {
            feedback.textContent = `Selected '${vsName}'. Click Delete to delete.`;
            feedback.classList.remove("ok", "warn", "err");
            feedback.classList.add("neutral");
          }

          const chatVsField = document.querySelector("[name='selected_vs_name'][data-chat-selected-vs]");
          if (chatVsField instanceof HTMLInputElement || chatVsField instanceof HTMLSelectElement) {
            chatVsField.value = vsName;
          }
          const chatVsLabel = document.querySelector("[data-chat-selected-vs-label]");
          if (chatVsLabel instanceof HTMLElement) {
            chatVsLabel.textContent = vsName;
          }
        });
      });
    });
  }

  function bindDestroyConfirmModal(scope = document) {
    const panels = scope.querySelectorAll("[data-vs-destroy-panel]");
    panels.forEach((panel) => {
      const triggerButton = panel.querySelector("[data-destroy-btn]");
      const destroyForm = triggerButton ? triggerButton.closest("form") : null;
      const modal = panel.querySelector("[data-destroy-confirm]");
      const modalName = panel.querySelector("[data-confirm-vs-name]");
      const selectedName = panel.querySelector("[data-destroy-selected-name]");
      const feedback = panel.querySelector("[data-destroy-feedback]");
      const cancelButtons = panel.querySelectorAll("[data-confirm-cancel]");
      const okButton = panel.querySelector("[data-confirm-ok]");
      if (!(triggerButton instanceof HTMLButtonElement) || !(destroyForm instanceof HTMLFormElement) || !(modal instanceof HTMLElement)) {
        return;
      }
      if (triggerButton.dataset.confirmBound === "1") {
        return;
      }
      triggerButton.dataset.confirmBound = "1";

      const closeModal = () => {
        modal.hidden = true;
        document.body.classList.remove("confirm-open");
      };

      const currentVsName = () => (selectedName && selectedName.textContent ? selectedName.textContent : "").trim() || "(none)";

      const openModal = () => {
        const name = currentVsName();
        if (modalName) {
          modalName.textContent = name;
        }
        modal.hidden = false;
        document.body.classList.add("confirm-open");
        if (okButton instanceof HTMLButtonElement) {
          okButton.focus();
        }
      };

      triggerButton.addEventListener("click", (event) => {
        if (triggerButton.dataset.confirmArmed === "1") {
          delete triggerButton.dataset.confirmArmed;
          return;
        }
        event.preventDefault();
        openModal();
      });

      cancelButtons.forEach((button) => {
        button.addEventListener("click", closeModal);
      });

      if (okButton instanceof HTMLButtonElement) {
        okButton.addEventListener("click", () => {
          const name = currentVsName();
          closeModal();
          if (feedback instanceof HTMLElement) {
            feedback.textContent = `Deleting '${name}'...`;
            feedback.classList.remove("ok", "warn", "err");
            feedback.classList.add("neutral");
          }
          if (typeof destroyForm.requestSubmit === "function") {
            destroyForm.requestSubmit(triggerButton);
            return;
          }
          triggerButton.dataset.confirmArmed = "1";
          setTimeout(() => triggerButton.click(), 0);
        });
      }

      destroyForm.addEventListener("htmx:afterRequest", (event) => {
        const source = event.detail && event.detail.elt;
        if (source !== destroyForm) {
          return;
        }
        if (event.detail && event.detail.successful) {
          return;
        }
        if (feedback instanceof HTMLElement) {
          const xhr = event.detail && event.detail.xhr;
          const status = xhr && typeof xhr.status === "number" ? xhr.status : 0;
          const suffix = status ? ` (HTTP ${status})` : "";
          feedback.textContent = `Delete request failed for '${currentVsName()}'.${suffix}`;
          feedback.classList.remove("ok", "neutral");
          feedback.classList.add("err");
        }
      });

      destroyForm.addEventListener("htmx:sendError", (event) => {
        const source = event.detail && event.detail.elt;
        if (source !== destroyForm) {
          return;
        }
        if (feedback instanceof HTMLElement) {
          feedback.textContent = `Delete request could not be sent for '${currentVsName()}'.`;
          feedback.classList.remove("ok", "neutral");
          feedback.classList.add("err");
        }
      });

      destroyForm.addEventListener("htmx:timeout", (event) => {
        const source = event.detail && event.detail.elt;
        if (source !== destroyForm) {
          return;
        }
        if (feedback instanceof HTMLElement) {
          feedback.textContent = `Delete request timed out for '${currentVsName()}'.`;
          feedback.classList.remove("ok", "neutral");
          feedback.classList.add("err");
        }
      });

      panel.addEventListener("keydown", (event) => {
        if (event.key === "Escape" && !modal.hidden) {
          event.preventDefault();
          closeModal();
        }
      });
    });
  }

  app.bindListRowSelection = bindListRowSelection;
  app.bindDestroyConfirmModal = bindDestroyConfirmModal;

  app.registerBinder(bindListRowSelection);
  app.registerBinder(bindDestroyConfirmModal);
})(window);
