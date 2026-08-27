# MCFA v2 Randomness Picker

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
| “Play the same stochastic part again.” | `seeded` + `pcg64dxsm` | Fast, stable, recordable, and easy to isolate per lane. |
| “Give every lane an independent but repeatable fate.” | `derived` + domain-separated PCG64DXSM or Philox | One performance seed creates isolated lane streams. |
| “Make old-console metallic noise.” | `seeded` + a short LFSR transform | Audible repetition and bit correlation are the desired color. |
| “Make it different every time, but replayable afterward.” | `fresh:system` | Draws once from the OS and records the resolved seed. |
| “Let live entropy become the actual noise material.” | `system-stream` + capture | Continuously consumes buffered OS entropy and preserves an optional replay. |
| “Tie the piece to a physical object.” | `plugin:<hardware-rng>` | The device becomes part of the instrument and provenance. |
| “Tie the piece to a public moment.” | `beacon:<name>` | Timestamped public randomness can govern structural decisions. |
| “Use a quantum process as source material.” | `quantum:<provider>` or an MCP capture | Finite quantum-job results become attributable entropy chunks. |
| “Use the exact strange stream I found yesterday.” | `capture` or `file` | Treats randomness like tape, a sample, or a found score. |
| “No single source should have authority.” | `mixed` | Combines named contributors with a recorded manifest. |
| “I mainly want the noise to sound darker/rougher/sparser.” | Keep the RNG; change the noise transform | Color, density, filtering, and rate are usually the audible controls. |

## Source cards

### Seeded PCG64DXSM — the reliable tracker default

**Pick it for:** repeatable probability, patterns, modulation, and full-rate
noise; independent streams across many lanes; ordinary performance work.

**Actually changes:** the performance can be recreated from its seed and
versioned algorithm. It is fast and supports robust stream separation.

**Does not inherently sound like:** anything special compared with another good
uniform generator under the same transform.

**Listening mythology:** *precision glass; a huge invisible mechanism that never
forgets which tooth comes next.*

### Philox — the keyed multi-lane machine

**Pick it for:** many independently addressed streams, parallel rendering, or a
design where lane and substream identity should behave like a key.

**Actually changes:** stream management is especially natural when many consumers
must remain independent. It may cost more computation than the fastest choices.

**Listening mythology:** *ten locked drawers opening at once, each with a
different key and no shared dust.*

### ChaCha20 — the sealed deterministic stream

**Pick it for:** deterministic cryptographic expansion, entropy mixing, reservoir
fallback, or when weak/hostile provider input should be conditioned.

**Actually changes:** it gives MCFA a strong deterministic byte stream from a
key. Cryptographic strength does not automatically produce better-sounding noise.

**Listening mythology:** *black water under pressure; continuous, opaque, and
indifferent to inspection.*

### Legacy MT19937 — the archive machine

**Pick it for:** replaying v1 performances or deliberately preserving an older
software lineage.

**Actually changes:** compatibility. It has a very long period but is no longer
the preferred modern default for MCFA's independent lane streams.

**Listening mythology:** *an enormous paper archive whose filing system predates
the building around it.*

### LFSR — the audible pseudo-random circuit

**Pick it for:** short repeating noise, metallic percussion, pitched buzz,
console-like tracker voices, and deliberate machine periodicity.

**Actually changes:** unlike good full-period uniform generators, a short LFSR's
cycle and correlations can become plainly audible. Register length, taps, clock
rate, and bit mapping are primary timbre controls.

**Listening mythology:** *a captive insect tracing the same electrified polygon,
too fast to see but not too fast to hear.*

### Fresh system seed — new fate, local execution

**Pick it for:** a new performance identity without depending on entropy I/O
during audio rendering.

**Actually changes:** MCFA draws one OS-provided seed, records it, then uses a
local deterministic generator. This is the safest “surprise me” choice.

**Listening mythology:** *the door opens once; weather enters; the room then
obeys its own physics.*

### Live system stream — operating-system weather

**Pick it for:** making continuously arriving OS entropy part of the material,
with a reservoir and optional capture.

**Actually changes:** provenance and replay behavior more than expected blind
sound. The lane must report consumption rate, reservoir health, and fallback.
Python `SystemRandom` and `os.urandom` belong to this same source family rather
than representing two independent characters.

**Listening mythology:** *ventilation from outside the machine; no gust belongs
to the room until it arrives.*

### Hardware RNG — the attached object

**Pick it for:** installations and performances where a physical device, sensor,
or noise circuit should be a named participant.

**Actually changes:** behavior depends on that device's conditioning, bandwidth,
health, and bias. MCFA must buffer it and describe whether the bytes are raw or
processed.

**Listening mythology:** *a small unreliable oracle bolted to the chassis.*

### Public randomness beacon — the communal clock

**Pick it for:** timestamped formal decisions, shared performances, externally
verifiable choices, or pieces bound to public time.

**Actually changes:** public beacons are better suited to seeds and structural
decisions than audio-rate noise. Local expansion can turn each published value
into a long reproducible stream.

**Listening mythology:** *the entire room agrees to turn when a distant lighthouse
flashes.*

### Quantum provider or capture — the remote measurement artifact

**Pick it for:** a work whose provenance explicitly includes measured quantum
outcomes, a named job/device, or a finite batch of external bitstrings.

**Actually changes:** the source history and acquisition process. Remote results
arrive too slowly and irregularly to be an audio-thread dependency, so MCFA caches,
captures, or expands them locally. “Quantum” supplies no guaranteed audible aura.

**Listening mythology:** *a sealed handful of decisions mailed from a machine
that was not obliged to choose either answer.*

### Capture or entropy file — randomness as tape

**Pick it for:** exact reconstruction, sharing an entropy performance, using a
found bitstream, or comparing different transforms against identical material.

**Actually changes:** an ephemeral stream becomes a fixed media artifact. This is
the best choice for blind comparisons of RNG transforms.

**Listening mythology:** *weather pressed into vinyl and made accountable to a
needle.*

### Mixed sources — the braid

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

