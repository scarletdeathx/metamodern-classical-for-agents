# MCFA v2 RNG and Entropy Draft

The performer-facing selection guide and deliberately fictionalized source
personas live in [`V2_RNG_USER_RUBRIC.md`](V2_RNG_USER_RUBRIC.md).

## Purpose

MCFA v2 should treat the ten lanes as an **entropy ecology**. Every lane may use
a different randomness provider, and each lane should independently choose how
that provider drives:

1. **decisions** — probability gates, procedural pattern generation, parameter
   selection, lane replacement, and other control-rate choices; and
2. **sound** — noise oscillators, stochastic modulation, jitter, dust, impulses,
   and other sample- or block-rate synthesis.

This is not only a global engine setting. A single performance might put a fixed
PRNG on lane 1, live OS entropy on lane 2, a recorded quantum result on lane 3,
a randomness beacon on lane 4, and derived substreams or hybrids on the remaining
lanes.

Decisions and sound are still different jobs. A reproducible decision process should not be changed
merely by adding a noise oscillator, and a fresh entropy-driven noise source
should not make the structure of a performance impossible to repeat.

The existing `entropy_stamp` remains a run identity only. It must not silently
become a seed.

## Tracker voice model

The synthesis source and the randomness provider are orthogonal:

```text
lane pattern/clock -> voice or noise algorithm -> envelope/filter/effects -> mix
                              ^
                              |
                       lane entropy bus
                              ^
                              |
                 seeded / system / capture / remote
```

A lane first selects what produces sound:

- conventional periodic oscillators such as sine, square, triangle, and saw;
- a noise voice or stochastic impulse process;
- a future wavetable, physical, granular, or procedural voice; or
- combinations that remain within the lane's bounded voice budget.

It separately selects an RNG configuration. A sine lane does not need to consume
randomness merely because an RNG is available, but it may use the decision domain
for probability or the sound domain for jitter and stochastic modulation.

Most importantly, a noise implementation must never construct its own hidden
`random.Random`, NumPy generator, `SystemRandom`, or device reader. It requests
words from the lane's **entropy bus**. The bus is the framework boundary that
provides domain separation, buffering, provenance, capture/replay, health, and
fallback behavior.

### Classic tracker configuration

V2 should make an intentionally simple four-voice setup natural even though ten
lanes remain available:

```json
{
  "command": "batch",
  "items": [
    {"channel": 1, "patch": {"synth": {"waveform": "square"}}},
    {"channel": 2, "patch": {"synth": {"waveform": "square"}}},
    {"channel": 3, "patch": {"synth": {"waveform": "triangle"}}},
    {"channel": 4, "patch": {
      "synth": {"waveform": "noise", "noise": {"algorithm": "lfsr", "color": "white"}},
      "rng": {"sound": {"mode": "seeded", "algorithm": "lfsr15", "seed": "0x0001"}}
    }}
  ]
}
```

That resembles the discipline of an old console tracker without pretending to
emulate a particular console. The noise lane can then be repatched from a short,
metallic repeating LFSR sequence to a long deterministic sequence, live system
entropy, a captured quantum result, or another provider without changing its
pattern, clock, envelope, or mixer identity.

The same entropy framework can serve multiple noise algorithms:

- `sample-hold`: one random value per configured interval;
- `white`: independent uniform samples or blocks;
- `pink`, `brown`, or band-limited noise: documented filters over entropy-fed
  white noise;
- `lfsr`: explicitly algorithmic pseudo-noise with selectable register/taps;
- `dust`: entropy-timed impulses with bounded density;
- `bitstream`: raw or conditioned provider bits interpreted at a musical rate;
- `jitter`: stochastic variation applied to an otherwise pitched voice.

These are sound transforms, not entropy sources. “Pink noise from Braket” means
a pink-noise transform consuming captured/provider bytes whose provenance points
to Braket; it does not mean the remote service somehow synthesized pink noise.

### Entropy consumption rates

Noise voices should declare how quickly they consume entropy. Per-sample white
noise at 48 kHz, a 15-bit LFSR clocked once per sample, probability checks at the
step rate, and one dust decision per audio block have radically different source
requirements.

The framework should expose a lane's requested and delivered entropy rates. A
remote provider will usually supply finite chunks that are cached, stretched,
or used to seed a local generator; it should not be described as continuously
streaming live quantum randomness unless it actually sustains and records that
rate. Rate adaptation is part of the selected transform and must be visible in
status.

