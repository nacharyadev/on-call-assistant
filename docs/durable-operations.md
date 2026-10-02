# Durable Operations and Request Resumption

## Status

Proposed design for the On-Call Assistant (OCA).

## Problem statement

OCA handles requests that may require several tools and agents before the user's goal is achieved. Some operations, such as a Jira lookup, may return a final result during the current request. Other operations, such as Codebot analysis, a broad Splunk investigation, or full application reproduction, can take minutes or hours.

Treating every tool as a synchronous call forces OCA to poll continuously, ties up service resources, and makes recovery difficult. Treating every tool as asynchronous creates unnecessary job-management overhead and assumes that every provider returns a job identifier. In practice, each tool has its own execution behavior.

Long-running work also creates a planning problem. A completed external operation may confirm the current plan, make the next task possible, or provide evidence that requires a new plan. OCA must resume from that result without losing the original user objective, completed work, or outstanding tasks.

## Goal

Build a durable execution model in which OCA can:

- Define each tool as synchronous or asynchronous.
- Run independent tasks in parallel when their dependencies permit it.
- Return promptly after dispatching long-running work, including the external operation identifier and current status.
- Resume a request when the user asks for status or explicitly asks OCA to continue.
- Use newly completed results to continue, wait, finish, or revise the remaining plan.
- Preserve the original request goal and success criteria throughout every continuation.
- Recover request, task, and operation state after a service restart.
- Produce complete trajectories for debugging, evaluation, and RRSI improvement.

## Non-goals

- Building the Codebot, Splunk, Jira, or observability services themselves.
- Requiring every external system to implement asynchronous jobs.
- Automatically continuing a request whenever an external system completes. User-triggered continuation is the initial operating model.
- Storing large log sets, repository archives, or other bulky artifacts directly in graph state.

## Design principles

### Tool behavior is explicit

Every tool definition declares its execution mode. OCA does not infer the mode from response shape, latency, or the presence of an identifier.

- **Synchronous:** the call returns a terminal result. Jira history lookup and ticket creation may use this mode.
- **Asynchronous:** submission returns an operation identifier. Codebot and long-running investigations commonly use this mode.

Where a provider offers both behaviors, OCA exposes separate tool definitions, such as a quick synchronous Splunk search and an asynchronous Splunk investigation. This makes the planner's choice clear and keeps worker behavior deterministic.

### The user request is the durable unit of work

Each request retains an immutable goal envelope containing the original request, objective, success criteria, constraints, account scope, and relevant domains or repositories. A user may explicitly revise the goal, but planning and tool results cannot silently replace it.

### Tasks and external operations are distinct

A task represents work in the OCA plan. An external operation represents one submitted execution attempt at a provider. Keeping them separate allows a task to be retried, moved to another tool, or superseded while preserving its history.

### Planning is evidence-driven

Completed results become evidence for the continuation planner. The planner may preserve the remaining plan, add grounded follow-up work, supersede tasks made irrelevant by new evidence, or conclude that the goal has been met. Completed history remains immutable.

### Status is deterministic

Dispatch and progress messages are constructed from stored state rather than generated freely by a model. The user receives an exact operation identifier, provider, task, and status.

## Request lifecycle

### 1. Accept and plan

OCA applies safety checks, classifies the request, creates the goal envelope, retrieves relevant harness context, and produces a dependency-aware task plan.

### 2. Schedule ready tasks

The scheduler starts every task whose dependencies are satisfied, subject to concurrency and policy limits. Independent repository, Jira, observability, and reproduction tasks may run in parallel.

### 3. Execute synchronous tools

A synchronous tool returns a final success or failure in the current graph run. OCA records the result, updates the task, and schedules newly unblocked work.

### 4. Dispatch asynchronous tools

An asynchronous tool returns an operation identifier after accepting work. OCA persists that operation, marks its task as waiting for external work, and returns a status such as:

> Codebot task `batch-4821` has been dispatched and is in progress.

OCA does not continuously poll after returning this response.

If dispatch fails, OCA records a failed submission. If the network outcome is uncertain, it records an unknown dispatch state and reconciles it by idempotency key before attempting another submission.

### 5. Resume on user intent

When the user asks “is it done?”, requests the status of a particular operation, or asks OCA to resume, OCA refreshes the relevant outstanding operations.

- If all selected operations remain active, OCA returns their current status without invoking the planner.
- If an operation reached a terminal state, OCA fetches its result, records the evidence, and invokes the continuation planner once.
- If the user asks about one operation, OCA verifies that it belongs to the request before returning details.

### 6. Continue or replan

The continuation planner receives the durable goal, current plan, completed evidence, outstanding operations, open hypotheses, and the user's latest message. It chooses one of five outcomes:

- **Wait:** required external work is still active.
- **Continue:** the existing plan remains valid and newly ready tasks can start.
- **Replan:** new evidence requires different follow-up work.
- **Finish:** the success criteria have been met or a supported conclusion has been reached.
- **Needs input:** a specific user decision or missing fact blocks meaningful progress.

For example, an inconclusive Codebot result may identify a likely backend code path. The planner can then launch a scoped Splunk investigation for the affected account and service instead of declaring the investigation complete.

## State model

### Request

