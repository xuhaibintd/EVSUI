let stepGate = null;

function escapeHtml(value) {
  return String(value)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/\"/g, "&quot;")
    .replace(/'/g, "&#39;");
}

async function uploadSelectedDocuments(fileInput, previewPanel) {
  const files = Array.from(fileInput.files || []);
  if (!files.length) {
    return;
  }

  previewPanel.innerHTML = `<p class="muted">Uploading ${files.length} file(s)...</p>`;

  const formData = new FormData();
  files.forEach((file) => formData.append("files", file, file.name));

  try {
    const response = await fetch("/ui/create/upload-documents", {
      method: "POST",
      body: formData,
      credentials: "same-origin",
    });
    const html = await response.text();
    previewPanel.innerHTML = html;

    if (response.ok) {
      // Prevent duplicate re-upload in /ui/create/upload after successful pre-upload.
      fileInput.value = "";
      const shell = fileInput.closest("[data-file-shell]");
      const nameNode = shell ? shell.querySelector("[data-file-name]") : null;
      const defaultText = (fileInput.dataset.fileDefault || "No file selected").trim();
      if (nameNode instanceof HTMLElement) {
        nameNode.textContent = defaultText;
      }
    }
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error);
    previewPanel.innerHTML = `<p class="status err">Upload failed: ${escapeHtml(message)}</p>`;
  }
}

function bindCreateFileUpload(scope = document) {
  const fileInput = scope.querySelector("input[type='file'][name='files']");
  const previewPanel = scope.querySelector("[data-selected-doc-paths]");
  if (!(fileInput instanceof HTMLInputElement) || !previewPanel) {
    return;
  }
  if (fileInput.dataset.uploadBound === "1") {
    return;
  }

  fileInput.dataset.uploadBound = "1";
  fileInput.addEventListener("change", () => uploadSelectedDocuments(fileInput, previewPanel));
}

function bindCustomFileInputs(scope = document) {
  const shells = scope.querySelectorAll("[data-file-shell]");
  shells.forEach((shell) => {
    const input = shell.querySelector("[data-file-input]");
    const trigger = shell.querySelector("[data-file-trigger]");
    const nameNode = shell.querySelector("[data-file-name]");
    if (!(input instanceof HTMLInputElement) || !(trigger instanceof HTMLButtonElement) || !(nameNode instanceof HTMLElement)) {
      return;
    }
    if (shell.dataset.fileBound === "1") {
      trigger.disabled = input.disabled;
      return;
    }
    shell.dataset.fileBound = "1";

    const defaultText = (input.dataset.fileDefault || "No file selected").trim();
    const multiLabel = (input.dataset.fileMultiLabel || "files selected").trim();
    const updateName = () => {
      const files = input.files ? Array.from(input.files) : [];
      if (!files.length) {
        nameNode.textContent = defaultText;
        return;
      }
      if (files.length === 1) {
        nameNode.textContent = files[0].name || defaultText;
        return;
      }
      nameNode.textContent = `${files.length} ${multiLabel}`;
    };

    trigger.disabled = input.disabled;
    updateName();

    trigger.addEventListener("click", () => {
      if (input.disabled) {
        return;
      }
      input.click();
    });

    input.addEventListener("change", () => {
      updateName();
    });

    input.addEventListener("htmx:afterRequest", () => {
      if (!input.files || input.files.length === 0) {
        nameNode.textContent = defaultText;
      }
    });
  });
}

function enforceCreateInputLength(scope = document) {
  const fields = scope.querySelectorAll("#section-create input:not([type='file']), #section-create textarea");
  const clamp = (field) => {
    if (!(field instanceof HTMLInputElement) && !(field instanceof HTMLTextAreaElement)) {
      return;
    }
    if (field.value.length > 50) {
      field.value = field.value.slice(0, 50);
    }
  };

  fields.forEach((field) => {
    if (!(field instanceof HTMLInputElement) && !(field instanceof HTMLTextAreaElement)) {
      return;
    }
    if (!(field instanceof HTMLInputElement && field.type === "number")) {
      field.maxLength = 50;
    }
    clamp(field);
    if (field.dataset.lengthBound === "1") {
      return;
    }
    field.dataset.lengthBound = "1";
    field.addEventListener("input", () => clamp(field));
    field.addEventListener("paste", () => setTimeout(() => clamp(field), 0));
  });

  const createForm = scope.querySelector("#section-create form[hx-post='/ui/create/upload']");
  if (createForm instanceof HTMLFormElement && createForm.dataset.lengthBound !== "1") {
    createForm.dataset.lengthBound = "1";
    createForm.addEventListener(
      "submit",
      () => {
        const submitFields = createForm.querySelectorAll("input:not([type='file']), textarea");
        submitFields.forEach((item) => clamp(item));
      },
      true
    );
  }
}

