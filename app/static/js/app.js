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

document.body.addEventListener("htmx:afterSwap", (event) => {
  const target = event.target;
  if (target && target.id === "chat-messages") {
    target.scrollTop = target.scrollHeight;
  }
  if (stepGate && target && target.id === "section-connect-content") {
    stepGate.syncStepConnectionState(target);
  }
  bindCreateFileUpload(document);
  enforceCreateInputLength(document);
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
  enforceCreateInputLength(document);
});
