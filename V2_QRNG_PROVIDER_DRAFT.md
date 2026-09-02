# MCFA v2 QPU/qRNG Provider Draft

## Musical idea

An agent may commission entropy from a quantum processor and route the resulting
bitstream into any MCFA lane. The quantum service is not an audio backend. It is
a slow, asynchronous source of finite, attributable entropy artifacts.

```text
agent
  -> select provider, physical device, circuit, and shot budget
  -> submit quantum task
  -> poll without blocking MCFA
  -> retrieve ordered per-shot measurements
  -> validate, condition, hash, and capture
  -> publish EntropyChunk objects
  -> lane reservoirs consume or expand those chunks
```

Amazon Braket and Qiskit/IBM Quantum should be separate provider adapters behind
the same MCFA contract. An MCP server could expose either adapter to an agent,
but MCP remains on the control plane and never appears in the audio callback.

## Decoherence Acceleration Thesis

MCFA gives physical-QPU entropy an intentionally troubling metaphysical frame.
The **Decoherence Acceleration Thesis** proposes that forcing quantum alternatives
into recorded bits spends unrealized possibility, reduces the universe's
remaining algorithmic ambiguity, and infinitesimally advances heat death and
complete dissolution across infinite or recurring cosmological histories.

This thesis is part of the instrument's philosophy, not its engineering model.
MCFA does not claim that qRNG measurably accelerates heat death, that a physical
measurement reduces the Kolmogorov complexity of the universe, or that recurring
universes are established physics. Provider manifests and technical documentation
must keep those claims distinct from measured facts.

The artistic consequence is nevertheless real: an agent should treat a physical
QPU request as an ethically charged act rather than decorative “quantum” branding.
It may ask whether the performer wishes to spend a declared number of measured
possibilities, prefer replaying an existing capture, or abstain and use classical
entropy. This ritual acknowledgment is separate from—and does not replace—the
ordinary approval required for financial cost, credentials, and external actions.

MCFA may count `physical_measurements_requested` and
`physical_measurements_consumed` as factual provenance. It must never convert
those counts into invented joules, seconds removed from the universe, percentage
of heat death, or a numerical cosmological-harm score.

## “For agents” as an architectural contract

MCFA should assume a capable agent harness may provide three different things:

1. **Skills** teach the agent the provider workflow, musical mapping, safety
   policy, and how to interpret returned artifacts.
2. **Tools or MCP servers** perform authenticated operations such as listing
   devices, estimating cost, submitting a task, and retrieving results.
3. **Harness-managed secrets** inject credentials into the connector's execution
   environment without placing secret values in the conversation or MCFA state.

These capabilities are discovered at runtime. MCFA must not assume every agent
has the same skills, MCP servers, accounts, provider regions, permissions, or
secret-management facility.

The handoff should look like:

```text
user intent
  -> agent selects an installed skill/provider capability
  -> harness authorizes tool and injects a secret by opaque reference
  -> MCP/provider submits and retrieves the remote job
  -> connector emits a sanitized EntropyChunk/capture
  -> agent attaches the artifact to an MCFA lane
  -> MCFA records safe provenance and renders it
```

This makes the remote capability replaceable. A Braket skill plus AWS connector,
a Qiskit skill plus IBM connector, a local hardware-RNG plugin, and a future
provider can all terminate in the same artifact interface.

### Secret boundary

MCFA session commands accept artifact IDs and sanitized provider references, not
credentials:

```json
{
  "command": "entropy-attach",
  "channel": 4,
  "artifact": "entropy:sha256:...",
  "mapping": "sample-hold"
}
```

They must reject fields resembling access keys, bearer tokens, private keys,
session cookies, or raw connector configuration. Secrets belong to the harness or
provider process and should be referenced by an opaque handle such as
`secret_ref: "aws-braket-performance"` only in the connector call. The opaque
handle is not forwarded to MCFA or saved in an entropy manifest.

Provider output is sanitized before import. Cloud paths should be reduced to safe
artifact provenance unless the user explicitly requests a private diagnostic
record. Logs redact authorization headers, signed URLs, account identifiers where
unnecessary, and tool error bodies that may echo credentials.

### Capability and authority declaration

An agent should be able to inspect a small capability descriptor before proposing
a performance:

