# The queue kept the handle. The data kept changing.

If three scoreboard entries suddenly contain the last packet's data, inspect
object reuse before changing the DUT checker. Three queue entries can point to
one object.

Scope: SystemVerilog class transactions sent through UVM TLM-1 analysis ports.
All snippets are illustrative fragments, uncompiled and unexecuted. Assume
`uvm_pkg` is imported and UVM macros are included where used. No DUT or complete
testbench is supplied.

## A queue entry is not automatically a snapshot

For a class variable, assignment copies the handle. Pushing that handle into a
queue does not copy the object's fields.

Procedural fragment. Assume `packet` is a class with a 32-bit `data` field:

```systemverilog
packet t;
packet pending[$];

t = new("t");
t.data = 32'h11;
pending.push_back(t);

t.data = 32'h22;
pending.push_back(t);

t.data = 32'h33;
// pending.size() is 2.
// Both pending[0].data and pending[1].data are now 32'h33.
```

No threads. No clock race. No UVM needed for this failure.

Reassigning `t` to a new object is different from changing `t.data`. Reassignment
changes which object `t` names; existing queue entries still name the old object.
Setting `t = null` also leaves those other handles intact.

Keep that distinction visible when reading monitor code. The important question
is where allocation happens relative to publication and the next field update.

## `write()` returning does not mean the transaction is finished

