(function () {
  "use strict";

  // A delegated external listener also runs on System Configuration, which
  // intentionally does not load the vector-store application modules.
  document.addEventListener("submit", (event) => {
    const source = event.submitter;
    const message = source?.dataset.confirmMessage || event.target?.dataset.confirmMessage;
    if (message && !window.confirm(message)) {
      event.preventDefault();
      event.stopImmediatePropagation();
    }
  }, true);
})();