The request stores its goal envelope, overall status, current plan revision, final response when available, and timestamps. Typical statuses are `running`, `waiting_external`, `completed`, `failed`, and `needs_input`.

### Task

Each task stores its purpose, dependencies, selected tool, inputs, status, attempts, and result references. Task statuses include `pending`, `running`, `waiting_external`, `completed`, `failed`, `blocked`, `superseded`, and `cancelled`.

### External operation

Each asynchronous attempt stores:

- OCA operation identifier and provider job identifier.
- Request, task, and attempt identifiers.
- Tool name and provider.
- Idempotency key.
- Current provider status.
- Submission and last-refresh timestamps.
- Result, error, and artifact references when available.

Provider statuses are normalized into `dispatching`, `dispatch_unknown`, `queued`, `running`, `succeeded`, `failed`, `inconclusive`, `cancelled`, and `expired`.

Large provider outputs remain in an artifact store or source system. Graph state retains a concise summary, structured evidence, provenance, and an artifact reference.

## Tool contract

The tool registry records at least:

- Name and purpose.
- Execution mode: synchronous or asynchronous.
- Input and output schemas.
- Timeout and retry policy.
- Required permissions and account scope.
- Whether cancellation and result retrieval are supported.

Synchronous tools implement one execution operation. Asynchronous tools implement submission, status lookup, and result retrieval. A successful asynchronous submission must provide a stable operation identifier. Business identifiers such as Jira issue keys are ordinary result data unless that tool is explicitly asynchronous.

## Persistence and concurrency

Request state, tasks, plan revisions, operations, evidence, events, and LangGraph checkpoints are stored durably. The API process does not rely on an in-memory future to represent long-running work.

Every external submission uses an idempotency key derived from the request, task, and attempt. A request lease or optimistic concurrency check ensures that simultaneous status requests cannot dispatch the same next task twice or apply the same result more than once.

The scheduler evaluates dependencies at task level. It does not wait for an entire parallel group when one completed task is enough to unlock useful follow-up work.

## API behavior

The service supports three primary interactions:

1. **Create request:** accepts a new goal and begins its initial plan.
2. **Read request:** returns the latest stored status without causing external calls.
3. **Send request message:** accepts status questions, a specific operation identifier, additional evidence, or an explicit resume instruction. This interaction may refresh operations and continue the graph.

A response includes the overall request status, task progress, outstanding operations, evidence-based summary, and the next expected user action when one is required.

## Failure and recovery behavior

- A provider rejection is recorded as a failed dispatch with its reason.
- A submission timeout with an uncertain provider outcome becomes `dispatch_unknown`; OCA reconciles before retrying.
- A failed or inconclusive operation returns evidence to the planner rather than automatically failing the entire request.
- Expired credentials or missing authorization produce a scoped blocked task and an actionable message.
- After restart, OCA reconstructs work from durable state and continues through the same resume path.
- Repeated status and resume requests are safe and do not duplicate external work.

## Observability and evaluation

Every lifecycle transition emits a structured event containing request, task, operation, plan revision, tool, timing, status, and evidence references. These events can be written locally during development and sent to Splunk or a data warehouse in deployed environments.

Trajectory evaluations should verify that OCA:

- Chooses the correct synchronous or asynchronous tool path.
- Returns an operation identifier without polling indefinitely.
- Avoids replanning while required work is still active.
- Continues dependent tasks after a successful result.
- Replans after failed or inconclusive evidence when another useful path exists.
- Preserves the original goal across multiple resumptions.
- Does not duplicate submissions after retries, restarts, or concurrent resume requests.
- Correctly handles several outstanding operations and scoped status questions.
- Produces a final answer only when the goal's success criteria are addressed.

Captured expected and actual trajectories remain suitable for offline replay and RRSI evaluation. Provider responses used in replay are recorded and sanitized so that an isolated trial does not contact production systems.

## Example flow

A user asks OCA to investigate why inventory is physically present in a warehouse but unavailable to a manufacturing work order.

1. OCA preserves the incident objective and account scope in the goal envelope.
2. The planner starts Jira history lookup, a scoped inventory data lookup, and Codebot repository analysis in parallel.
3. Jira and inventory tools return synchronously. Codebot returns `batch-4821`, so its task enters `waiting_external`.
4. OCA reports current findings and that Codebot task `batch-4821` is in progress.
5. Later, the user asks whether the investigation is done.
6. OCA refreshes `batch-4821`, retrieves its completed finding, and runs the continuation planner.
7. The finding points to an allocation service change. OCA dispatches a targeted Splunk investigation for the affected account and records its operation identifier.
8. On the next user-triggered resume, OCA retrieves the Splunk evidence, determines the root cause, and produces a supported resolution plan.

Throughout the flow, OCA retains the original incident goal, preserves previous evidence, and exposes the status of every task and external operation.

## Rollout

1. Introduce the tool execution-mode registry and normalized result contracts.
2. Add durable request, task, operation, evidence, and plan-revision storage.
3. Add asynchronous dispatch and deterministic progress responses.
4. Add the status and resume interaction with continuation planning.
5. Add concurrency controls, restart recovery, and provider adapters.
6. Gate deployment with trajectory tests for synchronous, asynchronous, failure, recovery, and replanning paths.

