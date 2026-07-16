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
    const getBookragLoadedRunSelect = () =>
      createForm.querySelector("select[name='bookrag_loaded_csv_run_id']:not([disabled])");
    const getMultiFormatLoadedRunSelect = () =>
      createForm.querySelector("select[name='multi_format_loaded_csv_run_id']:not([disabled])");
    const docPipelineMode = createForm.querySelector("[name='doc_pipeline_mode']");
    const embeddingsModel = createForm.querySelector("[name='embeddings_model']");
    const objectNames = createForm.querySelector("[name='object_names']");
    const documentFiles = createForm.querySelector("[name='document_files']");
    const uploadInput = createForm.querySelector("input[type='file'][name='files']");
    const uploadedPreview = createForm.querySelector("[data-selected-doc-paths]");
    const parseButton = createForm.querySelector("[data-bookrag-parse-button]");
    const csvButton = createForm.querySelector("[data-bookrag-csv-button]");
    const csvVectorStoreName = createForm.querySelector("[data-bookrag-csv-vector-store-name]");
    const csvTargetDatabase = createForm.querySelector("[data-bookrag-csv-target-database]");
    const parseRunSelect = createForm.querySelector("[data-bookrag-parse-run-select]");
    const csvGenerationResult = createForm.querySelector("#bookrag-csv-generation-result");
    const multiFormatParseButton = createForm.querySelector("[data-multi-format-parse-button]");
    const multiFormatCsvButton = createForm.querySelector("[data-multi-format-csv-button]");
    const multiFormatCsvVectorStoreName = createForm.querySelector("[data-multi-format-csv-vector-store-name]");
    const multiFormatCsvTargetDatabase = createForm.querySelector("[data-multi-format-csv-target-database]");
    const multiFormatParseRunSelect = createForm.querySelector("[data-multi-format-parse-run-select]");
    const multiFormatCsvGenerationResult = createForm.querySelector("#multi-format-csv-generation-result");
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
      const submitButton = createForm.querySelector("button[type='submit'][data-progress-button]");
      if (!(submitButton instanceof HTMLButtonElement)) {
        return;
      }
      if (typeof app.setProgressButtonState === "function") {
        app.setProgressButtonState(submitButton, false);
      }
    };

    const syncConditionalRules = () => {
      clearValidity(vectorStoreName);
      clearValidity(getBookragLoadedRunSelect());
      clearValidity(getMultiFormatLoadedRunSelect());
      clearValidity(docPipelineMode);
      clearValidity(embeddingsModel);
      clearValidity(objectNames);
      clearValidity(documentFiles);
      clearValidity(uploadInput);

      const uploadedCount = getUploadedCount();
      const selectedFileCount = getSelectedFileCount();
      const documentFileCount = getDocumentFileCount();
      const isBookrag = docPipelineMode instanceof HTMLSelectElement && docPipelineMode.value === "multi_format_bookrag";
      const isMultiFormat = docPipelineMode instanceof HTMLSelectElement && docPipelineMode.value === "multi_format";
      const loadedRunSelect = getBookragLoadedRunSelect();
      const multiFormatLoadedRunSelect = getMultiFormatLoadedRunSelect();
      const hasLoadedBookragRun =
        isBookrag && loadedRunSelect instanceof HTMLSelectElement && Boolean(loadedRunSelect.value.trim());
      const hasLoadedMultiFormatRun =
        isMultiFormat && multiFormatLoadedRunSelect instanceof HTMLSelectElement && Boolean(multiFormatLoadedRunSelect.value.trim());
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
        !hasLoadedBookragRun && !hasLoadedMultiFormatRun && uploadedCount === 0 && selectedFileCount === 0 && documentFileCount === 0 ? "1" : "0";
      if (parseButton instanceof HTMLButtonElement && !parseButton.classList.contains("is-loading")) {
        const formLocked = createForm.classList.contains("disabled-block");
        parseButton.disabled = formLocked || !isBookrag || isUploadInProgress() || uploadedCount === 0;
      }
      if (csvButton instanceof HTMLButtonElement && !csvButton.classList.contains("is-loading")) {
        const hasParseRun = parseRunSelect instanceof HTMLSelectElement && Boolean(parseRunSelect.value.trim());
        csvButton.disabled = !hasParseRun;
      }
      if (multiFormatParseButton instanceof HTMLButtonElement && !multiFormatParseButton.classList.contains("is-loading")) {
        const formLocked = createForm.classList.contains("disabled-block");
        multiFormatParseButton.disabled = formLocked || !isMultiFormat || isUploadInProgress() || uploadedCount === 0;
      }
      if (multiFormatCsvButton instanceof HTMLButtonElement && !multiFormatCsvButton.classList.contains("is-loading")) {
        const hasParseRun = multiFormatParseRunSelect instanceof HTMLSelectElement && Boolean(multiFormatParseRunSelect.value.trim());
        multiFormatCsvButton.disabled = !hasParseRun;
      }
      if (objectNames instanceof HTMLInputElement) {
        objectNames.required = false;
      }
      if (!isUploadInProgress() && createForm.dataset.uploadMissing !== "1" && createForm.checkValidity()) {
        clearValidationMessage();
      }
    };

    [vectorStoreName, docPipelineMode, embeddingsModel, objectNames, documentFiles, uploadInput, csvVectorStoreName, csvTargetDatabase, parseRunSelect, multiFormatCsvVectorStoreName, multiFormatCsvTargetDatabase, multiFormatParseRunSelect].forEach((field) => {
      if (
        field instanceof HTMLInputElement ||
        field instanceof HTMLSelectElement ||
        field instanceof HTMLTextAreaElement
      ) {
        field.addEventListener("input", syncConditionalRules);
        field.addEventListener("change", syncConditionalRules);
      }
    });
    createForm.addEventListener("change", syncConditionalRules, true);

    if (csvVectorStoreName instanceof HTMLInputElement && vectorStoreName instanceof HTMLInputElement) {
      csvVectorStoreName.addEventListener("input", () => {
        csvVectorStoreName.dataset.userEdited = "1";
      });
      const syncCsvTargetName = () => {
        if (csvVectorStoreName.dataset.userEdited !== "1") {
          csvVectorStoreName.value = vectorStoreName.value;
          syncConditionalRules();
        }
      };
      vectorStoreName.addEventListener("input", syncCsvTargetName);
      vectorStoreName.addEventListener("change", syncCsvTargetName);
    }

    const clearCsvValidationMessage = () => {
      if (!(csvGenerationResult instanceof HTMLElement)) {
        return;
      }
      if (csvGenerationResult.dataset.clientValidationMessage !== "1") {
        return;
      }
      csvGenerationResult.innerHTML = "";
      delete csvGenerationResult.dataset.clientValidationMessage;
    };

    const renderCsvValidationMessage = (message) => {
      if (!(csvGenerationResult instanceof HTMLElement)) {
        return;
      }
      csvGenerationResult.dataset.clientValidationMessage = "1";
      csvGenerationResult.innerHTML = `<div class="bookrag-parse-result bookrag-parse-result-error"><p><strong>Cannot generate CSV.</strong> ${app.escapeHtml(message)}</p></div>`;
    };

    const validateCsvGeneration = () => {
      if (!(parseRunSelect instanceof HTMLSelectElement) || !parseRunSelect.value.trim()) {
        renderCsvValidationMessage("Select a completed JSON parsing run.");
        parseRunSelect?.focus();
        return false;
      }
      if (!(csvVectorStoreName instanceof HTMLInputElement) || !csvVectorStoreName.value.trim()) {
        renderCsvValidationMessage("Enter the Target Vector Store Name.");
        csvVectorStoreName?.focus();
        return false;
      }
      if (!(csvTargetDatabase instanceof HTMLInputElement) || !csvTargetDatabase.value.trim()) {
        renderCsvValidationMessage("Enter the Target Database.");
        csvTargetDatabase?.focus();
        return false;
      }
      clearCsvValidationMessage();
      return true;
    };

    if (csvButton instanceof HTMLButtonElement) {
      csvButton.addEventListener(
        "click",
        (event) => {
          if (validateCsvGeneration()) {
            return;
          }
          event.preventDefault();
          event.stopImmediatePropagation();
        },
        true
      );
    }

    const validateMultiFormatCsvGeneration = () => {
      const resultNode = multiFormatCsvGenerationResult;
      const renderMessage = (message) => {
        if (!(resultNode instanceof HTMLElement)) {
          return;
        }
        resultNode.dataset.clientValidationMessage = "1";
        resultNode.innerHTML = `<div class="bookrag-parse-result bookrag-parse-result-error"><p><strong>Cannot generate CSV.</strong> ${app.escapeHtml(message)}</p></div>`;
      };
      if (!(multiFormatParseRunSelect instanceof HTMLSelectElement) || !multiFormatParseRunSelect.value.trim()) {
        renderMessage("Select a completed Multi-Format JSON parsing run.");
        multiFormatParseRunSelect?.focus();
        return false;
      }
      if (!(multiFormatCsvVectorStoreName instanceof HTMLInputElement) || !multiFormatCsvVectorStoreName.value.trim()) {
        renderMessage("Enter the Target Vector Store Name.");
        multiFormatCsvVectorStoreName?.focus();
        return false;
      }
      if (!(multiFormatCsvTargetDatabase instanceof HTMLInputElement) || !multiFormatCsvTargetDatabase.value.trim()) {
        renderMessage("Enter the Target Database.");
        multiFormatCsvTargetDatabase?.focus();
        return false;
      }
      if (resultNode instanceof HTMLElement && resultNode.dataset.clientValidationMessage === "1") {
        resultNode.innerHTML = "";
        delete resultNode.dataset.clientValidationMessage;
      }
      return true;
    };

    if (multiFormatCsvButton instanceof HTMLButtonElement) {
      multiFormatCsvButton.addEventListener(
        "click",
        (event) => {
          if (validateMultiFormatCsvGeneration()) {
            return;
          }
          event.preventDefault();
          event.stopImmediatePropagation();
        },
        true
      );
    }

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
    const fields = scope.querySelectorAll("#section-create input:not([type='file']):not([type='hidden']), #section-create textarea");
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
          const submitFields = createForm.querySelectorAll("input:not([type='file']):not([type='hidden']), textarea");
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
