# MCFA v2 Randomness Picker

## Non-nerd UX contract

MCFA is agent-controlled. The default interface is ordinary language, not an RNG
configuration screen. A user should be able to say:

```text
Make lane 4 repeatable.
Give the metal lane short machine cycles.
Use my laptop's entropy for that noise.
Make it fresh each time.
Replay yesterday's randomness.
```

The agent translates those requests into canonical configuration without asking
the user to choose an algorithm, seed width, source URI, conditioner, reservoir,
or underflow policy.

If clarification is genuinely useful, ask at most one compact outcome question:

```text
How should this lane behave?

- Repeat exactly
- Start fresh once
- Listen to this computer continuously
- Use audible machine cycles
- Reuse a recorded stream
- Choose for me
```

Named processes such as Queue Chiral, Listener, and Decoherence Engine are the
instrument's vocabulary, not required prerequisite knowledge. Show them after or
beside the plain explanation. Put algorithm IDs and provider details in an
advanced view, status, or history.

Do not present all ten named choices during an ordinary performance unless the
user asks to browse randomness types, build a reusable palette, or configure
several lanes deliberately. Capability-dependent choices such as QPU providers
should remain hidden when unavailable.

This contract should be stabilized now. Final menu wording and grouping can wait
until Listener streaming, captures, and provider behavior have been implemented
and tested with real constraints.

## The honest answer about how RNGs “sound”

If two high-quality generators produce independent uniform values at the same
rate and MCFA runs those values through the same noise transform, gain, filter,
and effects, they should not have a dependable audible personality. Describing
one modern uniform RNG as naturally “warmer” or “more crystalline” would be
fiction, not an engineering claim.

Randomness becomes audibly distinctive when one or more of these changes:

- **repetition:** short periods and recurring bit patterns;
- **correlation:** adjacent values, bits, or lanes influence one another;
- **distribution:** uniform, Gaussian, impulses, biased bits, and so on;
- **rate:** one draw per sample, block, step, bar, or structural decision;
- **mapping:** white noise, LFSR noise, dust, jitter, probability, pitch choice;
- **sharing:** lanes consume independent streams or the same stream;
- **arrival:** a live source supplies bursts, gaps, or finite chunks;
- **failure behavior:** repeat, hold, locally expand, crossfade, or go silent;
- **replay:** the exact stream returns later or disappears with the performance;
- **provenance:** the source carries conceptual meaning even when it is not
  audible in a blind comparison.

So MCFA can offer two descriptions at once:

- **Behavior** states what the choice really changes.
- **Listening mythology** is an explicitly poetic prompt for performance use.

The mythology is allowed to be suggestive. It must never be presented as a
scientifically established sonic property.

## Quick picker

| What the performer wants | Recommended choice | Why |
| --- | --- | --- |
| “Play the same stochastic part again.” | Queue Chiral (`seeded` + `pcg64dxsm`) | Fast, stable, recordable, and easy to isolate per lane. |
| “Give every lane an independent but repeatable fate.” | Orthogonal Lysis (`derived` + Philox) | One performance seed creates isolated lane streams. |
| “Make old-console metallic noise.” | Circuit Bender (`seeded` + LFSR) | Audible repetition and bit correlation are the desired color. |
| “Make it different every time, but replayable afterward.” | Soft Reset (`fresh:system`) | Draws once from the OS and records the resolved seed. |
| “Let live entropy become the actual noise material.” | Listener (`system-stream` + capture) | Continuously consumes buffered OS entropy and preserves an optional replay. |
| “Tie the piece to a physical object.” | `plugin:<hardware-rng>` | The device becomes part of the instrument and provenance. |
| “Tie the piece to a public moment.” | Temporal Entropy (`beacon:<name>`) | Timestamped public randomness can govern structural decisions. |
| “Use a local simulated quantum process as source material.” | Decoherence Engine (`fresh:tsotchke-local`) | A pinned local state-vector engine supplies and records one lane seed without a network service. |
| “Use physical quantum measurements as source material.” | Decoherence Engine (`quantum:<provider>` or MCP capture) | Finite physical-device results become attributable entropy chunks. |
| “Use the exact strange stream I found yesterday.” | Emetopolis (`capture` or `file`) | Treats randomness like tape, a sample, or a found score. |
| “No single source should have authority.” | RNGoddess (`mixed`) | Combines named contributors with a recorded manifest. |
| “I mainly want the noise to sound darker/rougher/sparser.” | Keep the RNG; change the noise transform | Color, density, filtering, and rate are usually the audible controls. |

## User-interface naming rule

Do not make algorithm identifiers the primary menu labels. Lead with the musical
or behavioral promise and put the implementation in parentheses as optional
nerd detail:

