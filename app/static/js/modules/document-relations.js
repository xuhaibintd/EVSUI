(function () {
  "use strict";

  const relationTypes = [
    "summary_of",
    "next_issue_of",
    "updates",
    "supplement_to",
    "follow_up_to",
    "references",
    "related_to",
  ];

  function escapeHtml(value) {
    return String(value == null ? "" : value)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;")
      .replace(/'/g, "&#39;");
  }

  function readJson(editor, selector, fallback) {
    const node = editor.querySelector(selector);
    if (!node) return fallback;
    try {
      return JSON.parse(node.textContent || "");
    } catch (_error) {
      return fallback;
    }
  }

  function optionMarkup(values, selected, valueKey, labelKey) {
    return values
      .map((item) => {
        const value = String(item[valueKey] || "");
        const label = String(item[labelKey] || item.name || value);
        return `<option value="${escapeHtml(value)}"${value === String(selected || "") ? " selected" : ""}>${escapeHtml(label)}</option>`;
      })
      .join("");
  }

  function relationRowMarkup(catalog, relation) {
    const sourceType = String(relation.source_type || "human");
    const confirmed = relation.confirmed === true;
    return `
      <div class="document-relation-row" data-document-relation-row data-source-type="${escapeHtml(sourceType)}" data-confidence="${escapeHtml(relation.confidence == null ? "" : relation.confidence)}">
        <select data-relation-from aria-label="From document">${optionMarkup(catalog, relation.from_doc_id, "doc_id", "filename")}</select>
        <select data-relation-type aria-label="Relationship">${optionMarkup(relationTypes.map((value) => ({ value, label: value })), relation.relation_type || "related_to", "value", "label")}</select>
        <select data-relation-to aria-label="To document">${optionMarkup(catalog, relation.to_doc_id, "doc_id", "filename")}</select>
        <input type="text" data-relation-description value="${escapeHtml(relation.relation_description || "")}" placeholder="Relationship description" />
        <label class="document-relation-confirm"><input type="checkbox" data-relation-confirm${confirmed ? " checked" : ""} /> Confirm</label>
        <button type="button" class="ghost" data-remove-document-relation>Remove</button>
      </div>`;
  }

  function bindEditor(editor) {
    if (!(editor instanceof HTMLElement) || editor.dataset.bound === "1") return;
    editor.dataset.bound = "1";
    const catalog = readJson(editor, "[data-document-catalog-json]", [])
      .map((item) => ({
        doc_id: String(item.doc_id || ""),
        filename: String(item.filename || item.name || ""),
      }))
      .filter((item) => item.doc_id && item.filename);
    const initial = readJson(editor, "[data-document-relation-initial-json]", []);
    const list = editor.querySelector("[data-document-relation-list]");
    const hidden = editor.querySelector("[data-document-relations-json]");
    if (!(list instanceof HTMLElement) || !(hidden instanceof HTMLInputElement)) return;

    function serialize() {
      const rows = Array.from(list.querySelectorAll("[data-document-relation-row]")).map((row) => ({
        from_doc_id: row.querySelector("[data-relation-from]")?.value || "",
        relation_type: row.querySelector("[data-relation-type]")?.value || "",
        to_doc_id: row.querySelector("[data-relation-to]")?.value || "",
        relation_description: row.querySelector("[data-relation-description]")?.value || "",
        source_type: row.dataset.sourceType || "human",
        confidence: row.dataset.confidence || null,
        is_active: 1,
        confirmed: Boolean(row.querySelector("[data-relation-confirm]")?.checked),
      }));
      hidden.value = JSON.stringify(rows);
    }

    function wireRows() {
      list.querySelectorAll("[data-remove-document-relation]").forEach((button) => {
        if (button.dataset.bound === "1") return;
        button.dataset.bound = "1";
        button.addEventListener("click", () => {
          button.closest("[data-document-relation-row]")?.remove();
          serialize();
        });
      });
    }

    initial.forEach((relation) => {
      list.insertAdjacentHTML("beforeend", relationRowMarkup(catalog, relation));
    });
    wireRows();
    serialize();
    list.addEventListener("change", serialize);
    list.addEventListener("input", serialize);

    editor.querySelector("[data-add-document-relation]")?.addEventListener("click", () => {
      if (catalog.length < 2) return;
      list.insertAdjacentHTML(
        "beforeend",
        relationRowMarkup(catalog, {
          from_doc_id: catalog[0].doc_id,
          relation_type: "related_to",
          to_doc_id: catalog[1].doc_id,
          source_type: "human",
          confirmed: true,
        }),
      );
      wireRows();
      serialize();
    });
  }

  function bindAll() {
    document.querySelectorAll("[data-document-relation-editor]").forEach(bindEditor);
  }

  document.addEventListener("DOMContentLoaded", bindAll);
  document.addEventListener("htmx:afterSwap", bindAll);
  document.addEventListener("evsui:uploaded-files-updated", bindAll, true);
})();