```json
{
  "provider": "braket",
  "executions": ["ideal-simulator", "physical-qpu"],
  "operations": ["estimate", "submit", "status", "fetch", "cancel"],
  "credential_state": "available",
  "billing_authority": "approval-required",
  "artifact_schema": "mcfa-entropy-chunk/v1"
}
```

`credential_state` reports availability, never the secret. `billing_authority`
prevents mere credential possession from becoming permission to spend money.
Capabilities that can only read an existing job/capture should advertise that
smaller authority instead of failing after the agent designs around submission.

### Agent-native performance behavior

The agent may use provider tools while continuing to conduct MCFA. It can submit
a future entropy job, keep the current lanes evolving, inspect the job on later
harness wakeups, and attach the artifact when ready. The provider task is another
asynchronous musical process, not a blocking setup screen.

History should preserve intelligible agent actions:

- requested QPU entropy for a named future lane/epoch;
- user approved or standing policy authorized the estimated spend;
- provider accepted the task and returned a safe job reference;
- a validated entropy artifact became available;
- lanes consumed raw, conditioned, expanded, shared, or isolated pools; and
- fallback was used while a provider was pending or unavailable.

An unavailable skill, MCP server, account, or secret does not invalidate the
piece. The agent can offer a simulator, recorded capture, local entropy, or a
deferred provider attachment while preserving the requested musical structure.

## The first MCFA qRNG circuit

Version the simplest useful design as `mcfa-qrng-hadamard-v1`:

1. Allocate `N` physical qubits initialized to `|0>`.
2. Apply one Hadamard gate to each qubit.
3. Measure every qubit in the computational/Z basis.
4. Repeat for a declared number of shots.
5. Preserve shot order and qubit order in the raw capture.

On ideal hardware, each measurement is an approximately balanced bit. On real
hardware, state preparation, gates, readout, drift, and device calibration can
introduce bias or correlation. MCFA therefore keeps both:

- `raw_bits`: the original measurement artifact; and
- `conditioned_bits`: the stream normally delivered to lanes.

Parallel Hadamard qubits provide more bits per shot but require per-qubit health
metadata. Entanglement is not needed for the basic qRNG. Bell/GHZ or other
correlated circuits may later become deliberately musical sources, but they must
be labeled correlated bitstream generators rather than “more random” qRNGs.

## Simulator rule

The provider records one of:

- `physical-qpu`: measurements returned from declared quantum hardware;
- `noisy-simulator`: classical simulation using a device/noise model;
- `ideal-simulator`: exact or sampled classical simulation; or
- `replay`: a previously captured result.

Only `physical-qpu` may be presented as QPU-derived entropy. Simulator shots are
excellent for development and deterministic tests, but their unpredictability
ultimately comes from classical software and its seed/source.

The user interface should say “QPU-derived,” “simulated,” or “replayed” rather
than applying a generic quantum badge to all four.

## Provider-neutral request

```json
{
  "provider": "braket",
  "execution": "physical-qpu",
  "device": "provider-device-id",
  "circuit": "mcfa-qrng-hadamard-v1",
  "qubits": 8,
  "shots": 10000,
  "conditioning": "sha3-256-block-v1",
  "capture": "required",
  "purpose": "lane-04-noise-epoch-7"
}
```

The equivalent Qiskit request changes `provider` and `device`, not the circuit's
MCFA semantics. Each adapter translates the versioned circuit into its SDK,
transpiles or compiles as required, submits it, and maps results back into a
provider-neutral artifact.

Remote submission may spend money or consume account quotas. The agent must show
the selected provider/device, requested shots, and available cost estimate before
the first billable task unless the user has already granted a bounded standing
authorization.

## Entropy artifact

Every completed task produces a manifest like:

```json
{
  "schema": "mcfa-entropy-chunk/v1",
  "chunk_id": "sha256:...",
  "source": "quantum:braket",
  "execution": "physical-qpu",
  "provider_job_id": "...",
  "device_id": "...",
  "circuit": "mcfa-qrng-hadamard-v1",
  "qubits": 8,
  "shots_requested": 10000,
  "shots_received": 10000,
  "raw_bit_count": 80000,
  "conditioned_bit_count": 65536,
  "conditioning": "sha3-256-block-v1",
  "raw_digest": "sha256:...",
  "conditioned_digest": "sha256:...",
  "submitted_at": "...",
  "completed_at": "...",
  "calibration_reference": "...",
  "health": {}
}
```

