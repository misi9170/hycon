import copy

import numpy as np
import pandas as pd


class LoggerMixin:
    """
    Mixin that lets controllers log stored values once per step.

    Store each value to log with ``self.store("name", value)``, including attributes
    (e.g. ``self.store("x", self.x)``) and local variables in compute_controls.

    log() appends one row (time and stored values) to an in-memory cache and then calls log() on
    its sub-loggers: loggers held as attributes, directly or in lists or tuples (e.g. a
    supervisor's component controllers). Use get_log()
    or write_log() to retrieve the results.
    """

    def __init__(self):
        self._log_row = {}
        self._log_cache = []

    def store(self, name, value):
        """
        Store a value for the next logged row.

        Repeated calls with the same name replace the pending value.
        """
        # Copy so that later in-place changes (e.g. to arrays) don't alter logged values
        self.__dict__.setdefault("_log_row", {})[name] = (
            value
            if isinstance(value, (int, float, complex, str, bytes, type(None), np.number, np.bool_))
            else copy.deepcopy(value)
        )

    def log(self, time=None):
        """Append the current stored values to the log cache, then log sub-loggers."""
        row = {"time": time}
        row.update(self.__dict__.get("_log_row", {}))
        # Clear the pending row after committing it to the log cache
        self._log_row = {}
        if len(row) > 1:
            self.__dict__.setdefault("_log_cache", []).append(row)

        for sub_logger in self._sub_loggers():
            sub_logger.log(time)

    def get_log(self):
        """
        Return this logger's and its sub-loggers' logs, outer-joined on time.

        Signal columns are prefixed with the originating controller's cname.
        Combining nonempty logs requires unique timestamps in each log.
        """
        combined = pd.DataFrame(self.__dict__.get("_log_cache", []))
        if not combined.empty:
            prefix = self.cname
            combined = combined.rename(
                columns={name: f"{prefix}.{name}" for name in combined.columns if name != "time"}
            )

        for sub_logger in self._sub_loggers():
            sub_log = sub_logger.get_log()
            if sub_log.empty:
                continue
            if combined.empty:
                combined = sub_log
                continue
            overlap = (set(combined.columns) & set(sub_log.columns)) - {"time"}
            if overlap:
                raise ValueError(f"Duplicate log columns: {sorted(overlap)}. Use distinct cnames.")
            combined = combined.merge(sub_log, on="time", how="outer", validate="one_to_one")
        return combined

    def write_log(self, filename):
        """Write this logger's and its sub-loggers' combined logs to a CSV file."""
        self.get_log().to_csv(filename, index=False)

    def reset_log(self):
        """Reset this logger's and its sub-loggers' logs."""
        self.__dict__["_log_cache"] = []
        for sub_logger in self._sub_loggers():
            sub_logger.reset_log()

    def _sub_loggers(self):
        sub_loggers = []
        for name, v in self.__dict__.items():
            if name in ("_log_row", "_log_cache"):
                continue
            if isinstance(v, LoggerMixin):
                sub_loggers.append(v)
            elif isinstance(v, (list, tuple)):
                sub_loggers.extend(c for c in v if isinstance(c, LoggerMixin))
        return sub_loggers
