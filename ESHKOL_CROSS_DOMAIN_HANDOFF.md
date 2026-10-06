# MCFA → Eshkol/phonond cross-domain handoff

Date: 5 October 2026

## Why this exists

The human is moving this family of work to an agent that already understands
Eshkol and has access to the relevant repositories. The receiving agent should
not interpret this as a request to reproduce MCFA in Eshkol line by line.

Three side projects were originally imagined as direct MCFA applications. Their
purposes must survive a transfer to an Eshkol-backed implementation, with
`phonond` acting as the likely shared stochastic-audio/MIDI backend:

- [phonond](https://github.com/scarletdeathx/phonond) — existing private Eshkol
  backend project;
- [aleatori-gate](https://github.com/scarletdeathx/aleatori-gate) — empty private
  repository created as a project boundary;
- [aleatori-spelling](https://github.com/scarletdeathx/aleatori-spelling) — empty
  private repository created as a project boundary; and
- [meat-proxy](https://github.com/scarletdeathx/meat-proxy) — empty private
  repository created as a project boundary.

The three new repositories are deliberately empty. Do not mistake that for an
invitation to apply generic scaffolding. Their project sidechats were developed
separately and do not yet share all of the MCFA, Eshkol, phonond, or entropy
vocabulary recorded here. This document is the bridge.

## Existing technical context

The receiving agent already has a working Eshkol lineage under its thumb. The
human reports an Eshkol/Moonlab/qRNG/Z1 stratum server and an Eshkol nonce picker
for a Rust Monero miner. That proven implementation is a stronger practical
starting point than inventing another entropy system solely for these music
projects.

MCFA remains the reference for the musical entropy contract. Its published
[`codex/v2-beta`](https://github.com/scarletdeathx/metamodern-classical-for-agents/tree/codex/v2-beta)
checkpoint introduced independent decision and sound domains, bounded entropy
providers, source provenance, deterministic local expansion, and a reservoir
foundation. Python/CoreAudio is not sacred to the side projects; those semantics
are.

The smallest useful shared boundary is conceptually:

```text
bounded entropy provider
  -> attributed entropy chunk or capture
  -> independently named stochastic domains
  -> Eshkol transformation/composition logic
  -> phonond audio or project-specific MIDI/export layer
  -> output plus provenance manifest
```

Avoid divergent implementations by giving Eshkol/phonond an adapter equivalent
to MCFA's narrow provider operation:

```text
read(count) -> bytes + provider/execution/origin/version/revision/physical_qpu
```

Provider acquisition must remain outside any hard real-time rendering callback.
A requested provider failure must be visible; do not silently replace it with a
different entropy source.

## The MCFA RNG vocabulary being inherited

These performer-facing names describe different behaviors. They are not all
implemented to the same degree:

1. **Queue Chiral** (`PCG64DXSM`) — repeatable deterministic behavior;
2. **Orthogonal Lysis** (`Philox`) — independent repeatable streams;
3. **Cliodynamic Threnody** (`ChaCha20`) — conditioned deterministic expansion;
4. **Circuit Bender** (`LFSR`) — short machine cycles;
5. **Soft Reset** (OS entropy seed) — one fresh system seed, recorded afterward;
6. **Listener** (system stream) — continuously arriving buffered entropy;
7. **Emetopolis** (entropy capture) — reuse an exact captured stream;
8. **Decoherence Engine** (local simulation or QPU provider) — request and
   capture quantum-formal or physical measurement material;
9. **Temporal Entropy** (randomness beacon) — bind decisions to a timestamped
   public source; and
10. **RNGoddess** (cryptographic mixer) — combine named contributors.

At the published beta checkpoint, the four deterministic algorithms, Soft Reset,
and a one-shot local Decoherence Engine source exist. The reservoir primitive
exists, but Listener is not yet a completed lane-facing stream mode. Emetopolis,
physical-QPU adapters, Temporal Entropy, and the mixed-source RNGoddess behavior
remain designs rather than finished features. Preserve those status distinctions.

MCFA's current local Tsotchke provider is a **classical state-vector simulation
conditioned by host OS/CPU entropy; physical QPU: no**. It may honestly be called
a simulated quantum representation or transformation. It must not be described
as physical quantum randomness. Physical-qRNG language is reserved for captured
measurements that actually came from attributable physical hardware.

MCFA's reservoir digest covers bytes produced into its buffer. A MIDI or offline
composition manifest additionally needs the count and digest of bytes actually
consumed by that work. A digest is evidence, not a substitute for retaining the
captured bytes or resolved root when exact reconstruction matters.

## Aleatori Gate

Aleatori Gate is the Eigendoll streaming release. Its developing premise is
randomness-based music with meaningful, AI-assisted lyrics. The streaming
identity, relationship to live or periodically arriving entropy, and lyrical
authorship distinguish it from Aleatori Spelling.

Do not collapse the two Aleatori projects into different presets for one
generator merely because they may share mora, MIDI, entropy, or Vocaloid tools.
Their release contexts and authorship rules differ.

The exact spelling `Aleatori Gate` versus `Aleatori Gates` was not settled in the
source discussion. Confirm it with the human before encoding it into release
metadata.

## Aleatori Spelling

Aleatori Spelling is the Scarlet Death work intended for a Subvert-exclusive
release. The human's stated boundary is no AI-generated musical or lyrical
material for this release. Procedural stochastic composition, Japanese-mora
selection, MIDI generation, and Vocaloid realization are the intended method.

The aesthetic direction is operatic: arias and cascades of randomized Japanese
syllables, with recognizable musical form but without pretending the generated
mora form meaningful Japanese language.

The presently discussed arrangement is five coordinated parts:

- lead Vocaloid;
- vocal harmony; and
- three instrumental parts.

Five synchronized MIDI files were proposed, not ratified as an immutable format.
The system should support controlled duration, generation intervals, motion,
breaks, modal changes, and relationships between notes. ABA and several detailed
contour/mora ideas appeared in discussion, but remain suggestions rather than
approved composition laws.

A strong initial architecture is one attributed finite entropy root or capture
per generated work, expanded into independently named domains for structure,
mora, lead pitch, lead rhythm, harmony, and each instrument. Adding a harmony
draw must not perturb the lead, structure, or instruments. Phrase- or event-rate
fresh entropy can be added later if its continuing arrival matters artistically;
offline MIDI generation does not require audio-rate entropy acquisition.

The Aleatori discussion is available locally as Codex task
`01a0b648-589a-7363-8ded-394de55cab11` (`aleatori`). Its existing handoff is
planning context, not proof of implementation.

## MEAT PROXY

MEAT PROXY is not a collection of random songs. Each track is one coordinated
musical organism distributed across 118 spatial objects.

A small set of intentional instrumental identities—currently imagined as roughly
four or five—produces coordinated material that is split across many MIDI/object
lanes. Apparent movement arises from which object is active, silent, interrupted,
or handing material elsewhere. The primary compositional mechanism is patterned
absence rather than conventional pan automation.

Desired perceptual behaviors include:

- traveling around or within a sphere;
- swarm behavior and temporary local exclusion;
- spatial cascades created by rests and handoffs; and
- coherent song-level identity despite stochastic local activity.

The eventual pipeline may involve hundreds of stochastic MIDI files plus
command-line Dolby Atmos and DaVinci Resolve orchestration. The computer may not
be able to render all 118 objects live; staged or offline production remains a
valid realization of the same composition. Do not weaken the 118-object concept
merely to force a live implementation prematurely.

The MEAT PROXY discussion is available locally as Codex task
`01a0b321-ab5e-7bb1-9fb7-d3d6c19fabc1` (`Design MEAT PROXY spatial MIDI`). Its
workspace already contains a small Gardnn project index and Design Bible, but the
new GitHub repository intentionally contains none of that material yet.

## What should transfer, and what should not

Transfer:

- source identity and honest provenance;
- independent stochastic domains whose consumers cannot perturb one another;
- explicit mapping from entropy to musical decisions;
- bounded acquisition and visible starvation/failure behavior;
- versioned transformations and output hashes;
- the user's named RNG vocabulary where it remains artistically relevant; and
- each project's distinct authorship and release constraints.

Do not transfer by reflex:

- MCFA's ten-lane limit;
- Python or CoreAudio merely because MCFA uses them;
- live audio constraints into offline MIDI jobs;
- claims that simulation is physical measurement;
- a conventional song-arranger model; or
- generic repository scaffolding before the human and receiving agent agree on
  the first implementation goal.

## Recommended next conversation

The receiving agent should inspect MCFA `codex/v2-beta` and the existing phonond
repository, then present the human with a small decision manifest before writing
project code. The first decisions should be:

1. the exact reusable entropy/capture interface owned by phonond or a shared
   Eshkol library;
2. which entropy origins qualify for each of the three projects;
3. the first narrow output to prove for each project;
4. the Vocaloid import/export contract for Aleatori; and
5. the offline object-routing representation for MEAT PROXY.

The human thinks aloud while designing. Discussion is not authorization to build.
Ask clarifying questions, propose explicit goals, and distinguish approved
requirements from earlier assistant suggestions.