## Design principles

- Give every lane separate **decision** and **sound** RNG domains.
- Let all ten lanes choose different provider instances and change providers
  independently during a performance.
- Route every stochastic synthesis implementation through one framework-owned
  lane entropy interface.
- Make deterministic replay the default and live entropy an explicit choice.
- Never call `SystemRandom`, `os.urandom`, a device, or a network source from the
  CoreAudio callback.
- Resolve seeds and validate sources on the control side before applying a
  patch.
- Record the effective source, algorithm, seed identity, reseed count, and
  fallback state in status/history.
- Do not promise reproducibility across algorithms, MCFA versions, or render
  implementations unless the recorded compatibility contract says it is safe.
- Keep randomness bounded: an entropy source may change values, but never bypass
  gain, feedback, frequency, voice-count, or event-rate limits.

## Proposed patch model

Replace the overloaded v1 `random_seed` with an `rng` object:

```json
{
  "rng": {
    "decision": {
      "mode": "seeded",
      "algorithm": "pcg64dxsm",
      "seed": "0x0123...cdef"
    },
    "sound": {
      "mode": "stream",
      "source": "system",
      "transform": "uniform-f32",
      "underflow": "local-csprng"
    }
  }
}
```

Each domain supports these modes:

| Mode | Meaning | Replay |
| --- | --- | --- |
| `derived` | Derive a domain-separated stream from the performance root seed and lane ID. | Yes |
| `seeded` | Use the supplied integer/hex seed with a named algorithm. | Yes |
| `fresh` | Draw one seed from the named entropy source, then use a local generator. | Yes, if the resolved seed is recorded |
| `stream` | Continuously refill an entropy reservoir from the named source. | Only when capture is enabled |
| `off` | Disable stochastic behavior in that domain; probability becomes deterministic and stochastic sources output their defined neutral value. | Yes |

`stream` is most useful for sound. It is allowed for control-rate decisions, but
the decision log must include draw indices so the performance remains auditable.

### Compact conveniences

The full object is authoritative, but the session parser may accept shortcuts:

```json
{"rng":{"decision":"seeded:0x1234","sound":"system-stream"}}
{"rng":{"decision":"fresh:system","sound":"derived"}}
```

Public status always expands shortcuts to the canonical object.

### Ten-lane source patch

A batch can establish a heterogeneous entropy field atomically:

```json
{
  "command": "batch",
  "items": [
    {"channel": 1, "patch": {"rng": {"sound": {"mode": "seeded", "algorithm": "pcg64dxsm", "seed": "0x1111"}}}},
    {"channel": 2, "patch": {"rng": {"sound": {"mode": "stream", "source": "system"}}}},
    {"channel": 3, "patch": {"rng": {"sound": {"mode": "stream", "source": "capture:braket-night-07"}}}},
    {"channel": 4, "patch": {"rng": {"decision": {"mode": "stream", "source": "beacon:nist"}}}},
    {"channel": 5, "patch": {"rng": {"sound": {"mode": "stream", "source": "plugin:hardware-rng/front-panel"}}}},
    {"channel": 6, "patch": {"rng": {"sound": {"mode": "derived"}}}},
    {"channel": 7, "patch": {"rng": {"sound": {"mode": "stream", "source": "file:prepared-entropy-a"}}}},
    {"channel": 8, "patch": {"rng": {"sound": {"mode": "stream", "source": "mcp:quantum-provider/job-42"}}}},
    {"channel": 9, "patch": {"rng": {"decision": {"mode": "fresh", "source": "system"}, "sound": {"mode": "derived"}}}},
    {"channel": 10, "patch": {"rng": {"sound": {"mode": "mixed", "sources": ["system", "capture:braket-night-07"]}}}}
  ]
}
```

Names above are illustrative provider URIs, not commitments to specific vendors.
The patch records stable provider instance IDs so two lanes may deliberately
share one upstream stream or request separately isolated streams.

Provider changes are lane lifecycle events. A source can be swapped while a lane
keeps sounding, with the switch occurring at a documented entropy block boundary;
or the performer can request a reseed/restart for a hard discontinuity.

## Sources and algorithms

Sources provide entropy; algorithms expand a finite seed into a stream. They
must not be presented as interchangeable concepts.

