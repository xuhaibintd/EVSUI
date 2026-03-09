(function (global) {
  "use strict";

  const app = global.EVSUIApp;

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
      previewPanel.innerHTML = `<p class="status err">Upload failed: ${app.escapeHtml(message)}</p>`;
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
        if (!input.disabled) {
          input.click();
        }
      });

      input.addEventListener("change", updateName);
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

  app.bindCreateFileUpload = bindCreateFileUpload;
  app.bindCustomFileInputs = bindCustomFileInputs;
  app.enforceCreateInputLength = enforceCreateInputLength;

  app.registerBinder(bindCreateFileUpload);
  app.registerBinder(bindCustomFileInputs);
  app.registerBinder(enforceCreateInputLength);
})(window);