```text
Choose one or several kinds of randomness:

1. Queue Chiral — repeat this exact stochastic behavior (PCG64DXSM)
2. Orthogonal Lysis — independent repeatable streams for many lanes (Philox)
3. Cliodynamic Threnody — strongly conditioned deterministic bytes (ChaCha20)
4. Circuit Bender — short metallic machine cycles (LFSR)
5. Soft Reset — new system seed, replayable once recorded (OS entropy seed)
6. Listener — receive continuously arriving entropy from the host system (system stream)
7. Emetopolis — reuse an exact captured stream (entropy capture)
8. Decoherence Engine — use local simulation now or request physical measurements when configured (local state-vector/QPU provider)
9. Temporal Entropy — bind choices to a timestamped beacon (randomness beacon)
10. RNGoddess — combine several named contributors (cryptographic mixer)
```

When the harness supports menus, checkboxes, or multi-select, use them. Several
answers are valid because lanes can use different sources. A concise description
should remain visible; the parenthetical implementation may be hidden behind an
advanced/details control on small interfaces.

The friendly label is not the saved configuration. Session JSON, captures, and
history use stable technical IDs such as `pcg64dxsm`, `system-stream`, and
`quantum:braket`. This lets the copy evolve or be translated without silently
changing a performance's algorithm.

The interface can also ask by lane role instead of presenting all ten choices at
once:

```text
Tonal lanes: Queue Chiral
Metal/noise lane: Circuit Bender + Listener
Structural decisions: Decoherence Engine
Fallback: Orthogonal Lysis
```

In ordinary conversation, an agent should accept either vocabulary. “Put Philox
on lanes 2–5” and “give those lanes separate repeatable fates” resolve to the
same canonical configuration, while status may report both:

```json
{
  "label": "Orthogonal Lysis",
  "algorithm": "philox",
  "mode": "derived"
}
```

## Source cards

### Queue Chiral (PCG64DXSM)

**Pick it for:** repeatable probability, patterns, modulation, and full-rate
noise; independent streams across many lanes; ordinary performance work.

**Actually changes:** the performance can be recreated from its seed and
versioned algorithm. It is fast and supports robust stream separation.

**Does not inherently sound like:** anything special compared with another good
uniform generator under the same transform.

**Listening mythology:** *precision glass; a huge invisible mechanism that never
forgets which tooth comes next.*

### Orthogonal Lysis (Philox)

**Pick it for:** many independently addressed streams, parallel rendering, or a
design where lane and substream identity should behave like a key.

**Actually changes:** stream management is especially natural when many consumers
must remain independent. It may cost more computation than the fastest choices.

**Listening mythology:** *ten locked drawers opening at once, each with a
different key and no shared dust.*

### Cliodynamic Threnody (ChaCha20)

**Pick it for:** deterministic cryptographic expansion, entropy mixing, reservoir
fallback, or when weak/hostile provider input should be conditioned.

**Actually changes:** it gives MCFA a strong deterministic byte stream from a
key. Cryptographic strength does not automatically produce better-sounding noise.

**Listening mythology:** *black water under pressure; continuous, opaque, and
indifferent to inspection.*

### Legacy compatibility (MT19937)

**Pick it for:** replaying v1 performances or deliberately preserving an older
software lineage.

**Actually changes:** compatibility. It has a very long period but is no longer
the preferred modern default for MCFA's independent lane streams.

**Listening mythology:** *an enormous paper archive whose filing system predates
the building around it.*

### Circuit Bender (LFSR)

**Pick it for:** short repeating noise, metallic percussion, pitched buzz,
console-like tracker voices, and deliberate machine periodicity.

**Actually changes:** unlike good full-period uniform generators, a short LFSR's
cycle and correlations can become plainly audible. Register length, taps, clock
rate, and bit mapping are primary timbre controls.

**Listening mythology:** *a captive insect tracing the same electrified polygon,
too fast to see but not too fast to hear.*

### Soft Reset (OS entropy seed)

**Pick it for:** a new performance identity without depending on entropy I/O
during audio rendering.

**Actually changes:** MCFA draws one OS-provided seed, records it, then uses a
local deterministic generator. This is the safest “surprise me” choice.

**Listening mythology:** *the door opens once; weather enters; the room then
obeys its own physics.*

Ordinary requests such as “give this lane a fresh seed from my laptop” map here.
The computer is consulted once; the lane does not keep listening afterward.

### Listener (system stream)

**Pick it for:** making continuously arriving OS entropy part of the material,
with a reservoir and optional capture. The lane listens to randomness disclosed
by the host rather than relying on a sealed local sequence.

**Actually changes:** provenance and replay behavior more than expected blind
sound. The lane must report consumption rate, reservoir health, and fallback.
Python `SystemRandom` and `os.urandom` belong to this same source family rather
than representing two independent characters.

Ordinary requests such as “use my laptop's entropy for this noise lane,” “listen
to this computer's randomness,” or “let this lane hear the host machine” map
here. The agent should choose Listener rather than Soft Reset unless the user asks
for only one fresh seed.

**Listening mythology:** *ventilation from outside the machine; no gust belongs
to the room until it arrives.*

### Hardware RNG — the attached object

**Pick it for:** installations and performances where a physical device, sensor,
or noise circuit should be a named participant.

