# Second ScheduleProvider built-in: alternatives survey

The requirement (issue #629, point 3) fixes AWS EventBridge Scheduler as the first built-in
ScheduleProvider and asks for a suggestion for a second. This note surveys the candidates and
recommends a **local in-process provider** as the second built-in.

Verification status: the EventBridge facts are verified in `aws-eventbridge-scheduler.md`. The
claims about the non-AWS cloud services below are from general knowledge and were **not**
re-verified in this pass; they only motivate a prioritization, none of them is being designed
against. Re-verify before ever building one of them.

## Candidates

| Candidate | Kind | One-time + cron? | Fit for "submit to AK input queue" | Assessment |
|---|---|---|---|---|
| Local in-process | asyncio/threading timers inside the AK process | Yes (both, computed in-process) | Direct: calls the in-process transport (`in_memory`) or any configured transport | **Recommended.** Zero setup, mirrors the house pattern of a local default for every pluggable backend |
| Google Cloud Scheduler | GCP managed cron | Cron only; no native one-time schedules (not re-verified) | Targets HTTP/Pub/Sub, not SQS; AK has no pub/sub input transport yet | Natural third provider once a GCP queue transport exists; poor first companion |
| Azure alternatives (Logic Apps recurrence, Container Apps jobs) | Azure managed | Varies | No direct AK-queue target; HTTP-based | Same story as GCP: wait for an Azure transport |
| APScheduler | Python library dependency | Yes (`date` + `cron` triggers) | In-process, same as local | Works, but pulls a dependency for what reduces to "compute next fire time and sleep"; its persistence/jobstore features duplicate the ScheduleStore |
| Temporal / Celery beat | Self-hosted infra | Yes | Would need custom bridging | Heavy operational dependency; contradicts "triggering is outside AK's scope" by pulling the trigger engine into the deployment |

## Why the local in-process provider

- **House pattern**: every pluggable capability in Agent Kernel ships a zero-setup local default
  next to its cloud backends: `session.type: in_memory`, `execution.queues.type: in_memory`,
  `thread.type: in_memory`, multimodal `storage_type: in_memory`, sandbox `local_subprocess`.
  A scheduling capability whose only built-in provider requires an AWS account would be the one
  exception, and examples/tests/e2e could not exercise the scheduling flow at all.
- **Trigger delivery already composes**: in the single-process topology the local provider fires by
  sending the trigger message through the configured queue transport (the `in_memory` transport in
  dev), which is exactly the delivery contract EventBridge uses against SQS. One delivery contract,
  two providers.
- **Honest scope**: like the other local backends it is not durable: schedules die with the process
  (the ScheduleStore still has the task records; re-arming on restart can be a later iteration).
  This is the same durability trade the `in_memory` transport and session store already make, and it
  is documented, not hidden.
- **No new dependency**: cron next-fire computation needs a small cron library (e.g. `croniter`)
  for expression validation anyway; the timer itself is a `threading.Timer`/asyncio task. Whether
  to use `croniter` directly or adopt APScheduler internally is an implementation-spec decision,
  not a design decision.