An analysis port calls each connected subscriber's `write(t)` function. For a
class transaction, each receives a handle to the same object. The port does not
make subscriber-specific copies. See Accellera's
[UVM 1.2 User's Guide, section 2.3.3](https://www.accellera.org/images/downloads/standards/uvm/uvm_users_guide_1.2.pdf).

The callbacks execute without consuming simulation time. A callback can still
retain the handle for processing much later. Function return says the callback
returned. It says nothing about the last future reader of that object.

If the subscriber reads scalar fields, samples coverage immediately, and retains
no handle, producer reuse after return can be safe. That is a specific lifetime
contract. Add a deferred checker and the same producer can become unsafe.

Treat incoming analysis transactions as read-only. Do not fix byte order, clear
status, or attach mutable checking results directly to the received object.
Accellera's [analysis implementation](https://github.com/accellera-official/uvm-core/blob/main/src/tlm1/uvm_analysis_port.svh)
explicitly requires subscribers to leave the incoming value unchanged.

If adding a coverage subscriber changes scoreboard results, inspect writes to
the shared transaction. Changing subscriber order is not a repair.

## Put the snapshot boundary before the next mutation

Two useful ownership contracts. Pick one deliberately.

**Publish a fresh object and freeze it.** A monitor allocates one complete object
per observed transaction. After publication, every holder treats its fields and
owned children as immutable. Subscribers may retain handles under that contract.

Monitor task-body fragment; `collect_complete_packet` is a placeholder task that
fills the supplied object from correctly sampled interface activity:

```systemverilog
packet t;
forever begin
  t = packet::type_id::create("observed", this);
  collect_complete_packet(t);
  ap.write(t);
  // Next iteration allocates again. Do not refill this published object.
end
```

Allocate fresh mutable children too. A new packet wrapped around a reused header
still shares that header with older packets.

**Copy at subscriber ingress.** A subscriber that retains data takes a private
snapshot inside `write()`, before the producer can resume and reuse its object.
Useful when producer immutability cannot be guaranteed.

Scoreboard member fragments. `packet` must implement the copy behavior discussed
below:

```systemverilog
packet pending[$];

function void write(packet t);
  packet saved;
  uvm_object raw;

  if (t == null) begin
    `uvm_fatal("NULL_RX", "Received a null packet")
    return;
  end

  raw = t.clone();
  if (raw == null) begin
    `uvm_fatal("CLONE", "Packet clone returned null")
    return;
  end
  if (!$cast(saved, raw)) begin
    `uvm_fatal("CLONE_TYPE", "Clone is not compatible with packet")
    return;
  end
  pending.push_back(saved);
endfunction
```

`$cast` checks handle type compatibility. It does not copy anything. A successful
cast does not prove the fields were copied correctly either.

Cloning once in the producer can isolate a reusable collection object from its
published copy. All subscribers still share that published copy. A subscriber
that needs to mutate it must take another private copy.

## An analysis FIFO buys time, not independence

`uvm_tlm_analysis_fifo #(packet)` stores packet handles. In Accellera's
[FIFO implementation](https://github.com/accellera-official/uvm-core/blob/main/src/tlm1/uvm_tlm_fifos.svh),
analysis `write()` forwards to `try_put()`, which stores `t` in a typed mailbox.
There is no clone on this path.

Hypothetical sequence with a reusable producer object `H` and a delayed consumer:

```text
producer fills H with A; writes H     FIFO: [H]
producer fills H with B; writes H     FIFO: [H, H]
producer fills H with C; writes H     FIFO: [H, H, H]
consumer gets first entry            reads C
```

The FIFO preserved insertion order. The object did not preserve its old value.

Cloning after `fifo.get(t)` cannot recover A. By then A has already been
overwritten. Put the copy in a subscriber or adapter before FIFO insertion, or
use a producer that publishes immutable objects.

Also check the rate mismatch. An analysis FIFO is unbounded. A consumer that
never keeps up can accumulate entries without blocking the monitor. Track
backlog separately from whether values were preserved.

## `clone()` only knows what the copy implementation knows

The default `uvm_object::clone()` calls `create()` and then `copy()`. Custom
fields need field automation or a correct `do_copy()` implementation. Merely
registering a type with `uvm_object_utils` does not describe its fields. See
Accellera's [object implementation](https://github.com/accellera-official/uvm-core/blob/main/src/base/uvm_object.svh)
and [copier implementation](https://github.com/accellera-official/uvm-core/blob/main/src/base/uvm_copier.svh).

For a hand-written copy hook, call `super.do_copy(rhs)`, check the source type,
and explicitly handle each owned field. Keep fields handled manually out of
field automation to avoid two competing copy definitions.

Suppose `packet` contains these members:

```systemverilog
logic [31:0] data;
byte unsigned bytes[];
header hdr;                 // nullable UVM object with its own copy implementation
```

The assignments have different consequences:

```systemverilog
data  = rhs_packet.data;    // copies the packed value
bytes = rhs_packet.bytes;   // copies the array's byte values
hdr   = rhs_packet.hdr;     // aliases a class object: not a private header
```

For this example, `hdr` is owned mutable transaction data. Replace that last
assignment with a clone and handle null explicitly. Fragment inside a
`do_copy()` hook, after checking/casting `rhs` into `rhs_packet`:

```systemverilog
uvm_object raw_header;      // declare at the start of the function body

if (rhs_packet.hdr == null) begin
  hdr = null;
end else begin
  raw_header = rhs_packet.hdr.clone();
  if (raw_header == null) begin
    `uvm_fatal("HDR_CLONE", "Header clone returned null")
    return;
  end
  if (!$cast(hdr, raw_header)) begin
    `uvm_fatal("HDR_TYPE", "Cloned header has an incompatible type")
    return;
  end
end
```

The null branch matters when copying into an existing destination: a null source
header must clear an old destination header, rather than leave stale data.

A dynamic array of class handles is another trap. Array assignment copies its
elements, but those elements are handles. Copying a byte array and copying an
array of header objects need different reasoning.

Do not blindly clone every member. A shared immutable configuration object may
intentionally stay shared. Virtual interfaces and component handles are not
packet payload to duplicate. Decide ownership per member. These fragments assume
an acyclic ownership tree; object graphs with cycles or intentionally shared
children need an explicit policy for preserving those relationships.

## Debug identity as well as data

Useful checks when delayed comparisons disagree with publication logs:

- Log `get_inst_id()` and selected payload fields at publication and consumption.
  Several entries with one instance ID suggest reuse; they do not alone prove
  an error if sharing was intentional. Do not confuse this ID with a protocol
  tag. [UVM defines it as object identity](https://github.com/accellera-official/uvm-core/blob/main/src/base/uvm_object.svh).
- Inspect children too. Different packet IDs with one mutable header ID can
  explain why only header comparisons fail.
- Delay consumption deliberately. Publish distinct A, B, and C values, then
  check all three. Immediate comparison can hide a retention bug.
- If a clone looks empty, inspect copy participation before blaming the cast.
- If the copy initially looks correct, mutate the source and check again.
  Include a nested field, not just the top-level payload.

Do not validate a copy only with `compare()` if copy and compare omit the same
field. Check named fields directly for the ownership diagnostic. Otherwise two
incomplete hooks can agree that everything is fine.

## Things copying will not fix

- A monitor that sampled the wrong clock region faithfully clones the wrong
  observation. See the existing [sampling notes](../ready-valid-handshake/assertions.md#sampling-and-reset-traps).
- Expected and actual paths built from the same observation can agree while
  checking the wrong thing. Copying separates storage, not evidence.
- A private transaction from before reset remains a pre-reset transaction.
  Define cancellation or completion policy separately. Clearing a pending queue
  does not cancel work already removed by a consumer. If using epoch tags, capture
  the epoch with the observation and reject stale work at the checking boundary.
- An object pool needs a last-reader release rule. Returning from `ap.write()`
  is insufficient when any subscriber retains handles. Start with fresh objects;
  add pooling only with an explicit lifetime protocol and a measured reason.

The question to leave beside any deferred queue: **who can still change the
object after this line?** Include every mutable object reachable through it.

Evidence boundary: the UVM behavior above was checked against the linked
Accellera guide and reference source. The traces and failure patterns are
reasoned examples, not observed simulator results. The snippets have not been
compiled or simulated; they are patterns to adapt and review in a real bench.
