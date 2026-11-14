# CLAUDE.md — guidance for Claude Code in this repo

- Stack: Python 3.11+, FastAPI, FFmpeg (libass), vanilla JS UI (iPad Safari first).
- **Never spend Higgsfield credits without explicit user approval.** Default is mock mode.
  Live calls need `HIGGSFIELD_MODE=live` AND `ALLOW_PAID_API_CALLS=true`.
- `app/services/higgsfield/live.py` is a skeleton. Implement it only from the official
  Higgsfield API docs; don't guess endpoints.
- Never commit `.env`, API keys, reference photos (`assets/characters/seoa/references/`) or `data/`.
- Output format is always vertical 9:16, 1080x1920, H.264/AAC.
- Run tests with `python -m pytest -q` before committing.
- UI text and README are in Korean; code and comments in English.
