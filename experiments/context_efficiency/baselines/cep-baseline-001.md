# CEP Baseline 001

This baseline is a directly observed **partial control record** for the task:

> Verify exact-head CI state for commit `50da6cef8307f82003ebbe5f282b67de12a14a00`
> using one commit workflow-runs lookup and report the observed run
> status/conclusion.

## Frozen identities

- context-state SHA-256:
  `24089d77a315bb57aca948cd4345364dc02bc911b2dfa4bceaf5dc836c1e525b`
- baseline-observation SHA-256:
  `eebf862cd50072afa216f997ab327f70c563ed8cc7b4ea5615e14f962af6b83a`

## Direct observations

- tool invocations: 1
- retrieved items: 1
- outcome: completed
- acceptance: accepted

## Explicitly unavailable

The current connector workflow does not expose authoritative values for:

- model input tokens;
- model output tokens;
- tool-result tokenization;
- total tool definitions exposed to the model;
- tool-definition token cost;
- cacheable/novel prefix token counts;
- decision-relevant input-token count.

Those fields remain `null`.

## Eligibility

This record is suitable for validating the baseline-recording and frozen-control
identity path.

It is **not sufficient** for a tool-gating efficacy comparison whose primary
metric is `tool_definitions_exposed`, because that baseline field is not
observable in this workflow.

The next comparison therefore requires an instrumented harness with an explicit,
countable tool catalog.

No efficacy or token-savings claim follows from this record.