Initial entropy provider families:

- `system`: the operating system CSPRNG, reached through `secrets`/`os.urandom`;
- `file`: an explicitly configured byte device or recorded entropy file;
- `capture`: a previously recorded MCFA entropy stream for replay;
- `plugin:<name>`: a local hardware, sensor, service, or experimental adapter;
- `mcp:<server>/<resource>`: an MCP-backed control-plane provider; and
- `beacon:<name>` or `quantum:<provider>`: convenient typed provider families.

Python `random.SystemRandom` normally obtains entropy from the same operating
system facility as `os.urandom`; on the same machine they are two APIs, not two
independent physical RNGs. MCFA may accept `system-random` and `urandom` as
user-friendly aliases, but canonical status should report `system` and must not
claim source diversity that does not exist.

Initial deterministic algorithms:

- `pcg64dxsm` for fast control-rate and vectorized synthesis draws;
- `philox` for explicitly keyed independent lane/substreams and parallel renders;
- `chacha20` for a deterministic cryptographic stream and the reservoir fallback;
- `legacy-mt19937` only for replaying v1 `random.Random` performances.

Algorithm names and exact implementations are part of the replay format. Never
label a stream merely `random`.

Hardware RNG, network randomness, sensors, and quantum services should enter
through the source adapter interface, not special cases in the audio engine.
Adapters must declare latency, availability, health, and whether their bytes are
raw, conditioned, or cryptographically mixed. Network sources are never valid
as a direct audio dependency.

### Remote and quantum providers

Amazon Braket or another quantum service could participate through an MCP server,
plugin, or ordinary provider daemon, but only on the control plane:

```text
remote job/service -> provider adapter -> authenticated chunk + provenance
                   -> MCFA reservoir/capture -> lane transform -> audio
```

The adapter may submit or read jobs, validate returned bitstrings, normalize them
into numbered entropy chunks, and attach provider/job/device metadata. MCFA then
consumes those chunks exactly like any other buffered source. Network latency,
credentials, throttling, job failure, and MCP availability never enter the audio
callback.

“Quantum” is provenance, not an automatic sonic property or quality guarantee.
The useful musical distinction comes from how and where bytes are acquired, how
they are transformed, whether lanes share or isolate a stream, and how source
arrival/failure is mapped into sound.

### Source composition

An optional `mixed` mode can combine several sources before distribution. Use a
documented cryptographic combiner rather than interleaving arbitrary byte counts.
This supports gestures such as a deterministic local stream continually mixed
with arriving quantum chunks, or two lanes sharing the same remote source while
using different lane-domain keys.

Mixing must retain a contribution manifest. Status should say which sources are
healthy and contributing; it must not imply that a named source contributed to a
block when the lane was running entirely on fallback.

## Domain separation

A seeded performance begins with a 256-bit `performance_seed`. Derive independent
keys with a stable KDF and labels such as:

```text
mcfa/v2/lane/01/decision
mcfa/v2/lane/01/sound/noise
mcfa/v2/lane/01/sound/modulation
mcfa/v2/conductor/procedural
```

Adding a new consumer must create a new labeled substream rather than consuming
extra values from an existing stream. This prevents a timbre edit from shifting
later probability decisions.

Reseeding is an explicit event. It increments an `epoch` and records the resolved
seed or capture reference. Patch edits that do not touch `rng` preserve stream
position.

## Streaming entropy without risking audio

`system-stream` must be implemented as a producer/consumer reservoir:

1. A non-audio worker fills a fixed-size ring buffer with entropy blocks.
2. The audio callback consumes already-conditioned blocks without locks,
   allocation, I/O, or system calls.
3. Low- and high-water marks regulate refills and appear in health status.
4. If the reservoir empties, the callback immediately uses the configured
   deterministic fallback. It never waits.
5. Recovery starts at a block boundary and is recorded; it must not reset lane
   phase or other RNG domains.

Recommended defaults are a two-second reservoir at the lane's worst-case draw
rate, a refill watermark of 50%, and `local-csprng` underflow seeded during patch
acceptance. `hold`, zero output, and engine failure may exist as expert policies,
but must not be defaults because each can produce a more disruptive result than
the entropy outage itself.

Entropy bytes should be converted in blocks. For uniform float noise, map fixed
unsigned words to `[-1, 1)` using a documented conversion. Gaussian, dust, and
other distributions are transforms over source words and must not be described
as separate entropy sources.

