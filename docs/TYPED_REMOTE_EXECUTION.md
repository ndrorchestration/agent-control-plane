# Typed Read-Only Remote Execution Contract

Status: candidate engineering contract for ACP review.

The v2 remote-execution path replaces signed shell command text with typed operation IDs and validated structured parameters.

## Core invariant

A signed request expresses **intent**, not shell syntax.

The executor derives the operating-system argv from an immutable ACP operation registry and executes it with `shell=False`.

```
signed operation intent
  -> schema validation
  -> device/freshness verification
  -> allowed-root resolution
  -> durable replay admission
  -> fixed argv rendering
  -> bounded shell=False execution
  -> typed result evidence
```

## Request schema

Envelope: `ndr.remote-execution-request.v2`

Typed request contract: `agent-control-plane.remote-execution.v1`

A request binds request ID, expected device identity and attestation level, `READ_ONLY_DISCOVERY`, expected `READ_ONLY` side-effect class, working directory, operation ID, validated parameters, operation SHA-256, nonce/freshness, and HMAC-SHA256 signature.

No shell command text or argv is included in the signed request envelope.
## Admitted operations

The operation registry is immutable at runtime. Current operations are deliberately narrow:

| Operation ID | Effective argv tail after `git -c core.fsmonitor=false` | Parameters |
| --- | --- | --- |
| `git.status.short` | `status --short --ignore-submodules=all` | none |
| `git.status.porcelain_v1` | `status --porcelain=v1 --ignore-submodules=all` | none |
| `git.rev_parse.head` | `rev-parse HEAD` | none |
| `git.branch.current` | `branch --show-current` | none |
| `git.remote.origin` | `remote get-url origin` | none |
| `git.diff.name_only` | `diff --no-ext-diff --ignore-submodules=all --name-only` | none |
| `git.diff.cached.check` | `diff --no-ext-diff --ignore-submodules=all --cached --check` | none |
| `git.show.file` | `show REVISION:PATH` | `revision`, `path` |

`git.show.file` is intentionally treated as content disclosure, not merely repository metadata. Its parameters reject option-like values, absolute paths, backslashes, colon injection, control characters, empty/dot/traversal segments, and overlong values.

Adding an operation expands capability and therefore requires explicit registry code plus tests. Callers cannot create a new capability by supplying arbitrary argv or shell text.

## Executor policy

Execution is constrained independently of the signed request:

- working directory must resolve inside at least one executor-configured allowed root;
- symlink/junction resolution occurs before root comparison;
- replay consumption happens only after deterministic signature, schema, operation, freshness, device, and root checks;
- execution uses `subprocess.run(..., shell=False)`;
- maximum runtime is 30 seconds;
- stdout and stderr are each retained up to 1 MiB as text;
- SHA-256 is computed over each complete stream even when retained text is truncated;
- timeout is represented as exit code 124 plus `timed_out=true`.

The signed request cannot widen allowed roots or execution bounds.
## Typed result evidence

Result schema: `ndr.typed-operation-result.v1`

The result records request ID, operation identity/parameters/digest, exact request-envelope SHA-256, derived argv, `shell=false`, resolved working directory, exit code/timing, timeout state, complete stdout/stderr hashes, byte counts/truncation flags, and bounded retained output.

ACP validates operation digest, argv, shell mode, result/request identity and working directory before accepting the typed result as matching the request.

## Replay and freshness

Freshness remains bounded by the existing ACP maximum request TTL of 300 seconds.

Durable replay protection persists request ID + nonce pairs in SQLite. Invalid requests do not consume replay state; replay is consumed as the final admission step immediately before execution.

Trusted external time is **not established**. Local freshness checks improve replay resistance but do not constitute trusted-clock attestation.

## Device identity

Current local demonstrations use a privacy-preserving software-derived fingerprint with the explicit attestation level `SOFTWARE_DERIVED_NOT_HARDWARE_ATTESTED`.

Hardware/TPM-rooted identity remains **NOT ESTABLISHED**.
## Legacy migration

The v1 command-text request format is compatibility-only.

- historical v1 receipt/request verification remains supported;
- new legacy shell-text request signing is disabled by default;
- callers must use the typed v2 issuer for new signed execution requests;
- an explicit internal `allow_legacy=True` override exists only to preserve historical verification tests/evidence.

The active CLI issuer emits only v2 typed envelopes.

## Threat-model improvements over v1

v2 removes several classes of ambiguity:

