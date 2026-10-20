"""Cycle model and queue checker. Teaching example, not an RTL simulator."""

from collections import deque
from random import Random


class Buffer:
    def __init__(self, bug=None):
        self.full = False
        self.data = None
        self.bug = bug

    def observe(self, ready):
        return not self.full or ready, self.full, self.data

    def tick(self, rst_n, valid, data, ready):
        s_ready, m_valid, _ = self.observe(ready)
        push = valid and s_ready
        pop = m_valid and ready
        if not rst_n:
            self.full = False
        elif s_ready:
            self.full = valid
            if valid:
                self.data = data
        if rst_n and self.bug == "drop-replacement" and push and pop:
            self.full = False
        if rst_n and self.bug == "overwrite-stalled" and valid and not s_ready:
            self.data = data


def check(rows, bug=None):
    dut = Buffer(bug)
    expected = deque()
    input_hold = output_hold = None
    pushes = pops = resets = 0
    for cycle, (rst_n, valid, data, ready) in enumerate(rows):
        s_ready, m_valid, m_data = dut.observe(ready)

        def require(condition, message):
            if not condition:
                raise AssertionError(f"cycle {cycle}: {message}")

        if not rst_n:
            expected.clear()
            input_hold = output_hold = None
            resets += 1
        else:
            if input_hold is not None:
                require(valid and data == input_hold, "illegal source change")
            if output_hold is not None:
                require(m_valid and m_data == output_hold, "stalled output changed")
            if m_valid:
                require(bool(expected), "output offer without queued input")
                require(m_data == expected[0], "output differs from queue head")
            if m_valid and ready:
                require(bool(expected), "unexpected output transfer")
                require(m_data == expected.popleft(), "accepted payload mismatch")
                pops += 1
            if valid and s_ready:
                expected.append(data)
                pushes += 1
            require(len(expected) <= 1, "capacity exceeded")
            input_hold = data if valid and not s_ready else None
            output_hold = m_data if m_valid and not ready else None

        dut.tick(rst_n, valid, data, ready)
        require(int(dut.full) == len(expected), "occupancy mismatch after edge")
    if expected or dut.full:
        raise AssertionError("test ended without draining")
    return len(rows), pushes, pops, resets


def directed_rows():
    # (reset released, source valid, source payload, receiver ready)
    return [
        (False, False, None, False),
        (True, True, "A", False),
        (True, True, "B", False),
        (True, True, "B", False),
        (True, True, "B", True),
        (True, True, "C", True),
        (False, False, None, False),
        (True, True, "D", True),
        (True, False, None, True),
        (True, False, None, True),
    ]


def random_rows(seed=2745, cycles=5000):
    rng = Random(seed)
    rows = [(False, False, None, False)]
    # Track source-side acceptance separately from the model under check.
    occupied = False
    pending = None
    for _ in range(cycles):
        rst_n = rng.random() >= 0.02
        ready = rng.random() < 0.55
        if not rst_n:
            pending = None
            occupied = False
            rows.append((False, False, None, ready))
            continue
        if pending is None and rng.random() < 0.8:
            pending = rng.randrange(256)
        valid = pending is not None
        s_ready = not occupied or ready
        rows.append((True, valid, pending, ready))
        if s_ready:
            occupied = valid
            if valid:
                pending = None
    # Finish any offered input, then drain without using reset to hide residue.
    rows.append((True, pending is not None, pending, True))
    rows.append((True, False, None, True))
    return rows


if __name__ == "__main__":
    for name, rows in [("directed", directed_rows()), ("random seed=2745", random_rows())]:
        cycles, pushes, pops, resets = check(rows)
        print(f"PASS {name}: {cycles} cycles, {pushes} pushes, {pops} pops, {resets} reset edges")
    for bug in ("drop-replacement", "overwrite-stalled"):
        try:
            check(directed_rows(), bug=bug)
        except AssertionError as error:
            print(f"DETECTED {bug}: {error}")
        else:
            raise AssertionError(f"checker missed injected bug: {bug}")
