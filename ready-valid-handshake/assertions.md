# Assertions: check across the accepting edge

Assumptions: rising-edge protocol, active-low reset, stable reset release away
from the observation edge. Examples below are module-scope fragments. They
have not been compiled or run in an HDL simulator here.

## Hold the complete beat

```systemverilog
// payload includes data and all sidebands that belong to this beat.
a_hold: assert property (
  @(posedge clk) disable iff (!rst_n)
  (valid && !ready) |=> (valid && $stable(payload))
);
```

For this one-cycle antecedent, `|=>` checks the consequent at the next clock
sample. `$stable(payload)` compares it with the previous sample. `disable iff`
aborts attempts when reset is active; it is an asynchronous disable condition.
These constructs are described in the [Accellera SystemVerilog 3.1a LRM,
sections 17.7.3, 17.11, and 17.11.1](https://ece.uah.edu/~gaede/cpe526/SystemVerilog_3.1a.pdf).
This older LRM is the source used for these basic semantics.

Why the next edge matters:

```text
edge      valid  ready  payload
10        1      0      A
11        1      1      B       <- violation: accepted payload changed
```

At edge 10 an attempt starts. At edge 11 the consequent must hold even though
the receiver is now ready. Rechecking `!ready` in the consequent would miss
this failure. Each stalled edge starts another attempt; a long stall is covered
one adjacent pair at a time.

Using `|-> $stable(payload)` instead would compare the current stall sample to
the preceding edge. That can reject the legal first presentation of a new beat.

Include `last`, byte enables, tags, and other relevant control bits in the
payload bundle. A stable data bus with a changing packet boundary is still a
corrupted beat. Exclude fields explicitly permitted to vary by the interface.

AMD's checker lists separate stable-data and stable-control checks, including
`WDATA`, `WSTRB`, and `WLAST`, as well as valid-persistence checks. See
[PG101 protocol checks](https://docs.amd.com/r/en-US/pg101-axi-protocol-checker/AXI-Protocol-Checks-and-Descriptions).

## Unknown values

```systemverilog
a_controls_known: assert property (
  @(posedge clk) disable iff (!rst_n)
  !$isunknown({valid, ready})
);

a_payload_known: assert property (
  @(posedge clk) disable iff (!rst_n)
  valid |-> !$isunknown(payload)
);
```

The second property is a deliberately strict local policy: every payload bit
must be known whenever offered, even while stalled. Adapt it for legal don't-care
fields or masked byte lanes. Do not classify all unknown idle data as an error.
The known-control check prevents an unknown antecedent from quietly avoiding
the intended hold check. A two-state model cannot exercise X/Z behavior.

## Sampling and reset traps

Concurrent assertions sample ordinary signals in Preponed and evaluate in
Observed. RTL nonblocking updates occur in NBA. Action-block diagnostics should
use `$sampled(...)` when reporting the values used by the assertion. See the
[Accellera LRM, sections 14.3 and 17.3](https://ece.uah.edu/~gaede/cpe526/SystemVerilog_3.1a.pdf).

For handshake accounting, observe the values presented **to** the accepting
edge. Sampling ordinary live signals after NBA can observe the next beat.
A monitor can use a clocking block with input skew `#1step`:

```systemverilog
clocking mon_cb @(posedge clk);
  default input #1step;
  input rst_n, valid, ready, payload;
endclocking
```

Consume `mon_cb` sampled inputs, not the unsampled interface signals. Arrange
driver timing separately, for example by driving on the falling edge in a
simple teaching bench. Do not drive and monitor through racing posedge blocks.

`disable iff (!rst_n)` does not check reset behavior. It disables the other
checks. A requirement that `valid` clears during reset needs its own check,
with a defined observation time and allowed reset-to-output response.
The Python example samples reset at cycle boundaries and cannot check an
asynchronous pulse between edges.

## What these checks leave open

- A source that never raises `valid` can pass the hold property vacuously.
- A held but wrong payload can pass every local stability check.
- A receiver that never raises `ready` can pass these safety checks.
- No property here proves that `valid` generation is independent of `ready`.
- Neither the checker nor the buffer is a clock-domain crossing solution.

Add stimulus that offers data while ready is low, and separately check progress
against a stated service contract. A bounded timeout is a design or environment
requirement, not an automatic consequence of using ready/valid.
