# An implication left half the stimulus undefined

`is_write -> strobe != 0` rejects writes with a zero strobe. It says nothing
about which strobes a read may use.

For this teaching command, `is_write` is one bit and `strobe` is a four-bit
byte-enable mask. The chosen interface rule is:

| Command | `strobe` | Intended legality |
| --- | --- | --- |
| Read (`is_write == 0`) | `0000` | Legal |
| Read | `0001` through `1111` | Illegal |
| Write (`is_write == 1`) | `0000` | Illegal |
| Write | `0001` through `1111` | Legal |

Partial writes are allowed. Reads must carry zero. These are assumptions for
this example, not universal rules for a bus with strobes.

Illustrative SystemVerilog examples below; not compiled or simulated.

```systemverilog
class command;
  rand bit       is_write;
  rand bit [3:0] strobe;

  constraint strobe_c {
    is_write -> (strobe != 4'b0000);
  }
endclass
```

The read `{is_write=0, strobe=4'b0101}` meets this constraint. It breaks the
table above. That's a constructed counterexample, not solver output.

## What the arrow actually requires

For Boolean expressions, `A -> B` means `!A || B`. Accellera's older
[SystemVerilog 3.1a LRM, section 12.4.5](https://ece.uah.edu/~gaede/cpe526/SystemVerilog_3.1a.pdf)
gives this equivalence. Here `A` is `is_write`, and `B` is `strobe != 0`.

| `is_write` | `strobe != 0` | `!is_write || (strobe != 0)` |
| --- | --- | --- |
| 0 | 0 | True |
| 0 | 1 | True |
| 1 | 0 | False |
| 1 | 1 | True |

Both read rows survive. The missing rule concerns allowed values; the `bit`
fields still hold ordinary two-state values, not X.

Also, the arrow doesn't mean “choose `is_write`, then assign `strobe`.” It's
a relation between the values in a solution. With only this constraint,
forcing `strobe == 0` forces `is_write == 0`. Forcing a nonzero strobe leaves
either command kind legal.

That last part matters: a nonzero strobe does **not** imply a write under the
original constraint. Adding `(strobe != 0) -> is_write` adds the converse and
removes legal combinations from that original relation.

## Give the read case its own rule

Replace the constraint block with:

```systemverilog
constraint strobe_c {
  if (is_write)
    strobe != 4'b0000;
  else
    strobe == 4'b0000;
}
```

The `else` supplies the read requirement. An `if` without it would leave the
same gap. Conditional constraints require the selected branch's expressions
to hold; they don't procedurally assign fields. See sections 12.4.5 and 12.4.6
in the LRM above, also clarified in Accellera's
[chapter 12 review](https://accellera.org/images/eda/sv-ec/1710.html).

Two implications express the same policy:

```systemverilog
constraint strobe_c {
  is_write    -> (strobe != 4'b0000);
  (!is_write) -> (strobe == 4'b0000);
}
```

Use either replacement, not all three blocks. I'd use the branches here;
the two rows of the requirement are easier to spot.

If the interface instead ignores strobes on reads and permits every mask,
the original implication is enough. Then a checker must allow nonzero read
strobes too. Requiring zero would be an extra stimulus restriction. Calling a
field a don't-care needs that interface decision behind it.

## Check the table, including reads

A checker that only rejects zero-strobe writes repeats the original omission.
For the chosen zero-on-read policy, check each command kind explicitly.
This module uses `command` with the corrected constraint block:

```systemverilog
module command_check;
  task automatic check_command(input command t);
    if (t.is_write) begin
      if (t.strobe == 4'b0000)
        $fatal(1, "write has no enabled bytes");
    end else begin
      if (t.strobe != 4'b0000)
        $fatal(1, "read has nonzero strobe: %b", t.strobe);
    end
  endtask

  initial begin
    command t;
    t = new();

    repeat (16) begin
      if (!t.randomize() with { is_write == 0; })
        $fatal(1, "read randomization failed");
      check_command(t);

      if (!t.randomize() with { is_write == 1; })
        $fatal(1, "write randomization failed");
      check_command(t);
    end
  end
endmodule
```

Both command kinds are requested deliberately. A run containing only writes
would never exercise the read check. Within writes, the checker allows every
nonzero mask, including partial ones such as `0001`.

For a deterministic constraint diagnostic, force each of the 32 possible
`{is_write, strobe}` pairs using inline equalities and compare the randomization
status with the first table. With no other constraints or callbacks, the
original block permits 31 pairs; the corrected block permits 16. The 15 removed
pairs are exactly the nonzero-strobe reads. This also catches an accidental
`strobe == 4'b1111` write rule that the checker alone would accept.

Those status checks examine which combinations are possible. The short random
loop doesn't establish that every legal mask can be generated, and neither
check says whether a DUT processed a command correctly.

The question to keep beside an implication: what is allowed when its condition
is false? Sometimes “anything” is the intended answer. Here it wasn't.
