import copy

import pandas as pd


class LoggerBase:
    """
    Mixin that lets controllers log tagged values once per step.

    Values are tagged in two ways:
        - Attributes: list attribute names in the class-level ``log_attributes``, e.g.
          ``log_attributes = ["x"]``. These are read when log() is called.
        - Any other value (e.g. a local variable in compute_controls): call
          ``self.tag("name", value)``.

    log() appends one row (time, attributes, tags) to an in-memory cache and then calls log() on
    any controllers held by this one (e.g. a supervisor's component controllers). Use get_log()
    or write_log() to retrieve the results.
    """

    log_attributes = []

    def __init__(self):
        self._log_row = {}
        self._log_cache = []

    def tag(self, name, value):
        """Tag a value to be included in the next logged row."""
        self.__dict__.setdefault("_log_row", {})[name] = value

    def log(self, time=None):
        """Append the current tagged values to the log cache, then log child controllers."""
        row = {"time": time}
        row.update({a: getattr(self, a) for a in self.log_attributes})
        row.update(self.__dict__.get("_log_row", {}))
        self._log_row = {}
        if len(row) > 1:
            # Copy so that later in-place changes (e.g. to arrays) don't alter logged values
            row = {
                k: v if isinstance(v, (int, float, str, type(None))) else copy.deepcopy(v)
                for k, v in row.items()
            }
            self.__dict__.setdefault("_log_cache", []).append(row)

        for child in self._child_loggers():
            child.log(time)

    def get_log(self):
        """Return this controller's logged values as a DataFrame."""
        return pd.DataFrame(self.__dict__.get("_log_cache", []))

    def write_log(self, filename):
        """Write this controller's logged values to a CSV file."""
        self.get_log().to_csv(filename, index=False)

    def _child_loggers(self):
        children = []
        for v in self.__dict__.values():
            if isinstance(v, LoggerBase):
                children.append(v)
            elif isinstance(v, (list, tuple)):
                children.extend(c for c in v if isinstance(c, LoggerBase))
        return children
