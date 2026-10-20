# Scoreboard, stimulus, and debug

For the [one-entry buffer](README.md), the scoreboard contains accepted input
beats that have not been accepted at the output. Do not enqueue sequence items
just because the driver intended to send them.

## Process one sampled edge atomically

Pseudocode; `push`, `pop`, and payloads come from the same sampled edge:

```python
if reset_active:
    expected.clear()
else:
    if pop:
        require(expected)              # no empty-buffer bypass in this DUT
        compare(output_payload, expected.popleft())
    if push:
        expected.append(input_payload)
    require(len(expected) <= 1)
```

Pop before push deliberately checks the old queue head. An output transfer
from an empty queue is illegal for this registered buffer, even if an input
transfer occurs at the same edge. A fall-through FIFO needs a different rule.

Two monitors calling two scoreboard callbacks in an arbitrary order can break
this accounting. Collect both interface samples into one cycle record, or use
an explicit coordination scheme before updating expected state.

Within each reset epoch:

```text
accepted_inputs - accepted_outputs = outstanding_beats
```

Counts help detect drops and duplicates. They do not detect substitution or
reordering. Compare complete payloads too. Across reset, either restart these
counters or explicitly account for discarded beats.

At end of test: stop offering new beats, keep the receiver ready, and allow the
pipeline to drain. Fail on an unexpected residual queue. For this model, one
drain edge is sufficient after the final input edge. A permanently stalled sink
does not justify declaring every pending beat lost.

## Stimulus that exposes the boundaries

| Scenario | Intended observation |
| --- | --- |
| Ready high before first offer | Immediate acceptance; no required valid pulse gap |
| Valid high before ready | Source offers independently; payload persists |
| Long output stall with full buffer | Neither stored beat nor pending input changes |
| Stall release with pending input | Pop old beat and push replacement on the same edge |
| Continuous traffic | After filling, one output transfer per edge |
| Source gap while receiver is ready | Last stored beat drains, then output becomes invalid |
| Same payload on consecutive inputs | Two transfers still produce two comparisons |
| Reset with stored and pending beats | Flush expected state; restart source according to reset contract |
| Idle payload toggles | No scoreboard entry while valid is low |

For random stimulus, hold the pending source item until its handshake. Generate
a new candidate only after acceptance or reset. Randomizing payload every cycle
while leaving valid high creates an illegal producer and obscures DUT failures.

Independent Bernoulli choices for ready can miss long stalls. Mix in directed
stall lengths such as 1, 2, 7, and 31 cycles. Run sustained ready-high traffic
separately so that a low-throughput implementation cannot hide in random gaps.

## Useful coverage

- Empty-to-full, full-to-empty, and full-to-full replacement transitions.
- Accepted beats after zero, one, and multiple stalled cycles.
- Input and output stall lengths measured separately.
- Consecutive output transfers, with a target long enough to expose bubbles.
- Reset while empty and while full; reset while the producer has a stalled offer.
- Repeated payload values and payload boundary values.

Sample acceptance-related coverage on handshakes. Do not count a stalled beat
once per cycle as multiple transferred items. Only call an ordering scenario
covered after both handshake signals have actually participated; a test ending
with valid high and ready low has not covered completed valid-before-ready.

A coverage hit says the scenario occurred. Keep assertion results, scoreboard
results, and coverage evidence separate.

## Failure signatures

| Symptom | First checks |
| --- | --- |
| One beat missing after stall release | Simultaneous push/pop update priority; queue callback ordering |
| Newest beat replaces an older stalled beat | Storage write enable includes valid but ignores ready |
| Duplicate output comparisons | Monitor counts valid instead of valid AND ready; source reuses accepted item |
| Stable-data failure only on accepting edge | Payload advanced too early; hold check must include that edge |
| Correct order, half expected throughput | Ready depends only on empty; replacement not supported |
| Hang when receiver waits for valid | Source waits for ready; also check reset and source-data availability |
| Mismatch begins exactly at reset | DUT flush policy and scoreboard epoch policy disagree |
| Mismatch shifts by one beat | Monitor sampled post-update state; input and output sampled inconsistently |

These are hypotheses, not unique diagnoses. For the first failing edge, inspect
the previous sampled beat, current handshakes, expected queue before mutation,
and reset history. Later mismatches may all be consequences of that first error.

## Safety and progress

Stability and queue comparison are safety checks: an observed event must be
legal. Completion needs progress as well. If the sink may stall indefinitely,
eventual delivery cannot be guaranteed by the buffer alone.

In formal verification, assume a legal producer on the buffer input and assert
the buffer's output behavior. If proving delivery, state the sink fairness or
bounded-service assumption explicitly. Do not assume the output stability or
data correctness that the proof is meant to establish.

In simulation, use a watchdog with context: outstanding count, current valid and
ready, time since last handshake, and whether the stimulus is intentionally
stalling. Label a violated latency bound according to its actual contract.
