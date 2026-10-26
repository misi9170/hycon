import numpy as np
import pandas as pd
import pytest
from hycon.controllers import (
    BatteryController,
    HybridSupervisoryControllerGeneric,
    SolarPassthroughController,
    WindFarmPowerDistributingController,
)
from hycon.controllers.controller_base import ControllerBase
from hycon.interfaces.interface_base import InterfaceBase


class PassthroughInterface(InterfaceBase):
    def __init__(self):
        super().__init__()
        self.dt = 1.0
        self.plant_parameters = {}

    def get_measurements(self, input_dict):
        return dict(input_dict)

    def check_controls(self, controls_dict):
        pass

    def send_controls(self, input_dict, controls_dict):
        return controls_dict


class LoggingController(ControllerBase):
    def __init__(self, interface):
        super().__init__(interface, cname="tagged")
        self.x = 0.0

    def set_controller_parameters(self):
        pass

    def compute_controls(self, measurements_dict):
        e = measurements_dict["ref"] - measurements_dict["y"]
        self.x += e
        self.store("x", self.x)
        self.store("e", e)
        self.store("vec", np.array([e, 2 * e]))
        return {"tagged": {"u": e}}


def test_log_stored_values(tmp_path):
    controller = LoggingController(PassthroughInterface())
    controller.step({"time": 0.0, "ref": 2.0, "y": 1.0})
    controller.step({"time": 1.0, "ref": 5.0, "y": 1.0})

    df = controller.get_log()
    assert list(df.columns) == ["time", "tagged.x", "tagged.e", "tagged.vec"]
    assert df["time"].tolist() == [0.0, 1.0]
    assert df["tagged.x"].tolist() == [1.0, 5.0]
    assert df["tagged.e"].tolist() == [1.0, 4.0]
    assert np.allclose(df["tagged.vec"].iloc[1], [4.0, 8.0])

    filename = tmp_path / "log.csv"
    controller.write_log(filename)
    assert pd.read_csv(filename)["tagged.e"].tolist() == [1.0, 4.0]

    # Attributes alone do not produce rows once the stored values have been consumed.
    controller.x = 100.0
    controller.log(time=2.0)
    assert len(controller.get_log()) == 2


def test_log_discards_what_if_values():
    controller = LoggingController(PassthroughInterface())
    controller.compute_controls_without_updating_state({"ref": 100.0, "y": 0.0})
    controller.step({"time": 0.0, "ref": 2.0, "y": 1.0})
    controller.compute_controls_without_updating_state({"ref": 100.0, "y": 0.0})
    controller.step({"time": 1.0, "ref": 2.0, "y": 1.0})

    df = controller.get_log()
    assert df["tagged.e"].tolist() == [1.0, 1.0]
    assert df["tagged.x"].tolist() == [1.0, 2.0]


def test_log_component_controllers(test_hercules_dict, test_interface_hercules):
    wind = WindFarmPowerDistributingController(test_interface_hercules, "wind_farm")
    solar = SolarPassthroughController(test_interface_hercules, "solar_farm")
    battery = BatteryController(test_interface_hercules, "battery")
    supervisor = HybridSupervisoryControllerGeneric(
        test_interface_hercules,
        controller_parameters={"component_controllers": [wind, solar, battery]},
    )

    for t in [0.0, 1.0]:
        test_hercules_dict["time"] = t
        out = supervisor.step(test_hercules_dict)

    # A supervisor with no stored values still includes its children's logs.
    assert wind.get_log().empty

    df = battery.get_log()
    assert df["time"].tolist() == [0.0, 1.0]
    pd.testing.assert_frame_equal(supervisor.get_log(), df)
    assert list(df.columns) == [
        "time",
        "battery.x",
        "battery.reference_power",
        "battery.e",
        "battery.u",
    ]
    # Logged values come from the real call, not the supervisor's what-if query
    assert np.isclose(
        df["battery.e"].iloc[-1],
        df["battery.reference_power"].iloc[-1] - test_hercules_dict["battery"]["power"],
    )
    assert np.isclose(
        out["battery"]["power_setpoint"],
        test_hercules_dict["battery"]["power"] + df["battery.u"].iloc[-1],
    )


def test_store_replaces_pending_value():
    controller = LoggingController(PassthroughInterface())
    controller.store("e", 1.0)
    controller.store("e", 2.0)
    assert controller.get_log().empty

    controller.log(time=0.0)
    assert controller.get_log().to_dict("records") == [{"time": 0.0, "tagged.e": 2.0}]

    controller.log(time=1.0)
    assert len(controller.get_log()) == 1


def test_get_log_combines_nested_controllers(tmp_path):
    interface = PassthroughInterface()
    supervisor = LoggingController(interface)
    supervisor.cname = "supervisor"
    child = LoggingController(interface)
    child.cname = "battery"
    nested = LoggingController(interface)
    nested.cname = "inner"
    supervisor.components = [child]
    child.subsystem = nested

    supervisor.store("power", 10.0)
    child.store("power", 2.0)
    supervisor.log(time=0.0)
    child.store("power", 3.0)
    nested.store("power", 4.0)
    supervisor.log(time=1.0)
    supervisor.store("power", 20.0)
    supervisor.log(time=2.0)

    expected = pd.DataFrame(
        {
            "time": [0.0, 1.0, 2.0],
            "supervisor.power": [10.0, np.nan, 20.0],
            "battery.power": [2.0, 3.0, np.nan],
            "inner.power": [np.nan, 4.0, np.nan],
        }
    )
    pd.testing.assert_frame_equal(supervisor.get_log(), expected)
    filename = tmp_path / "combined.csv"
    supervisor.write_log(filename)
    pd.testing.assert_frame_equal(pd.read_csv(filename), expected)
    # Retrieving combined results does not modify individual caches.
    assert len(supervisor._log_cache) == 2
    assert list(child.get_log().columns) == ["time", "battery.power", "inner.power"]


def test_get_log_rejects_column_collisions():
    parent = LoggingController(PassthroughInterface())
    parent.child = LoggingController(PassthroughInterface())
    parent.store("power", 1.0)
    parent.child.store("power", 2.0)
    parent.log(time=0.0)
    with pytest.raises(ValueError, match="Duplicate log columns"):
        parent.get_log()


def test_get_log_rejects_ambiguous_timestamps():
    parent = LoggingController(PassthroughInterface())
    parent.child = LoggingController(PassthroughInterface())
    parent.child.cname = "child"
    for _ in range(2):
        parent.store("power", 1.0)
        parent.child.store("power", 2.0)
        parent.log(time=0.0)
    with pytest.raises(pd.errors.MergeError):
        parent.get_log()
