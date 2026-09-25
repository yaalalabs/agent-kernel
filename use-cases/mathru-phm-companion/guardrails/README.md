# Guardrail configuration

The normal configuration enables input and output guardrails. These reduce some unwanted
content; they do not establish clinical safety or guarantee that a symptom report is processed.

## Configured checks

| Path | File | Checks |
|---|---|---|
| Input pre-flight | `input.json` | Moderation with the categories listed below |
| Input | `input.json` | Jailbreak |
| Output | `output.json` | NSFW Text |

The custom input class is selected through `guardrail.input.type` in `../config.yaml`.
The output path uses Agent Kernel's built-in OpenAI output guardrail. The separate
`BlockUnsafeLanguageHook` checks final agent replies; direct PHM alerts bypass that hook.

## No PII detection

`Contains PII` is disabled on both paths because registration and routing use phone numbers.
Phone-pattern redaction runs at log-record creation through `../redaction.py`, including
records sent to non-propagating Agent Kernel loggers and replacement handlers. It does
not rewrite database records, delivery destinations, tool results, or symptom excerpts.
PHM tools separately omit stored routing fields and raw delivery errors from their results.

## Narrow moderation categories

The input moderation categories are:

- `sexual/minors`
- `hate/threatening`
- `harassment/threatening`
- `illicit/violent`

`self-harm` and `violence/graphic` are excluded to reduce interference with descriptions of
bleeding, pain, or other symptoms. The remaining checks can still produce false positives;
a genuine tripwire blocks the turn before screening. This configuration has not been
clinically validated.

## Failure behavior

`ResilientInputGuardrail` blocks `GuardrailTripwireTriggered`. Other exceptions raised during
validation are logged and the requests pass through; this includes more than network errors.
If the guardrail client did not initialize, requests also pass through. Inspect startup logs
as well as per-turn logs when checking whether validation is active.

The built-in output guardrail replaces a reply on a tripwire and passes the original reply
through on validation errors. It can therefore replace a symptom-related response. Passing
through input validation errors does not recover an unavailable agent model or database.

## Model configuration and cost

`MATHRU_MODEL` controls the five agents only. The independent guardrail model settings are:

- `guardrail.input.model` in `../config.yaml`, or `AK_GUARDRAIL__INPUT__MODEL`.
- `guardrail.output.model` in `../config.yaml`, or `AK_GUARDRAIL__OUTPUT__MODEL`.
- The Jailbreak check's literal `config.model` in `input.json`.
- The NSFW Text check's literal `config.model` in `output.json`.

JSON values do not interpolate environment variables. Moderation uses a separate moderation
service. Both guardrail wrappers invoke a chat completion; configured checks and retries
can add further requests. Measure the actual workload rather than assuming a fixed call count.
See [model and rate limits](../README.md#model-and-rate-limits) for setup.

For a local debugging run, the two `AK_GUARDRAIL__*__ENABLED` settings can disable these
checks. Restore both to `true` for the normal configuration. Disabled-guardrail runs do not
validate guardrail behavior.