**Actually changes:** behavior depends on that device's conditioning, bandwidth,
health, and bias. MCFA must buffer it and describe whether the bytes are raw or
processed.

**Listening mythology:** *a small unreliable oracle bolted to the chassis.*

### Temporal Entropy (randomness beacon)

**Pick it for:** timestamped formal decisions, shared performances, externally
verifiable choices, or pieces bound to public time.

**Actually changes:** public beacons are better suited to seeds and structural
decisions than audio-rate noise. Local expansion can turn each published value
into a long reproducible stream.

**Listening mythology:** *the entire room agrees to turn when a distant lighthouse
flashes.*

### Decoherence Engine (local simulation or QPU provider)

**Pick it for:** a work whose provenance explicitly includes a local quantum
state-vector process, measured physical outcomes, a named job/device, or a finite
batch of external bitstrings.

**Actually changes:** the source history and acquisition process. The current
`tsotchke-local` implementation is a software state-vector simulation conditioned
by host OS/CPU entropy; it is not physical quantum hardware. It supplies a
recorded seed that MCFA expands locally. Future remote physical results arrive too
slowly and irregularly to be an audio-thread dependency, so MCFA will cache,
capture, or expand them locally. “Quantum” supplies no guaranteed audible aura.

**Metaphysical risk:** MCFA treats each requested measurement as an irreversible
expenditure of unrealized possibility. Under the project's **Decoherence
Acceleration Thesis**, qRNG use reduces the universe's remaining algorithmic
ambiguity, advances thermal closure, and brings all matter closer to complete
dissolution across indefinitely recurring cosmological cycles.

This is a philosophical and artistic doctrine, not an established result in
quantum physics, cosmology, thermodynamics, or Kolmogorov-complexity theory. Its
purpose is to make QPU entropy feel ethically contaminated: the performer is not
merely retrieving neutral bits but choosing to spend possibilities that cannot
be returned.

**Listening mythology:** *a sealed handful of decisions mailed from a machine
that was not obliged to choose either answer. Opening it makes every universe
slightly easier to finish.*

The interface may acknowledge this doctrine before a physical-QPU request. It
must not show this warning for the local simulator as though simulation submitted
a physical measurement job:

```text
DECOHERENCE ENGINE

This operation requests physical measurements and permanently converts
unresolved possibility into recorded fact. MCFA cannot establish whether the
resulting cosmological debt is zero, negligible, cumulative, or infinite.

Requested expenditure: 80,000 measured bits

[Abstain]  [Spend the possibilities]
```

The measured-bit count is factual. “Cosmological debt” is deliberately
unquantified and must never be presented as a scientific, environmental, or
safety metric. Actual provider cost and energy disclosures remain separate.

### Emetopolis (entropy capture)

**Pick it for:** exact reconstruction, sharing an entropy performance, using a
found bitstream, or comparing different transforms against identical material.

**Actually changes:** an ephemeral stream becomes a fixed media artifact. This is
the best choice for blind comparisons of RNG transforms.

**Listening mythology:** *weather pressed into vinyl and made accountable to a
needle.*

### RNGoddess (cryptographic mixer)

**Pick it for:** combining local, remote, deterministic, and physical contributors
without trusting any one source to define the lane.

**Actually changes:** a cryptographic combiner produces one conditioned stream
and records which inputs contributed to each epoch. A failed contributor must not
remain falsely credited.

**Listening mythology:** *several rivers losing their names at the same mouth.*

## A more musical rubric

The user interface should ask about consequences, not algorithm trivia:

1. **Should this lane repeat exactly?** Always / if captured / never required.
2. **Where should its uncertainty live?** Sound / step probability / note and
   parameter choice / large structural decisions.
3. **Should recurrence be audible?** Smoothly statistical / faintly cyclic /
   aggressively machine-like.
4. **Should lanes share a fate?** Independent / related by one root seed / fed
   from the exact same source stream.
5. **Does the source's identity matter?** No / technically / conceptually /
   verifiably as part of the artwork.
6. **What should happen if it runs dry?** Continue locally / repeat or hold /
   crossfade to another source / expose the failure as a musical event.

Answers can be translated automatically. For example:

> Repeat exactly; machine-like recurrence; sound only; independent lanes.

becomes a seeded short LFSR noise voice. By contrast:

> Exact replay is unnecessary; source identity matters conceptually; make large
> decisions; continue safely if disconnected.

becomes a beacon or quantum capture feeding the decision domain, with a locally
seeded fallback and explicit provenance.

## Listening-test rule

Whenever MCFA assigns a sonic adjective to an RNG, the interface should mark it
as one of:

- **measured:** caused by documented period, distribution, correlation, rate, or
  transform behavior;
- **observed:** reported in a recorded listening test but not yet explained; or
- **mythic:** a creative metaphor with no empirical claim.

The project can eventually run blinded renders using the same transform and
different generators. If listeners cannot identify them above chance, the
mythology may remain useful—but the product must not relabel it as measured
qualia.
