# Queued execution architecture

`EXECUTION_MODE=sync` remains the default. `EXECUTION_MODE=queued` opts into
shared inventory, durable request records, Storage Queues, and Python Azure
Functions. Changing the setting alone is insufficient: configure storage and
deploy/start the Functions application as described in the
[infrastructure guide](infrastructure.md). No authentication bypass is added.

For staged rollout or recovery, `activate_queued_execution=false` keeps
provisioned storage but stops the worker and selects synchronous web execution.
It must be applied successfully; editing local variables does not pause Azure
processing. Restricted subscriptions can use
`enable_private_storage_networking=true` for private Blob/Queue endpoints and
outbound app VNet integration without reopening public storage access.

## Implemented path and integration boundaries

```text
Browser + MSAL -> App Service / FastAPI
                     | GET servers -> Blob inventory cache
                     | POST disable -> Blob request record -> Storage Queue
                     | GET request -> owner-only Blob status
                                                        |
                                             queue-triggered Function
                                                        |
                                           shared Commvault HTTP adapter
                                             /                     \
                               private simulated API       approved live API
                                shared Blob state        (optionally via APIM)

Timer Function -> same adapter -> latest successful inventory in Blob
Poison-queue Function -> reconcile unresolved request outcomes
```

The two upstream operations remain `GET /V4/Servers` and
`PUT /V4/Server/{serverId}/Backup/Action/Disable`. Request submission and status
lookup are **this application's endpoints**, not invented Commvault APIs.

The simulated API uses private HTTPX ASGI transport inside Python, with shared
Blob-backed simulated state in queued mode. It does not traverse APIM. An
existing APIM gateway can be the approved live base URL when its API prefix,
routes, credentials, and network path match the adapter. Client-specific APIM
policy provisioning and an APIM-hosted remote simulator are not included.
Application Gateway is separately opt-in infrastructure; TLS, hostname,
networking, ingress restrictions, and deployment validation remain prerequisites.

## Submission and tracking contract

1. The API validates the Entra token, operator role, live-write gate, target IDs,
   typed confirmation, and requested re-enable deadline.
2. The browser generates a UUID `Idempotency-Key` and saves that reference before
   submitting. The server can generate one for callers that omit the header.
3. The API persists a request record before sending its queue message. A `202`
   means queued/accepted for processing, **not** that backups were disabled.
   Storage/enqueue failures are reported explicitly.
4. The worker updates durable per-target intent and outcomes. The browser polls
   `GET /api/requests/{requestId}`; only the submitting tenant/user can read it.
5. The same owner, key, and payload reuse the same request. A changed payload
   conflicts; another owner cannot use the key to read a request.

Overall status is `queued`, `running`, `completed`, `partial`, `failed`, or
`unknown`. Individual targets are `pending`, `running`, `accepted`, `failed`, or
`unknown`, with `success` true, false, or null. Records also carry the request's
original mode, targets, options, and submitted/updated timestamps.

`completed` means all disable requests were accepted by the upstream contract.
It is not a current-backup-state query or verification of re-enablement.
`partial` means mixed accepted/failed targets. Any ambiguous target requires
reconciliation and is surfaced as an unknown outcome, not silently retried.

## Failure and concurrency behavior

- Storage Queues deliver at least once. Leases and conditional writes coordinate
  request processing and overlapping targets; terminal duplicate deliveries
  do not repeat mutations.
- The worker persists target intent **before** calling the upstream API. An
  interruption or ambiguous transport failure after that point must not cause
  an automatic replay of that mutation. Unresolved targets remain blocked from
  new operations; stopping browser tracking does not clear that protection.
  This phase has no operator reconciliation/unblock endpoint. Establish an
  approved recovery procedure and verify the upstream outcome before changing
  coordination records.
- Live writes and the stored mode are checked again at execution time. An
  absolute `enableAfterADelay` deadline is not extended by time spent queued;
  an expired deadline is rejected rather than silently shifted.
- Retries and poison handling are recovery mechanisms, not exactly-once
  guarantees. Storage outages, lease loss, and upstream ambiguity require
  monitoring and operator reconciliation.
- Blob records and queue messages have separate commits. Do not assume a
  successful write to one guarantees the other, and do not delete request
  records while their messages or retries can still exist.

## Inventory freshness

The timer refreshes inventory through the same upstream adapter. The API reads
the shared cache rather than calling Commvault on every page refresh. Responses
include `inventory.updatedAt`, `inventory.stale`, and `inventory.refreshError`.
No initial cache returns an explicit unavailable response, not fabricated data.
Refresh failure preserves the last good inventory and surfaces its age/error.

The UI says **Reload inventory**, shows the cache timestamp, and warns when the
cache is stale. Reloading does not force the timer to run or make old data fresh.
Freshness is an operator warning, not an assertion of current backup state.

## Browser recovery

Only the last Request ID is stored in browser local storage, keyed by tenant,
SPA, and MSAL account. Server records remain authoritative. The UI exposes
manual lookup and supports viewing a saved request even if inventory is
temporarily unavailable. It does not provide a request-history list.

A lost submission response triggers a read of the same UUID, never an automatic
repeat write. Failed status checks stop automatic polling and expose **Check
status**. **Stop tracking** requires acknowledgement and only clears the
browser's reference; it does not cancel processing. Save the ID before stopping.
Storage-denied browsers receive explicit instructions to save the ID manually.

## Operational limits

Configure retention and access controls for request records, inventory,
coordination, simulated state, logs, and poison messages. Records can contain
operator identifiers, server names, and operational history. Alert on queue age,
failed inventory refreshes, poison messages, and unknown outcomes.

Validate the Function host/bindings, managed-identity RBAC, timer execution,
worker restart recovery, networking, and the real Entra browser flow in the
target subscription before enabling queued mode for a shared deployment.
Local adapter/unit/browser tests are not a substitute for that deployment test
or for an approved read-only compatibility check against the client's API.
