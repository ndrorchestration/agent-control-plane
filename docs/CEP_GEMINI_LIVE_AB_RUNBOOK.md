# CEP Gemini Live A/B — Operator Runbook

Status: **EXPERIMENTAL / BOUNDED / NON-AUTHORIZING**

Controller: ACP issue #165  
Experiment protocol: ACP issue #161

This runbook operates the fail-closed Gemini transport runner only. It does **not**
authorize connector execution, production routing, scientific promotion, or
High-Assurance.

## Preconditions

Use an ACP checkout containing PR #169.

The runner is bound to:

- control catalog: 89-tool frozen GitHub connector snapshot;
- treatment catalog: one frozen `mcp__GitHub__fetch_commit_workflow_runs` descriptor;
- transport profile: `gemini-openai-compatible-v1`;
- provider endpoint: Gemini OpenAI-compatible chat-completions endpoint;
- model: `gemini-3.8-flash`;
- frozen downstream execution binding:
  `github-status-pr164-head-001`.

Do not substitute another catalog, prompt, task, model, endpoint, or downstream
execution binding and call it the same experiment.

## 1. Dry-run first

From the repository root:

```powershell
python scripts/run_cep_gemini_transport_ab.py
```

Expected disposition:

```text
BLOCKED_SEND_NOT_REQUESTED
```

Required properties:

- no network request;
- no credential read;
- control/treatment catalog identities are verified;
- exact request bodies are deterministically constructed;
- frozen downstream execution binding is verified.

If dry-run fails, stop. Do not supply a credential.

## 2. Supply the credential only to the invoking process

The runner reads exactly this environment variable:

```text
GEMINI_API_KEY
```

Do not commit, echo, paste into issue comments, write into JSON evidence, or
store the value in repository files.

Example PowerShell session:

```powershell
$env:GEMINI_API_KEY = "<credential>"
python scripts/run_cep_gemini_transport_ab.py --send
Remove-Item Env:GEMINI_API_KEY
```

Credential creation, provider enrollment, billing changes, and secret migration
from another project are outside this runbook and require explicit operator
action.

## 3. Interpret the transport result fail-closed

Possible dispositions:

- `BLOCKED_CREDENTIAL_NOT_CONFIGURED`
- `BLOCKED_MEASUREMENT_DEPENDENCY_MISSING`
- `BLOCKED_DYNAMIC_EXPOSURE_UNOBSERVED`
- `BLOCKED_SELECTED_TOOL_NOT_PRESERVED`
- `TRANSPORT_PAIR_READY_FOR_RESULT_ADJUDICATION`

Only the final state means both exact request catalogs were sent and both
provider responses contained an admissible tool call resolving to the frozen
workflow-status tool.

It is **not** an end-to-end PASS.

## 4. Required evidence from a transport-ready pair

Retain the emitted non-secret result with:

- exact request-manifest identities;
- exact request-body hashes and byte counts;
- provider request IDs;
- provider model IDs;
- response hashes;
- selected tool;
- latency;
- exact sent-tool token counts;
- control/treatment catalog identities;
- frozen downstream execution binding identity.

The runner never records the credential.

## 5. Downstream adjudication remains separate

After a transport-ready pair, execute the frozen workflow-status observation
under its separately governed connector path and bind:

- normalized result identity;
- evidence identity;
- acceptance outcome.

Then apply the existing paired dynamic-exposure evaluator.

Do **not** infer result equivalence from tool selection alone.

## Claim ceiling

Even a successful bounded pair does not establish:

- generalized model efficiency;
- universal latency or monetary savings;
- DGAF efficacy;
- scientific N increment;
- independent validation;
- production routing authority;
- High-Assurance.

Current fixed state:

```text
SCIENTIFIC_N_INCREMENT=0
INDEPENDENT_VALIDATION=NOT_ESTABLISHED
CANONICAL_DGAF_EFFICACY=NOT_ESTABLISHED
HIGH_ASSURANCE=NOT_AUTHORIZED
```
