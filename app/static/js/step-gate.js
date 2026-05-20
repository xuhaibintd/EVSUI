(function (global) {
  "use strict";

  function createStepGate(options = {}) {
    const connectSectionId = options.connectSectionId || "section-connect";
    const connectContentId = options.connectContentId || "section-connect-content";
    const lockedSections =
      options.lockedSections || ["section-create", "section-chat", "section-eval", "section-admin"];
    const menuHintId = options.menuHintId || "menu-hint";
    const wizardNoteSelector = options.wizardNoteSelector || "#section-connect .wizard-note";
    const noteConnectedText = options.noteConnectedText || "Step 1 completed. Continue to Step 2.";
    const noteDisconnectedText = options.noteDisconnectedText || "Complete Step 1 to continue.";

    function menuLayout() {
      return document.querySelector(".menu-layout");
    }

    function resolveConnectedState(connectTarget = null) {
      const scope =
        connectTarget instanceof Element
          ? connectTarget
          : document.getElementById(connectContentId) || document;

      const marker = scope.querySelector("[data-step1-connected]");
      let connected = false;

      if (marker) {
        connected = marker.dataset.step1Connected === "true";
      }

      const firstStatus = scope.querySelector(".connect-status-slot .status");
      if (firstStatus && /^Connected at/i.test(firstStatus.textContent.trim())) {
        connected = true;
      }

      if (!marker && !firstStatus) {
        const layout = menuLayout();
        connected = Boolean(layout) && layout.dataset.connected === "true";
      }

      const layout = menuLayout();
      if (layout) {
        layout.dataset.connected = connected ? "true" : "false";
      }

      return connected;
    }

    function isConnected() {
      return resolveConnectedState();
    }

    function isLockedTarget(sectionId) {
      return lockedSections.includes(sectionId) && !isConnected();
    }

    function setLockState(locked) {
      const menuHint = document.getElementById(menuHintId);
      if (menuHint) {
        menuHint.textContent = "";
      }

      document.querySelectorAll(".menu-item").forEach((item) => {
        const isLockedMenu = lockedSections.includes(item.dataset.section || "");
        item.classList.toggle("locked", locked && isLockedMenu);
        item.classList.toggle("disabled", locked && isLockedMenu);
        if (isLockedMenu) {
          item.setAttribute("aria-disabled", locked ? "true" : "false");
          if ("disabled" in item) {
            item.disabled = locked;
          }
        }
      });

      document.querySelectorAll("[data-requires-connected='true']").forEach((button) => {
        button.disabled = locked;
      });

      lockedSections.forEach((sectionId) => {
        const section = document.getElementById(sectionId);
        if (!section) {
          return;
        }

        section.classList.toggle("locked", locked);


        section
          .querySelectorAll(".panel-content .disabled-block")
          .forEach((block) => block.classList.toggle("disabled-block", locked));

        section
          .querySelectorAll(".panel-content input, .panel-content textarea, .panel-content select, .panel-content button")
          .forEach((control) => {
            if (
              control instanceof HTMLInputElement ||
              control instanceof HTMLTextAreaElement ||
              control instanceof HTMLSelectElement ||
              control instanceof HTMLButtonElement
            ) {
              control.disabled = locked;
            }
          });
      });
    }

    function activateSection(sectionId, force = false) {
      const currentlyLocked = !resolveConnectedState();
      setLockState(currentlyLocked);

      if (!sectionId) {
        return false;
      }
      if (!force && isLockedTarget(sectionId)) {
        return false;
      }

      document.querySelectorAll(".menu-item").forEach((button) => {
        button.classList.toggle("active", button.dataset.section === sectionId);
      });

      document.querySelectorAll(".menu-section").forEach((section) => {
        section.classList.toggle("active", section.id === sectionId);
      });

      return true;
    }

    function syncStepConnectionState(connectTarget) {
      if (!(connectTarget instanceof Element)) {
        return;
      }
      const connected = resolveConnectedState(connectTarget);

      setLockState(!connected);

      const step1Note = document.querySelector(wizardNoteSelector);
      if (step1Note) {
        step1Note.textContent = connected ? noteConnectedText : noteDisconnectedText;
        step1Note.classList.toggle("muted", connected);
      }

      if (!connected) {
        const activeSection = document.querySelector(".menu-section.active");
        if (activeSection && lockedSections.includes(activeSection.id)) {
          activateSection(connectSectionId, true);
        }
      }
    }

    function initialize() {
      const locked = !resolveConnectedState();
      setLockState(locked);

      const activeButton = document.querySelector(".menu-item.active");
      const initialSection = (activeButton && activeButton.dataset.section) || connectSectionId;
      activateSection(initialSection, true);

      const connectContent = document.getElementById(connectContentId);
      if (connectContent) {
        syncStepConnectionState(connectContent);
      }
    }

    return {
      initialize,
      isLockedTarget,
      activateSection,
      setLockState,
      syncStepConnectionState,
    };
  }

  global.createStepGate = createStepGate;
})(window);
