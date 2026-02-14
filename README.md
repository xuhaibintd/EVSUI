# EVSUI

FastAPI + Jinja2 + HTMX UI scaffold for teradatagenai visualization.

## Included

- Step 1 notebook-style connection/auth panel:
  - `create_context(host, username, password)`
  - `set_auth_token(base_url, pat_token, pem_file)`
  - optional `VSManager.health()` / `VSManager.list()` execution
- Step 2 multi-file upload + full `VectorStore.create` parameter form with presets:
  - `VECTORDISTANCE` sample
  - `HNSW` sample
  - custom
- Step 3 EVS validation chat window aligned to notebook operations (`ask`, `similarity_search`, `status`, `destroy`, `disconnect`).

## Run

```bash
cd EVSUI
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8010
```

Open: `http://127.0.0.1:8010`

## Notes

- Step 1 now performs real DB connection + VS auth (not only preview).
- If `PEM` is a file name from `vars-vs_demo.json`, the app also tries `VS_Basics_Full_Kit/<key_file>`.
- Uploaded files are saved under `EVSUI/uploads/`.
