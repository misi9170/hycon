import numpy as np
import pandas as pd
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


class TaggedController(ControllerBase):
    log_attributes = ["x"]

    def __init__(self, interface):
        super().__init__(interface, cname="tagged")
        self.x = 0.0

    def set_controller_parameters(self):
        pass

    def compute_controls(self, measurements_dict):
        e = measurements_dict["ref"] - measurements_dict["y"]
        self.x += e
        self.tag("e", e)
        self.tag("vec", np.array([e, 2 * e]))
        return {"tagged": {"u": e}}


def test_log_attributes_and_tags(tmp_path):
    controller = TaggedController(PassthroughInterface())
    controller.step({"time": 0.0, "ref": 2.0, "y": 1.0})
    controller.step({"time": 1.0, "ref": 5.0, "y": 1.0})

    df = controller.get_log()
    assert list(df.columns) == ["time", "x", "e", "vec"]
    assert df["time"].tolist() == [0.0, 1.0]
    assert df["x"].tolist() == [1.0, 5.0]
    assert df["e"].tolist() == [1.0, 4.0]
    assert np.allclose(df["vec"].iloc[1], [4.0, 8.0])

    filename = tmp_path / "log.csv"
    controller.write_log(filename)
    assert pd.read_csv(filename)["e"].tolist() == [1.0, 4.0]


def test_log_discards_what_if_tags():
    controller = TaggedController(PassthroughInterface())
    controller.compute_controls_without_updating_state({"ref": 100.0, "y": 0.0})
    controller.step({"time": 0.0, "ref": 2.0, "y": 1.0})
    controller.compute_controls_without_updating_state({"ref": 100.0, "y": 0.0})
    controller.step({"time": 1.0, "ref": 2.0, "y": 1.0})

    df = controller.get_log()
    assert df["e"].tolist() == [1.0, 1.0]
    assert df["x"].tolist() == [1.0, 2.0]


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

    # Untagged controllers log nothing
    assert supervisor.get_log().empty
    assert wind.get_log().empty

    df = battery.get_log()
    assert df["time"].tolist() == [0.0, 1.0]
    assert list(df.columns) == ["time", "x", "reference_power", "e", "u"]
    # Logged values come from the real call, not the supervisor's what-if query
    assert np.isclose(
        df["e"].iloc[-1], df["reference_power"].iloc[-1] - test_hercules_dict["battery"]["power"]
    )
    assert np.isclose(
        out["battery"]["power_setpoint"],
        test_hercules_dict["battery"]["power"] + df["u"].iloc[-1],
    )
