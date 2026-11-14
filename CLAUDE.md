# CLAUDE.md — guidance for Claude Code in this repo

- Stack: Python 3.11+, FastAPI, FFmpeg (libass), vanilla JS UI (iPad Safari first).
- **Never spend Higgsfield credits without explicit user approval.** Default is mock mode.
  Live calls need `HIGGSFIELD_MODE=live` AND `ALLOW_PAID_API_CALLS=true`.
- `app/services/higgsfield/live.py` follows the official docs (https://docs.higgsfield.ai).
  Change endpoints or request fields only after re-checking those docs; don't guess.
- Paid generation starts only via `POST /api/jobs/{id}/approve` (per-job user approval).
- Never commit `.env`, API keys, reference photos (`assets/characters/seoa/references/`) or `data/`.
- Output format is always vertical 9:16, 1080x1920, H.264/AAC.
- Run tests with `python -m pytest -q` before committing.
- UI text and README are in Korean; code and comments in English.
