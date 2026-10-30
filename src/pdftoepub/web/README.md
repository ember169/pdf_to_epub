# pdftoepub web

FastAPI app `pdftoepub.web.app:app` + static single-page front (`static/`, vanilla JS, FR/EN, dark mode).
Run: `pdftoepub serve --host 0.0.0.0 --port 8000` (or `uvicorn pdftoepub.web.app:app`).

## Environment

| Var | Default | Meaning |
|---|---|---|
| `DATA_DIR` | `./data` | Job state/files (`DATA_DIR/jobs/<id>/`); survives restarts |
| `MAX_UPLOAD_MB` | `100` | Upload size limit (413 above) |
| `JOB_TTL_HOURS` | `24` | Janitor deletes finished jobs older than this |
| `MAX_CONCURRENT_JOBS` | `2` | Conversion worker threads |
| `JOB_TIMEOUT_S` | `600` | Wall-clock limit per conversion (0 = none); each job runs in an isolated child process that is killed on breach or `DELETE` |
| `JOB_MAX_MEM_MB` | `2048` | Memory limit (resident set) per conversion (0 = none) |
| `MAX_PAGES` | `2000` | Reject PDFs with more pages (0 = unlimited) |
| `MAX_QUEUED_JOBS` | `20` | Queued+running jobs accepted before `POST /api/jobs` answers 503 (`Retry-After`) |
| `ALLOWED_HOSTS` | unset | Comma-separated extra hostnames (reverse proxy / LAN name). Default accepts only `localhost`, `127.0.0.1`, `[::1]` as `Host`; state-changing requests must be same-origin. `*` disables the check. When `AUTH_TOKEN` is set the host check applies only if `ALLOWED_HOSTS` is set |
| `AUTH_TOKEN` | unset | If set, `/api/jobs*` require `Authorization: Bearer <token>` (static page, `/healthz`, `/api/config` stay open; the front asks for the token) |

## Endpoints

- `POST /api/jobs` — multipart `file` (+ optional `options` JSON: `title, author, language, ocr, ocr_langs, drop_headers_footers, detect_columns, image_mode`) → `201 {id}`; 415 non-PDF, 413 too large, 422 bad options
- `GET /api/jobs/{id}` — `{status: queued|running|done|error, stage, page, total_pages, warnings, error, title, filename}`
- `GET /api/jobs/{id}/events` — SSE (`event: progress`, JSON payload as above; ends on done/error)
- `GET /api/jobs/{id}/download` — `application/epub+zip` (409 until done)
- `DELETE /api/jobs/{id}` — 204
- `GET /healthz`, `GET /api/config`

Uploaded PDFs are removed as soon as conversion ends; jobs running at a restart are marked `error`, queued ones are re-run.
Tests: `pytest src/pdftoepub/web/tests`.

Uploads are size-limited while streaming (Content-Length and byte count), at most one file + 4 form fields per request; 507 when free disk is low. Stale `DATA_DIR/tmp` uploads are swept by the janitor.