function bindAlgorithmParams(scope = document) {
  const forms = scope.querySelectorAll("#section-create form[hx-post='/ui/create/upload']");
  forms.forEach((form) => {
    const algorithmSelect = form.querySelector("select[name='search_algorithm']");
    const panel = form.querySelector("[data-algorithm-panel]");
    const fields = form.querySelectorAll("[data-algo-for]");
    const hint = form.querySelector("[data-algo-hint]");
    if (!(algorithmSelect instanceof HTMLSelectElement) || !panel || !fields.length) {
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

    fields.forEach((field) => {
      if (!(field instanceof HTMLElement)) {
        return;
      }
      const controls = field.querySelectorAll("input, select, textarea");
      controls.forEach((control) => {
        const key = "algoInitialDisabled";
        if (control.dataset[key] == null) {
          control.dataset[key] = control.disabled ? "1" : "0";
        }
      });
    });

    const syncByAlgorithm = () => {
      const current = (algorithmSelect.value || "VECTORDISTANCE").trim().toUpperCase();
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
          const initialDisabled = control.dataset.algoInitialDisabled === "1";
          control.disabled = !show || initialDisabled;
        });
      });

      if (hint instanceof HTMLElement) {
        hint.textContent = labels[current] || "VECTORDISTANCE";
      }
    };

    algorithmSelect.addEventListener("change", syncByAlgorithm);
    syncByAlgorithm();
  });
}

function bindListRowSelection(scope = document) {
  const tables = scope.querySelectorAll("[data-vs-select-table]");
  tables.forEach((table) => {
    const card = table.closest(".monitor-card-list");
    if (!card) {
      return;
    }
    const hiddenInput = card.querySelector("[data-destroy-vs-input]");
    const selectedName = card.querySelector("[data-destroy-selected-name]");
    const destroyButton = card.querySelector("[data-destroy-btn]");
    const feedback = card.querySelector("[data-destroy-feedback]");
    if (!(hiddenInput instanceof HTMLInputElement)) {
      return;
    }

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
        hiddenInput.value = vsName;
        if (selectedName) {
          selectedName.textContent = vsName;
        }
        if (destroyButton instanceof HTMLButtonElement) {
          destroyButton.disabled = false;
        }
        if (feedback) {
          feedback.textContent = `Selected '${vsName}'. Click Destroy Selected to delete.`;
          feedback.classList.remove("ok", "warn", "err");
          feedback.classList.add("neutral");
        }
      });
    });
  });
}

function bindDestroyConfirmModal(scope = document) {
  const panels = scope.querySelectorAll("[data-vs-destroy-panel]");
  panels.forEach((panel) => {
    const triggerButton = panel.querySelector("[data-destroy-btn]");
    const modal = panel.querySelector("[data-destroy-confirm]");
    const modalName = panel.querySelector("[data-confirm-vs-name]");
    const selectedName = panel.querySelector("[data-destroy-selected-name]");
    const cancelButtons = panel.querySelectorAll("[data-confirm-cancel]");
    const okButton = panel.querySelector("[data-confirm-ok]");
    if (!(triggerButton instanceof HTMLButtonElement) || !(modal instanceof HTMLElement)) {
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

    const openModal = () => {
      const currentName = (selectedName && selectedName.textContent ? selectedName.textContent : "").trim() || "(none)";
      if (modalName) {
        modalName.textContent = currentName;
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
      button.addEventListener("click", () => closeModal());
    });

    if (okButton instanceof HTMLButtonElement) {
      okButton.addEventListener("click", () => {
        closeModal();
        triggerButton.dataset.confirmArmed = "1";
        setTimeout(() => triggerButton.click(), 0);
      });
    }

    panel.addEventListener("keydown", (event) => {
      if (event.key === "Escape" && !modal.hidden) {
        event.preventDefault();
        closeModal();
      }
    });
  });
}

document.body.addEventListener("htmx:afterSwap", (event) => {
  const target = event.target;
  if (target && target.id === "chat-messages") {
    target.scrollTop = target.scrollHeight;
  }
  if (stepGate && target && target.id === "section-connect-content") {
    stepGate.syncStepConnectionState(target);
  }
  bindCreateFileUpload(document);
  bindCustomFileInputs(document);
  enforceCreateInputLength(document);
  bindAlgorithmParams(document);
  bindListRowSelection(document);
  bindDestroyConfirmModal(document);
});

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

document.addEventListener("click", (event) => {
  const menuButton = event.target.closest(".menu-item");
  if (menuButton) {
    if (stepGate) {
      stepGate.activateSection(menuButton.dataset.section);
    }
    return;
  }

  const navButton = event.target.closest(".wizard-btn[data-target]");
  if (navButton && stepGate) {
    stepGate.activateSection(navButton.dataset.target);
  }
});

document.addEventListener("DOMContentLoaded", () => {
  if (typeof window.createStepGate === "function") {
    stepGate = window.createStepGate();
    stepGate.initialize();
  }
  registerHtmxProgressButtons();
  bindCreateFileUpload(document);
  bindCustomFileInputs(document);
  enforceCreateInputLength(document);
  bindAlgorithmParams(document);
  bindListRowSelection(document);
  bindDestroyConfirmModal(document);
});

