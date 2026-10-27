# Controller logging

`ControllerBase` inherits logging methods from `LoggerMixin`. Each controller
keeps its own in-memory log. No logging structure or list of attributes needs to
be declared in a child class.

## Store values during control calculations

Call `self.store(name, value)` for each signal you want to record, including local
variables and controller attributes:

```python
def compute_controls(self, measurements_dict):
    reference = measurements_dict[self.cname]["power_reference"]
    power = measurements_dict[self.cname]["power"]
    error = reference - power

    self.store("reference_power", reference)
    self.store("error", error)

    return {self.cname: {"power_setpoint": reference}}
```

`store()` adds a value to the pending row; it does not append a row to the log or
write a file. Repeated calls with the same name replace the pending value.
Attributes are not observed automatically: use `self.store("x", self.x)` at the
point in the calculation whose value you want to record.

## Commit a row

At the end of a successful `step()`, after sending controls, `ControllerBase`
calls `self.log(time)`. This appends the pending values and a `time` column to the
log cache, then clears the pending row. Time comes from the measurements
dictionary, or is `None` if unavailable. Reserve the channel name `time` for this
timestamp.

If no values have been stored, no row is appended. Values are not carried forward
to subsequent rows. If different rows contain different signals, the DataFrame
and CSV have missing entries for signals absent from a row.

Mutable values such as arrays are copied when `log()` commits the row, so later
changes do not affect that row. They are not copied by `store()`: if a mutable
value will change before `log()`, pass a copy to `store()`.

When calling `compute_controls()` directly rather than through `step()`, call
`controller.log(time)` explicitly when you want to commit a row.

## Child controllers and hypothetical calculations

`log()` also calls `log(time)` on child loggers held as direct attributes or in
lists or tuples. For example, a hybrid supervisor commits its component
controllers' rows with the same timestamp, even though it calls their
`compute_controls()` methods directly. Each controller still has a separate
cache; `get_log()` combines these caches when retrieving results.

On normal return, `compute_controls_without_updating_state()` restores the
pending values from before the hypothetical calculation, discarding values
stored during it. It does not append a row to the cache.

## Retrieve and write results

After stepping a controller, retrieve its log as a pandas DataFrame or write it
to CSV:

```python
df = battery.get_log()
battery.write_log("battery.csv")
```

Both methods operate on committed rows, not pending values. `write_log()` writes
the combined logs without a DataFrame index, overwriting the destination file;
it does not clear the cache. Logging is kept in memory until written, with no
automatic periodic flushing.

`get_log()` recursively includes subsystem logs and outer-joins them on `time`.
Every signal column is prefixed with its originating controller's `cname`,
including the supervisor's signals. Only `time` remains unprefixed. For example,
`supervisor.get_log()` might return `time`, `supervisor.reference_power`,
`battery.x`, and `wind.error`. Missing subsystem rows appear as missing values.
The supervisor need not store any signals itself to retrieve its subsystem logs.
Calling `battery.get_log()` still retrieves just the battery and its own children.

Controllers with logged signals must have a valid `cname`. Use distinct names to
avoid column collisions; overlapping signal columns raise an error rather than
being overwritten or automatically renamed. Combining nonempty logs also requires
unique timestamps within each log (including at most one missing timestamp).
Duplicate timestamps raise a merge error rather than multiplying rows. Provide
simulation time when combining multi-step logs.

```python
df = supervisor.get_log()
supervisor.write_log("combined.csv")
```

Retrieving or writing a combined log does not change the individual caches.

Arrays occupy a single DataFrame cell and are written as text in CSV, not
expanded into separate columns. For separate columns, store each element with
its own name.
