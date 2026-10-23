# The sum constraint passed. The total is still wrong.

Four unsigned bytes can satisfy `credits.sum() == 100` even when their full
total is 356. The reduction has only eight bits. The carry has already gone by
the time the comparison happens.

Small teaching example: split a budget of 100 credits across four entries.
Each entry is an unsigned byte, so its individual range is 0 through 255.
The intended rule is an ordinary nonnegative total of exactly 100, with no
wraparound.

Illustrative SystemVerilog class, not compiled or simulated here:

```systemverilog
class credit_split;
  rand byte unsigned credits[4];

  constraint total_c {
    credits.sum() == 100;
  }
endclass
```

Looks close to the requirement. It describes a different one.

## The comparison sees the reduced value

For an array reduction, the result type follows the array element type. A
`with` clause changes it to the type of that clause's expression. That's the
rule in [Accellera's SystemVerilog 3.1a LRM, section 4.15.3](https://ece.uah.edu/~gaede/cpe526/SystemVerilog_3.1a.pdf#page=66).
This is the older language reference used for the reduction rule here.

For these unsigned bytes, keeping eight bits gives the mathematical sum modulo
256. Some possible assignments:

| `credits` | Full total | Eight-bit reduction | Original constraint |
| --- | --- | --- | --- |
| `{25, 25, 25, 25}` | 100 | 100 | Satisfied |
| `{200, 100, 56, 0}` | 356 | 100 | Satisfied |
| `{255, 255, 102, 0}` | 612 | 100 | Satisfied |
| `{255, 255, 255, 103}` | 868 | 100 | Satisfied |

These are constructed counterexamples, not randomization output.

The second row is enough to expose the problem:

```text
200 + 100 + 56 + 0 = 356
356 mod 256        = 100
```

The 32-bit literal `100` does not give the reduction a 32-bit accumulator.
The comparison can widen the returned value, but that returned value is already
100. No carry left to recover.

I'd check the expression type before adding another seed. A solver returning
that second row has met the written constraint.

## Widen each contribution before reducing

Replace the constraint block with this one:

```systemverilog
constraint total_c {
  credits.sum() with (int'(item)) == 100;
}
```

`item` is the current array element. Casting it inside `with` makes each
contribution, and therefore the reduction, an `int`.

For this example, that's enough space. The largest possible total is
`4 * 255 = 1020`. An unsigned total needs ten bits; a signed 32-bit `int` can
also hold the entire range. The unsigned byte values remain positive when
converted to `int`.

Moving the cast outside is too late:

```systemverilog
// Still wrong for the intended full total.
constraint total_c {
  int'(credits.sum()) == 100;
}
```

That converts the already reduced result. It doesn't change the type of the
contributions. The reduction rule and the cast syntax are described in the
[same LRM, sections 4.15.3 and 3.14](https://ece.uah.edu/~gaede/cpe526/SystemVerilog_3.1a.pdf).

Don't turn `int'(item)` into a fix to paste everywhere. Here it works because
the elements are unsigned bytes and there are only four. Bigger arrays or
wider elements need a fresh range calculation. Signed elements need a lower
bound too. Changing `byte unsigned` to plain `byte` changes the value range;
it isn't just a spelling change.

## Check the intended total through another path

Checking `credits.sum() == 100` after randomization repeats the same mistake.
It can agree with the constraint while both miss the budget rule.

Module-scope fragment, using `credit_split` with the corrected constraint above.
Also uncompiled and unexecuted:

```systemverilog
initial begin
  credit_split t;
  int unsigned total;

  t = new();
  repeat (100) begin
    if (!t.randomize())
      $fatal(1, "credit_split randomization failed");

    total = 0;
    foreach (t.credits[i])
      total += int'(t.credits[i]);

    if (total != 100)
      $fatal(1, "credits=%p full total=%0d", t.credits, total);
  end
end
```

The explicit loop keeps a sufficiently wide running total. It checks the
meaning of the budget without calling the reduction under investigation.
This is a stimulus check before driving anything, not evidence that a DUT
processed the credits correctly.

A random loop might happen to return only valid full totals even with the bad
constraint. Keep the deterministic counterexample as a separate diagnostic:
assign `{200, 100, 56, 0}` in a procedural test, then compare the narrow
reduction with the loop's total. That exposes the width without depending on
what a solver chooses.

Another useful boundary: replace the target with 300. A four-byte split can
represent a full total of 300, but the original eight-bit reduction cannot
return 300. The corrected constraint can represent that requirement. Same
width error, now showing up as a solve failure rather than unwanted solutions.

The bit to keep beside this constraint: **what type holds the total before
the equality is evaluated?** Counting array entries doesn't answer that.

Validation: the four table rows and the possible wrapped totals were checked
with Python 3.12.3 in this workspace. That checks the arithmetic model, not
SystemVerilog expression evaluation or constraint solving. No HDL simulator
was available on PATH; the SystemVerilog fragments remain uncompiled and
unsimulated.
