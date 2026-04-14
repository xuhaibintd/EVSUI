(function (global) {
  "use strict";

  const app = global.EVSUIApp;

  function renderPendingUploadPreview(previewPanel, files) {
    const items = files
      .map((file) => `<li><div class="file-main"><strong>${app.escapeHtml(file.name || "unnamed")}</strong><span>${Number(file.size || 0)} bytes</span></div></li>`)
      .join("");
    previewPanel.innerHTML = `
      <p class="uploaded-files-title">Uploading files (${files.length})</p>
      <p class="muted">Upload in progress...</p>
      <ul class="file-list small limit-3">${items}</ul>
    `;
  }

  async function uploadSelectedDocuments(fileInput, previewPanel) {
    const files = Array.from(fileInput.files || []);
    if (!files.length) {
      return;
    }

    const form = fileInput.closest("form");
    if (form instanceof HTMLFormElement) {
      form.dataset.uploadInProgress = "1";
      form.dispatchEvent(new CustomEvent("evsui:upload-state-changed"));
    }

    renderPendingUploadPreview(previewPanel, files);

    const formData = new FormData();
    files.forEach((file) => formData.append("files", file, file.name));

    try {
      const response = await fetch("/ui/create/upload-documents", {
        method: "POST",
        body: formData,
        credentials: "same-origin",
      });
      const html = await response.text();
      if (response.ok) {
        previewPanel.innerHTML = html || `<p class="uploaded-files-title">Uploaded files (${files.length})</p>`;
        fileInput.value = "";
        const shell = fileInput.closest("[data-file-shell]");
        const nameNode = shell ? shell.querySelector("[data-file-name]") : null;
        const defaultText = (fileInput.dataset.fileDefault || "No file selected").trim();
        if (nameNode instanceof HTMLElement) {
          nameNode.textContent = defaultText;
        }
        if (form instanceof HTMLFormElement) {
          form.dispatchEvent(new CustomEvent("evsui:uploaded-files-updated"));
        }
      } else {
        previewPanel.innerHTML = html || `<p class="status err">Upload failed: HTTP ${response.status}</p>`;
      }
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error);
      previewPanel.innerHTML = `<p class="status err">Upload failed: ${app.escapeHtml(message)}</p>`;
    } finally {
      if (form instanceof HTMLFormElement) {
        delete form.dataset.uploadInProgress;
        form.dispatchEvent(new CustomEvent("evsui:upload-state-changed"));
      }
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

  function bindCreateValidation(scope = document) {
    const createForm = scope.querySelector("#section-create form[hx-post='/ui/create/upload']");
    if (!(createForm instanceof HTMLFormElement)) {
      return;
    }
    if (createForm.dataset.validationBound === "1") {
      return;
    }
    createForm.dataset.validationBound = "1";

    const vectorStoreName = createForm.querySelector("[name='vector_store_name']");
    const docPipelineMode = createForm.querySelector("[name='doc_pipeline_mode']");
    const embeddingsModel = createForm.querySelector("[name='embeddings_model']");
    const objectNames = createForm.querySelector("[name='object_names']");
    const documentFiles = createForm.querySelector("[name='document_files']");
    const uploadInput = createForm.querySelector("input[type='file'][name='files']");
    const uploadedPreview = createForm.querySelector("[data-selected-doc-paths]");
    const createResult = document.querySelector("#create-result");

    const getUploadedCount = () => {
      const fallbackNode = createForm.querySelector("[data-uploaded-count]");
      const raw = createForm.dataset.uploadedCount || (fallbackNode instanceof HTMLElement ? fallbackNode.dataset.uploadedCount || "0" : "0");
      const count = Number.parseInt(raw, 10);
      return Number.isFinite(count) ? count : 0;
    };

    const getSelectedFileCount = () => {
      if (!(uploadInput instanceof HTMLInputElement) || !uploadInput.files) {
        return 0;
      }
      return Array.from(uploadInput.files).filter((file) => file && file.name).length;
    };

    const getDocumentFileCount = () => {
      if (!(documentFiles instanceof HTMLInputElement) && !(documentFiles instanceof HTMLTextAreaElement)) {
        return 0;
      }
      return String(documentFiles.value || "")
        .split(/[\n,]/)
        .map((item) => item.trim())
        .filter(Boolean).length;
    };

    const clearValidity = (field) => {
      if (
        field instanceof HTMLInputElement ||
        field instanceof HTMLSelectElement ||
        field instanceof HTMLTextAreaElement
      ) {
        field.setCustomValidity("");
      }
    };

    const isUploadInProgress = () => createForm.dataset.uploadInProgress === "1";

    const renderValidationMessage = (message) => {
      if (!(createResult instanceof HTMLElement) || !message) {
        return;
      }
      createResult.dataset.clientValidationMessage = "1";
      createResult.innerHTML = `<div class="result-box"><p class="status err">${app.escapeHtml(message)}</p></div>`;
    };

    const clearValidationMessage = () => {
      if (!(createResult instanceof HTMLElement)) {
        return;
      }
      if (createResult.dataset.clientValidationMessage !== "1") {
        return;
      }
      createResult.innerHTML = "";
      delete createResult.dataset.clientValidationMessage;
    };

    const clearSubmitProgress = () => {
      const submitButton = createForm.querySelector("[data-progress-button]");
      if (!(submitButton instanceof HTMLButtonElement)) {
        return;
      }
      if (typeof app.setProgressButtonState === "function") {
        app.setProgressButtonState(submitButton, false);
      }
    };

    const syncConditionalRules = () => {
      clearValidity(vectorStoreName);
      clearValidity(docPipelineMode);
      clearValidity(embeddingsModel);
      clearValidity(objectNames);
      clearValidity(documentFiles);
      clearValidity(uploadInput);

      const uploadedCount = getUploadedCount();
      const selectedFileCount = getSelectedFileCount();
      const documentFileCount = getDocumentFileCount();
      createForm.dataset.uploadedCount = String(uploadedCount);
      if (embeddingsModel instanceof HTMLSelectElement) {
        embeddingsModel.required = true;
        if (!embeddingsModel.value.trim()) {
          embeddingsModel.setCustomValidity("embeddings_model is required.");
        }
      }
      if (uploadInput instanceof HTMLInputElement) {
        uploadInput.required = false;
      }
      createForm.dataset.uploadMissing =
        uploadedCount === 0 && selectedFileCount === 0 && documentFileCount === 0 ? "1" : "0";
      if (objectNames instanceof HTMLInputElement) {
        objectNames.required = false;
      }
      if (!isUploadInProgress() && createForm.dataset.uploadMissing !== "1" && createForm.checkValidity()) {
        clearValidationMessage();
      }
    };

    [vectorStoreName, docPipelineMode, embeddingsModel, objectNames, documentFiles, uploadInput].forEach((field) => {
      if (
        field instanceof HTMLInputElement ||
        field instanceof HTMLSelectElement ||
        field instanceof HTMLTextAreaElement
      ) {
        field.addEventListener("input", syncConditionalRules);
        field.addEventListener("change", syncConditionalRules);
      }
    });

    const getValidationError = () => {
      syncConditionalRules();
      if (isUploadInProgress()) {
        return { kind: "message", text: "Documents are still uploading. Please wait." };
      }
      if (createForm.dataset.uploadMissing === "1") {
        return { kind: "message", text: "Upload at least one document before creating the vector store." };
      }
      if (!createForm.checkValidity()) {
        return { kind: "native" };
      }
      return null;
    };

    const validateBeforeSubmit = () => {
      const error = getValidationError();
      if (!error) {
        clearValidationMessage();
        return true;
      }
      clearSubmitProgress();
      if (error.kind === "message") {
        renderValidationMessage(error.text);
        return false;
      }
      clearValidationMessage();
      createForm.reportValidity();
      return false;
    };

    createForm.addEventListener(
      "submit",
      (event) => {
        if (!validateBeforeSubmit()) {
          event.preventDefault();
        }
      },
      true
    );

    createForm.addEventListener("htmx:beforeRequest", (event) => {
      const source = event.detail && event.detail.elt;
      if (source !== createForm) {
        return;
      }
      if (!validateBeforeSubmit()) {
        event.preventDefault();
      }
    });

    createForm.addEventListener("evsui:uploaded-files-updated", syncConditionalRules);
    createForm.addEventListener("evsui:upload-state-changed", syncConditionalRules);
    if (uploadedPreview instanceof HTMLElement && uploadedPreview.dataset.validationObserverBound !== "1") {
      uploadedPreview.dataset.validationObserverBound = "1";
      const observer = new MutationObserver(() => {
        const node = uploadedPreview.querySelector("[data-uploaded-count]");
        if (node instanceof HTMLElement) {
          createForm.dataset.uploadedCount = node.dataset.uploadedCount || "0";
        }
        syncConditionalRules();
      });
      observer.observe(uploadedPreview, { childList: true, subtree: true, attributes: true });
    }

    syncConditionalRules();
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
  app.bindCreateValidation = bindCreateValidation;

  app.registerBinder(bindCreateFileUpload);
  app.registerBinder(bindCustomFileInputs);
  app.registerBinder(enforceCreateInputLength);
  app.registerBinder(bindCreateValidation);
})(window);

