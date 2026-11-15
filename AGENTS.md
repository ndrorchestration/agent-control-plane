# ACP Codex Repository Instructions
Read the current ACP architectural contracts, policy interfaces, existing tests, and repository instructions before implementing.
- Enforce explicit PDP/PEP separation; tool capability access is not authorization.
- Preserve default-deny/fail-closed decisions, least privilege, credential isolation, provenance, and fresh adjudication for follow-on authority.
- Examine process identity/isolation, filesystem object identity, symlinks, path traversal, TOCTOU, and mutation lineage whenever applicable.
- Distinguish dry-run, disposable-scope validation, hosted testing, and real-world authorized execution. Do not extrapolate scope.
- Prefer narrow, reversible patches and contract tests; inspect integration relationships with Tektite, DGAF, and public status projections.
- Do not silently expand public visibility, agent permissions, external effects, or authority transfer.
- Record exact evidence and any unresolved cross-repository dependencies.
