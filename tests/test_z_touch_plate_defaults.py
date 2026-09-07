from ttc3018_control.application.controller import ApplicationController


def test_new_z_touch_plate_capability_prefills_stated_height(tmp_path) -> None:
    controller = ApplicationController(tmp_path)
    assert controller.save_z_plate_capability(True).accepted
    probe = controller.z_touch_plate_definition
    assert probe is not None
    assert probe.plate_thickness == 19.37
