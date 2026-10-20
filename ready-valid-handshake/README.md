# Ready/valid under backpressure

Count a transfer only at a rising clock edge with both `valid` and `ready`
asserted. A beat sitting on the bus for five stalled cycles is still one beat.

Scope: one clock domain, in-order beats, no cancellation outside reset. Payload
means data plus every sideband belonging to that beat. This contract uses the
AXI-style rule that an offered beat stays present until accepted. Other
interfaces can define different contracts; check before reusing the checker.

Arm specifies the handshake, source persistence, and the rule that the source
must not wait for `ready` before asserting `valid`. The receiver may wait for
`valid`. See [IHI 0022H, A3.2.1 and A3.3.1](https://developer.arm.com/-/media/Arm%20Developer%20Community/PDF/IHI0022H_amba_axi_protocol_spec.pdf).

- [Assertions and sampling](assertions.md)
- [Scoreboard, stimulus, and debug](scoreboard-and-debug.md)
- [Executable buffer model](examples/elastic_buffer.py)

## Four sampled states

| `valid` | `ready` | Meaning at this edge |
| --- | --- | --- |
| 0 | 0 | No offer, no transfer |
| 0 | 1 | Receiver has capacity, no transfer |
| 1 | 0 | Offered beat is stalled |
| 1 | 1 | Exactly one beat transfers |

Continuous `valid=1, ready=1` means one transfer on **every** edge. No rising
edge on `valid` is needed between beats. Equal payload values on consecutive
transfers are also legal; payload changes cannot be used as a transfer counter.

If edge `n` sees `valid && !ready`, edge `n+1` must still see `valid` and the
same payload, unless reset has aborted the offer. This includes the edge where
`ready` finally becomes high. After a transfer the source may immediately
present the next beat, or lower `valid`.

## One-entry elastic buffer

Teaching design. One stored beat, registered forward data path, combinational
backward ready path. No empty-buffer bypass. Reset discards the stored beat.

Signals at the input use `s_*`; output signals use `m_*`.

```text
m_valid = full
m_data  = data_q
s_ready = !full || m_ready

push = s_valid && s_ready
pop  = m_valid && m_ready
```

When full, accepting another beat is safe only if the current beat leaves on
the same edge. When empty, an input beat cannot leave immediately because
`m_valid` is still low at that edge.

| `push` | `pop` | State after edge |
| --- | --- | --- |
| 0 | 0 | Hold state |
| 1 | 0 | Store input; become full |
| 0 | 1 | Become empty |
| 1 | 1 | Output old beat; store new beat; stay full |

Useful state equation outside reset:

```text
occupancy_next = occupancy + int(push) - int(pop)
0 <= occupancy_next <= 1
```

The simultaneous case is the one to inspect first. Two independent assignments
to `full`, with a later `if (pop) full <= 0`, can drop a replacement beat.

Illustrative RTL, not compiled in this workspace:

```systemverilog
module elastic_buffer #(parameter int W = 32) (
  input  logic         clk,
  input  logic         rst_n,
  input  logic         s_valid,
  output logic         s_ready,
  input  logic [W-1:0] s_data,
  output logic         m_valid,
  input  logic         m_ready,
  output logic [W-1:0] m_data
);
  logic full;
  logic [W-1:0] data_q;

  assign s_ready = !full || m_ready;
  assign m_valid = full;
  assign m_data  = data_q;

  always_ff @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin
      full <= 1'b0;
    end else if (s_ready) begin
      full <= s_valid;
      if (s_valid)
        data_q <= s_data;
    end
  end
endmodule
```

`s_ready` is also an update enable here. If low, the current output is stalled
and both registers hold. If high, either replace the old beat with a valid
input or leave the buffer empty. `data_q` need not be reset because `full=0`
makes its contents invalid. This does not apply if the design specification
requires a defined idle data value.

This block alone is not an AXI register slice: `m_ready -> s_ready` is a
combinational input-to-output path. AXI forbids such paths at its interfaces
([IHI 0022H, A3.1.1](https://developer.arm.com/-/media/Arm%20Developer%20Community/PDF/IHI0022H_amba_axi_protocol_spec.pdf)).
Registering ready changes the capacity requirement. Account for beats accepted
before the upstream source sees backpressure; extra storage or a different
acceptance policy is needed. Do not just add a register to this equation.

## Worked trace

All values below are sampled just before each rising edge. `full` and `m_data`
describe the old state. This is an illustrative trace, also exercised by the
Python model. A dash means the payload is invalid.

| Edge | `rst_n` | `full` | Input | `s_ready` | Output | `m_ready` | Action |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 0 | 0 | — | — | — | — | 0 | Reset |
| 1 | 1 | 0 | A | 1 | — | 0 | Push A |
| 2 | 1 | 1 | B | 0 | A | 0 | Hold A and B |
| 3 | 1 | 1 | B | 0 | A | 0 | Hold A and B |
| 4 | 1 | 1 | B | 1 | A | 1 | Pop A, push B |
| 5 | 1 | 1 | C | 1 | B | 1 | Pop B, push C |
| 6 | 0 | — | — | — | — | 0 | Reset discards C |
| 7 | 1 | 0 | D | 1 | — | 1 | Push D; no bypass |
| 8 | 1 | 1 | — | 1 | D | 1 | Pop D |
| 9 | 1 | 0 | — | 1 | — | 1 | Idle |

At edge 4 the output is A, not B. The input and output interfaces transfer
different beats on the same edge. Updating the scoreboard with the new input
before checking the old output can hide a replacement bug.

Reset policy here is local: no transfers are counted during reset and pending
expectations are flushed. This example does not define whole-system recovery
of outstanding AXI transactions. Reset rows omit interface observations. The
Python model applies reset at its cycle boundary; asynchronous RTL can already
have cleared `full` before that edge.

## Latency and throughput

An input accepted at edge `n` becomes eligible for output transfer at `n+1`.
That is the minimum latency for this implementation. Backpressure can extend
latency without bound unless the environment has a progress requirement.

After filling, the buffer can transfer one beat per edge through simultaneous
push and pop. Replacing `s_ready` with `!full` prevents replacement and reduces
continuous traffic to one output transfer every two edges. Data can remain
correct while throughput is wrong.

## Executable check

From the repository root:

```bash
python3 ready-valid-handshake/examples/elastic_buffer.py
```

The model checks the trace above and seeded random traffic against an independent
queue. It also requires detection of two deliberately broken models: clearing
`full` after a replacement, and overwriting a stalled output. See the script
for the exact checks. The queue checks output offers and transfers; an additional
internal-state check compares `full` with queue occupancy after each update.
This exercises the Python model and checker, not the RTL.

Observed run:

```text
PASS directed: 10 cycles, 4 pushes, 3 pops, 2 reset edges
PASS random seed=2745: 5003 cycles, 2528 pushes, 2430 pops, 107 reset edges
DETECTED drop-replacement: cycle 4: occupancy mismatch after edge
DETECTED overwrite-stalled: cycle 3: stalled output changed
```

Push and pop totals differ because reset discards accepted beats. The checker
flushes its expected queue on reset; it still requires an empty queue after the
final drain.

Validation: Python 3.12.3 used in this workspace. SystemVerilog simulation and
assertion execution were unavailable; the RTL and SVA snippets remain uncompiled.