## Decisions: what can actually be seeded

MCFA can reproduce only decisions it owns. A `decision` RNG can drive engine-side
probability checks and a future procedural command API. It cannot make an
external AI conductor deterministic by itself.

For agent-conducted performances, v2 should support a `decision_context` on each
submitted command:

```json
{
  "command": "set",
  "channel": 4,
  "patch": {"pan": -0.7},
  "decision_context": {
    "seed": "0xabcd...",
    "draw_start": 91,
    "draw_end": 94,
    "policy": "mcfa-conductor-v2"
  }
}
```

This proves which random context accompanied a choice without claiming that a
language model, prompt, or external tool is bit-for-bit reproducible. For exact
replay, the applied command history remains the score of record.

A later engine-owned `generate` command may use the lane or conductor decision
stream directly:

```json
{
  "command": "generate",
  "channel": 4,
  "generator": "bounded-step-cell",
  "draws": 24,
  "constraints": {"notes": [36, 39, 42, 48], "steps": 11, "density": 0.45}
}
```

Generators must have named, versioned semantics and a maximum draw budget so a
bug cannot consume an unbounded stream or stall the control thread.

## Capture, replay, and provenance

Status should expose, per domain:

- canonical mode, source, algorithm/transform, and epoch;
- resolved seed as exact hex for `seeded` and `fresh` modes;
- draw counter or consumed block counter;
- reservoir fill, underflows, source errors, and active fallback for `stream`;
- capture ID and byte offset when capture is enabled; and
- compatibility version.

History records configuration/reseed changes and stream health transitions, not
every audio-rate draw. Optional capture writes entropy blocks outside the audio
thread to a chunked file with sequence numbers and hashes. The manifest contains
the run `entropy_stamp`, source metadata, byte count, transform version, and a
whole-capture digest. Captures are data artifacts and must never replace the
permanent project anchor in `ENTROPY.md`.

Treat seeds and captures as provenance rather than secrets by default, while
warning that externally supplied entropy may contain sensitive source material.

## v1 compatibility

During migration:

- `"random_seed": <integer>` maps to both decision and sound domains using
  `legacy-mt19937`, with separate derived substreams only when doing so does not
  break an explicitly requested v1 replay;
- `"random_seed": "system"` keeps v1 semantics: draw once, record the resolved
  seed, and run locally. It maps to `fresh`, **not** `stream`;
- `"random_seed": "default"` maps to `derived`;
- specifying both `random_seed` and `rng` is a validation error; and
- v2 status includes a migration warning until the lane is patched with `rng`.

Exact v1 replay should remain a dedicated compatibility path. New v2 defaults
must use independent domains even though that means the output differs from v1.

## Suggested delivery slices

1. **Domain split:** add the canonical model, seed derivation, status/history,
   and v1 compatibility with deterministic sources only.
2. **Procedural decisions:** add versioned bounded generators and
   `decision_context` logging.
3. **Entropy reservoir:** add `system-stream`, fallback health, stress tests, and
   optional capture/replay.
4. **Source adapters:** add file and plugin sources only after failure,
   starvation, and malicious-source tests exist.

## Acceptance tests

- The same seed, algorithm, compatibility version, commands, and render settings
  produce the same decision log and audio checksum.
- Adding a sound RNG consumer does not alter decision outcomes.
- Adding a decision RNG consumer does not alter an existing sound stream.
- A `fresh` source resolves exactly once on the control thread.
- No streaming source function is reachable from the audio callback.
- Forced source stalls create underflow history and uninterrupted bounded audio.
- Capture replay reproduces stream bytes and the rendered checksum.
- Reseeding one domain leaves the other domain and all unrelated lanes intact.
- Invalid source, algorithm, transform, or mixed v1/v2 configuration is rejected
  before scheduling.
- Status remains JSON-safe and reports exact seeds without numeric precision
  loss.

## Open decisions

- Whether captures are always opt-in or automatically enabled for non-system
  experimental sources.
- Whether `performance_seed` is supplied only at engine start or can begin a new
  recorded epoch without restarting the engine.
- Whether live source bytes should be cryptographically mixed with a local seed
  before use, preserving source contribution while protecting against weak or
  biased adapters.
- Which render settings belong in the formal cross-machine replay contract.