1. **Shell injection:** signed envelopes contain no shell program text.
2. **Command relabeling:** a caller cannot declare an arbitrary destructive command as `READ_ONLY`.
3. **Argument injection:** operation-specific parameter validation controls argv construction.
4. **Working-directory scope drift:** executor-configured roots are authoritative.
5. **Replay-state griefing:** out-of-scope requests fail before replay consumption.
6. **Output/runtime denial of service:** execution time and retained output are bounded.
7. **Mutable registry/request state:** operation specs and validated request parameters are immutable.
8. **Request/result detachment:** typed results bind the exact request-envelope SHA-256.

## Deliberately not established

This contract does not establish remote mutation authority, arbitrary command execution, authenticated transport identity, TPM/hardware-rooted device attestation, trusted external time, externally trusted key custody, production security, DGAF High-Assurance authorization, independent validation, or scientific efficacy/N increment.

Those boundaries remain separate governance transitions.

### Request-byte and evidence-path binding

The verified executor reads the request envelope bytes once, computes the envelope SHA-256 from those exact bytes, parses and validates that in-memory payload, and carries the same digest into the typed result. It does not re-read the request file after execution.

Result placement is executor-owned rather than request/caller-owned. The executor receives a configured evidence root and derives the result filename as `<request_id>.typed-result.json`. A signed request cannot select an arbitrary output path or redirect result evidence into the target working tree.

The generic argv execution helper is private to the typed module. Public execution accepts an admitted operation ID plus validated parameters and derives argv internally.

### Result-evidence validation

`TypedRemoteExecutionResult` validates the evidence packet itself, not only operation identity. For untruncated stdout/stderr it recomputes UTF-8 byte counts and SHA-256 exactly. For truncated streams it requires a full byte count larger than the retained prefix and enforces the retention bound; the full-stream digest remains executor-produced because the omitted suffix is intentionally unavailable to the verifier. The result also validates start/finish ordering, boolean timeout state, timeout exit-code semantics, derived argv, `shell=false`, and the exact expected request-envelope SHA-256 when supplied by the verifier.

This means a result whose retained output, byte counts, timing, timeout state, argv, operation digest, or request-envelope binding drifts fails closed instead of being accepted as structurally plausible evidence.

### Request identifier safety

Typed request IDs are constrained to a bounded filename-safe token alphabet (`A-Z a-z 0-9 . _ -`, maximum 128 characters) and reject `.` / `..` plus any path separator or drive/colon syntax. Typed results enforce the same rule. This keeps executor-derived evidence filenames confined to the configured evidence root rather than trusting a signed request ID as a path fragment.


## Repository metadata boundary hardening — 2026-09-26

Adversarial review found that cwd containment and shell-free argv were not sufficient by themselves: a repository-local `.git/config` could use `[include]` / `[includeIf]` to make a nominally read-only Git operation consume configuration from outside the executor's allowed root. A real `git.remote.origin` probe reproduced that scope escape before this fix.

Typed execution now performs a filesystem-level repository admission check before replay consumption:

- `.git` directories and `gitdir:` pointers must resolve inside executor-configured allowed roots;
- linked-worktree `commondir` targets must remain inside allowed roots;
- repository config and `config.worktree` files must themselves resolve inside allowed roots;
- `include`, `includeIf`, `filter`, and `diff` config sections are rejected;
- path/helper-capable core keys `core.worktree`, `core.attributesFile`, `core.excludesFile`, `core.hooksPath`, and `core.fsmonitor` are rejected;
- Git object `alternates` / `http-alternates` are rejected;
- inherited `GIT_*` environment variables are scrubbed before execution;
- the executor pins `GIT_WORK_TREE`, disables system/global attributes/config, disables prompts, disables optional locks, and sets `GIT_NO_LAZY_FETCH=1`.

The exact real include-path probe that previously returned a sentinel from an outside config is now refused before execution. Removing the outside include allows the same signed request to execute, confirming the failed admission did not consume replay state.

## Evidence-path collision hardening — 2026-09-26

Typed result filenames are derived only from validated path-safe request IDs, but pre-existing result paths are also treated as an admission conflict. The executor reserves the result path with exclusive creation before replay consumption. If the path already exists, execution is refused without overwriting the file or consuming the request.

For already-consumed requests, a non-mutating durable replay lookup runs first so the refusal remains explicitly classified as replay rather than being masked by the existing result file. Once the exclusive result reservation succeeds, replay is consumed immediately before execution and the validated result is written and fsynced through the reserved descriptor.
