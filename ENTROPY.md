# MCFA Entropy Stamps

## Project anchor

- Created: 2026-08-14
- Source: one 128-bit draw from Python `random.SystemRandom`
- Stamp: `6508e891905c808836b63804d30093d3`

This is the project's permanent entropy anchor. Do not regenerate or replace it;
it identifies this project history rather than controlling synthesis.

## Performance stamps

Every MCFA engine run independently draws a new 128-bit `entropy_stamp` from
`random.SystemRandom`. Live and final saved status expose that stamp, providing a
verifiable identity for the run. A performance stamp does not alter the sound by
itself.

Individual lanes may additionally use `"random_seed":"system"`. That separate
draw seeds the lane's fast local generators for noise samples and probability
decisions. Public seeds are recorded as exact JSON-safe hexadecimal strings and
may be supplied again to reproduce the same stochastic stream.