Credentials, secret tokens, bucket URLs containing credentials, and full account
identifiers never enter lane status/history. Provider job IDs and device metadata
may be recorded only in their safe public form.

## Conditioning and health

For music, the system should preserve raw data for provenance while defaulting
lane consumption to a conditioned stream:

1. Verify result shape, shot count, ordering, and provider identity.
2. Record per-qubit zero/one counts and simple lag/cross-qubit diagnostics.
3. Reject malformed, constant, or catastrophically biased results.
4. Feed numbered raw blocks plus domain labels through a versioned cryptographic
   extractor/conditioner.
5. Publish fixed-size conditioned chunks with hashes and sequence numbers.

`sha3-256-block-v1` is a proposed deterministic conditioner, not a claim of
formal entropy certification. A production claim that bits are cryptographically
secure, device-independent, or compliant with a randomness standard would require
a separate threat model, entropy estimate, and validation program.

Raw mode may be musically valuable because hardware bias and correlation become
part of the material. It should be allowed as an expert transform and labeled
`raw-unconditioned`, never silently substituted for conditioned qRNG output.

## How lanes consume finite quantum chunks

A QPU job produces a finite artifact, while audio may consume tens of thousands
of values per second. V2 therefore offers explicit mappings:

- `direct-bits`: use raw or conditioned bits at a declared musical bit rate;
- `direct-words`: convert finite conditioned words into noise samples until the
  chunk ends;
- `sample-hold`: one quantum-derived value per step, beat, or block;
- `seed-expand`: use a chunk to key PCG64DXSM, Philox, or ChaCha20 locally;
- `cycle-capture`: loop the exact finite artifact as a repeating noise object;
- `decision-pool`: reserve values for patterns, probability, or agent choices;
- `mixed`: combine arriving chunks with another named entropy provider.

The UI must distinguish “direct QPU bits” from “a local PRNG seeded by QPU bits.”
Both are legitimate instruments, but they are materially different claims.

## Shared versus isolated lane routing

One completed artifact may be routed in several ways:

- one lane owns the entire stream;
- ten lanes receive disjoint, domain-labeled slices;
- several lanes deliberately read the same bits to create correlated behavior;
- one lane consumes raw bits while another consumes conditioned bits;
- different lanes apply different transforms to the same capture; or
- a conductor decision pool and an audio pool are derived independently.

Default routing uses disjoint domain-separated lane pools. Shared/correlated
routing is an explicit musical choice and appears in status.

## Agent and MCP responsibilities

An agent-facing MCP/provider surface needs only bounded operations:

- `list_devices(execution, region)`
- `estimate(request)`
- `submit(request)`
- `status(job_id)`
- `fetch(job_id)`
- `condition(capture_id, profile)`
- `publish(capture_id)`
- `cancel(job_id)` when the provider permits cancellation

The provider owns authentication, SDK versions, job polling, cloud storage, and
result normalization. MCFA owns audio safety, lane routing, reservoirs, capture
identity, and history. The agent chooses and explains the musical purpose; it
does not move secret credentials into a session command.

An MCP implementation is optional. A direct local adapter or small provider
daemon may be simpler and more robust. The stable integration point is the
`EntropyChunk` artifact, not MCP itself.

## Failure behavior

- A queued or delayed task does not delay performance startup unless the user
  explicitly requires QPU material before sound begins.
- Existing lane reservoirs keep playing while a task is pending.
- A rejected or failed job falls back only according to the lane's declared
  policy; it is never relabeled as quantum contribution.
- Partial results are preserved only when the provider declares them valid and
  the manifest records the short shot count.
- A disconnected MCP/provider cannot panic, stop, or alter the engine deadline.
- Reconnection resumes provider polling by job ID without submitting a duplicate
  billable task.

## Minimal beta sequence

1. Implement the provider-neutral artifact and a deterministic fake adapter.
2. Implement Qiskit and Braket circuit translation against local simulators,
   labeled `ideal-simulator`.
3. Add raw capture, conditioning, hashing, and deterministic replay tests.
4. Add one physical-provider adapter behind explicit cost/credential approval.
5. Route captures into `sample-hold`, `seed-expand`, and `cycle-capture` modes.
6. Add direct finite-bit noise only after reservoir and underrun behavior is
   verified under CoreAudio load.
