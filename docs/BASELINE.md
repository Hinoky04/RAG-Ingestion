# Final internship baseline

This repository preserves the author's confirmed final research-internship implementation. The delivered Python package is `sourcecode/`.

## Provenance

Original delivery archive SHA-256:

```text
6308b3e8b29d492f8d629c756ddd88924e28b03348dbb2e42d94f6db465b5504
```

All 45 delivered Python/UI/schema files in `sourcecode/`, `streamlit_app.py` and `db/schema.sql` retain their original bytes. [The manifest](submission_baseline.json) records their SHA-256 values, and a test verifies them. `.gitattributes` prevents automatic line-ending conversion for those files so this check works across fresh checkouts. The final report PDF is also unchanged from the delivery.

## Maintained additions

- Packaging and dependency declarations for the delivered package.
- Unit tests aligned with the delivered behavior and opt-in real-service integration checks.
- CI, setup instructions, architecture documentation and a PowerShell startup helper.
- PostHog 5.4.0 compatibility pin for the delivered Chroma 0.5.23 API.

Raw documents, runtime data, retained archives, credentials, model caches, editable Word drafts and generated test outputs are not published. Source tests construct their own temporary fixtures. FYP research extensions are outside this internship baseline.
