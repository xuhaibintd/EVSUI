# Publication Checks

> **Language:** English | [日本語](publishing_ja.md)

Run the publication check before committing or pushing changes:

```powershell
uv run --locked --no-sync python scripts\check_publication.py
uv run --locked --no-sync python scripts\check_doc_parity.py
```

The check examines the current Git-tracked tree and rejects runtime data,
environment files, credentials and key formats, internal dated reports,
machine-specific user paths, and non-English primary documentation. When local
configuration is available, it also compares saved connection and credential
values against tracked files without printing those values. CI runs the same
check on every push and pull request.

Use fictional identifiers such as `example_database`, `EXAMPLE_STORE`, and
`example.invalid` in public examples. Keep run-specific reports, screenshots,
environment notes, and customer or deployment identifiers under the ignored
`local-notes/` directory. Translations are kept in explicitly suffixed files,
such as `_ja.md`; README and unsuffixed documents are maintained in English.
Every public English Markdown document must have a complete `_ja.md` counterpart
with the same heading/list/table structure and identical fenced code. After
translating an English change, update the Japanese file's `Source-SHA256` marker.
The documentation parity check rejects missing, structurally different, or stale
translations and broken/localized cross-document links.

The checker validates the current tree, not prior Git history. If a credential
was ever committed, rotate it immediately. Removing it from the latest revision
does not make the old value secret again. Rewriting published history is a
separate repository-administration operation and requires coordination with all
users of existing clones and forks.

Review licensing, trademark use, third-party notices, and organizational approval
separately. Automated checks cannot establish legal authorization to publish.
