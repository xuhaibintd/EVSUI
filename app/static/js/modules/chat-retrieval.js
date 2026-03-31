(function (global) {
  "use strict";

  const app = (global.EVSUIApp = global.EVSUIApp || {});

  function escapeHtml(value) {
    if (typeof app.escapeHtml === "function") {
      return app.escapeHtml(value);
    }
    return String(value)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/\"/g, "&quot;")
      .replace(/'/g, "&#39;");
  }

  function currentMode(form, radios) {
    const active = radios.find((radio) => radio.checked);
    return active ? active.value : "native";
  }

  function renderMessage(role, content, time) {
    return [
      `<div class="msg ${escapeHtml(role)}">`,
      `<p class="chat-content">${escapeHtml(content)}</p>`,
      `<small>${escapeHtml(time)}</small>`,
      "</div>",
    ].join("");
  }

  function appendMessage(messagesRoot, role, content, time) {
    if (!messagesRoot) {
      return;
    }
    messagesRoot.insertAdjacentHTML("beforeend", renderMessage(role, content, time));
    messagesRoot.scrollTop = messagesRoot.scrollHeight;
  }

  function nowHm() {
    const now = new Date();
    const hh = String(now.getHours()).padStart(2, "0");
    const mm = String(now.getMinutes()).padStart(2, "0");
    return `${hh}:${mm}`;
  }

  function setManualProgress(form, button, loading) {
    if (form) {
      form.classList.toggle("htmx-request", loading);
    }
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

  function buildAssistantMessage(payload) {
    const vectorStoreName = String((payload && payload.vector_store_name) || "").trim();
    const evidence = payload && payload.evidence ? payload.evidence : {};
    const evidenceText = String((evidence && evidence.evidence_text) || "").trim();
    if (evidenceText) {
      return `BookRAG evidence for '${vectorStoreName}':\n\n${evidenceText}`;
    }
    if (vectorStoreName) {
      return `No BookRAG evidence found for '${vectorStoreName}'.`;
    }
    return "No BookRAG evidence found.";
  }

  async function parseError(response) {
    try {
      const payload = await response.json();
      if (payload && typeof payload.detail === "string" && payload.detail.trim()) {
        return payload.detail.trim();
      }
      return JSON.stringify(payload);
    } catch (_error) {
      try {
        const text = await response.text();
        return String(text || "").trim() || `${response.status} ${response.statusText}`;
      } catch (_textError) {
        return `${response.status} ${response.statusText}`;
      }
    }
  }

  async function submitBookragApi(form, radios) {
    const messageField = form.querySelector("#chat-message");
    const selectedVsField = form.querySelector("[data-chat-selected-vs]");
    const apiUrlField = form.querySelector("#bookrag-api-url");
    const messagesRoot = document.querySelector("#chat-messages");
    const submitButton = form.querySelector("button[type='submit'][data-progress-button]");

    if (!(messageField instanceof HTMLTextAreaElement)) {
      return;
    }

    const question = messageField.value.trim();
    if (!question) {
      messageField.reportValidity();
      return;
    }

    const vectorStoreName = selectedVsField instanceof HTMLSelectElement ? selectedVsField.value.trim() : "";
    if (!vectorStoreName) {
      appendMessage(messagesRoot, "assistant", "BookRAG API requires a selected vector store.", nowHm());
      return;
    }

    const apiUrl = apiUrlField instanceof HTMLInputElement ? apiUrlField.value.trim() : "";
    if (!apiUrl) {
      appendMessage(messagesRoot, "assistant", "BookRAG API URL is unavailable.", nowHm());
      return;
    }

    const userTime = nowHm();
    appendMessage(messagesRoot, "user", question, userTime);
    setManualProgress(form, submitButton, true);

    try {
      const response = await fetch(apiUrl, {
        method: "POST",
        credentials: "same-origin",
        headers: {
          "Content-Type": "application/json",
          Accept: "application/json",
        },
        body: JSON.stringify({
          question,
          vector_store_name: vectorStoreName,
        }),
      });

      if (!response.ok) {
        throw new Error(await parseError(response));
      }

      const payload = await response.json();
      const assistantMessage = String((payload && payload.assistant_message) || "").trim() || buildAssistantMessage(payload);
      const assistantTime = String((payload && payload.assistant_time) || "").trim() || nowHm();
      appendMessage(messagesRoot, "assistant", assistantMessage, assistantTime);
      messageField.value = "";
      messageField.focus();
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error);
      appendMessage(messagesRoot, "assistant", `BookRAG API failed: ${message}`, nowHm());
    } finally {
      setManualProgress(form, submitButton, false);
    }
  }

  function initializeForm(form) {
    if (!form || form.dataset.retrievalModeBound === "1") {
      return;
    }
    form.dataset.retrievalModeBound = "1";

    const radios = Array.from(form.querySelectorAll("[data-retrieval-mode-toggle]"));
    const nativeOnly = Array.from(form.querySelectorAll("[data-native-only]"));
    const cards = Array.from(form.querySelectorAll("[data-retrieval-option]"));

    nativeOnly.forEach((element) => {
      if (!element.hasAttribute("data-native-base-disabled")) {
        element.setAttribute("data-native-base-disabled", element.disabled ? "1" : "0");
      }
    });

    function applyState() {
      const mode = currentMode(form, radios);
      const nativeSelected = mode === "native";

      cards.forEach((card) => {
        const selected = card.getAttribute("data-retrieval-option") === mode;
        card.classList.toggle("is-selected", selected);
        card.classList.toggle("is-unselected", !selected);
      });

      nativeOnly.forEach((element) => {
        const baseDisabled = element.getAttribute("data-native-base-disabled") === "1";
        element.disabled = baseDisabled || !nativeSelected;
      });
    }

    radios.forEach((radio) => radio.addEventListener("change", applyState));

    form.addEventListener(
      "submit",
      (event) => {
        if (currentMode(form, radios) !== "api") {
          return;
        }
        event.preventDefault();
        event.stopPropagation();
        if (typeof event.stopImmediatePropagation === "function") {
          event.stopImmediatePropagation();
        }
        submitBookragApi(form, radios);
      },
      true
    );

    applyState();
  }

  app.registerBinder(function bindChatRetrieval(scope) {
    const root = scope || document;
    root.querySelectorAll("[data-retrieval-mode-form]").forEach(initializeForm);
  });
})(window);
