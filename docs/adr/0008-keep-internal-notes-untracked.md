# ADR 0008: Keep internal notes untracked

- Status: Accepted
- Context: The repo needs concise, public-facing documentation, while keeping larger design/research notes for local iteration.
- Decision: Move `docs/design.md` and `docs/research.md` into `docs/internal/` and add `docs/internal/` to `.gitignore`.
- Decision: Maintain the public, user-facing docs under `docs-site/docs/` (MkDocs).
- Consequence: Internal notes remain available for local development but are not pushed to GitHub.
- Consequence: The source of truth for public documentation becomes `docs-site/`, not `docs/`.

