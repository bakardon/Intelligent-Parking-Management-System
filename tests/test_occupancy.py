"""Occupancy engine: ground-contact points, adjacent spaces, smoothing."""

import numpy as np
import pytest

from src.config import SPACES_PATH
from src.occupancy import (
    AVAILABLE,
    OCCUPIED,
    UNKNOWN,
    ParkingOccupancy,
    get_vehicle_ground_points,
    is_space_occupied,
    load_parking_spaces,
    scale_polygon,
)

# Two adjacent bays side by side, 100 px wide, rows y=100..200.
LEFT = [[0, 100], [100, 100], [100, 200], [0, 200]]
RIGHT = [[100, 100], [200, 100], [200, 200], [100, 200]]
# A bay in the row "behind" (further from the camera), y=20..90.
BEHIND = [[0, 20], [100, 20], [100, 90], [0, 90]]


def car(x1, y1, x2, y2):
    return {"box": (x1, y1, x2, y2), "class": "car", "confidence": 0.9}


def run(engine, frames):
    status = None
    for vehicles in frames:
        status = engine.update(vehicles)
    return status


def test_ground_points_are_on_bottom_edge():
    points = get_vehicle_ground_points((0, 0, 100, 100))
    assert points == [(10, 90), (30, 90), (50, 90), (70, 90), (90, 90)]


def test_point_in_polygon_inclusive_of_edge():
    polygon = np.array(LEFT, dtype=np.int32)
    assert is_space_occupied(polygon, [(50, 150)])
    assert is_space_occupied(polygon, [(100, 150)])  # on the boundary
    assert not is_space_occupied(polygon, [(150, 150)])


def test_tall_box_overlapping_row_behind_only_occupies_its_own_bay():
    # Perspective view: the car's box extends up into the row behind, but
    # its ground contact (90 % height) is in LEFT. Box-overlap logic would
    # wrongly mark BEHIND as occupied too.
    engine = ParkingOccupancy([LEFT, BEHIND], history_length=1, occupied_threshold=1)
    status = engine.update([car(10, 30, 90, 180)])
    assert status["spaces"] == {"P1": True, "P2": False}


def test_vehicle_straddling_two_adjacent_bays_occupies_both():
    engine = ParkingOccupancy([LEFT, RIGHT], history_length=1, occupied_threshold=1)
    status = engine.update([car(50, 100, 150, 180)])
    assert status["occupied"] == 2
    assert status["available"] == 0


def test_vehicle_in_one_bay_does_not_mark_neighbour():
    engine = ParkingOccupancy([LEFT, RIGHT], history_length=1, occupied_threshold=1)
    status = engine.update([car(5, 100, 95, 180)])
    assert status["spaces"] == {"P1": True, "P2": False}


def test_multiple_spaces_counts():
    spaces = [[[x, 100], [x + 50, 100], [x + 50, 200], [x, 200]] for x in range(0, 500, 50)]
    engine = ParkingOccupancy(spaces, history_length=1, occupied_threshold=1)
    status = engine.update([car(5, 100, 45, 180), car(205, 100, 245, 180), car(455, 100, 495, 180)])
    assert (status["capacity"], status["occupied"], status["available"], status["unknown"]) == (10, 3, 7, 0)


def test_spaces_unknown_until_enough_observations():
    engine = ParkingOccupancy([LEFT], history_length=8, occupied_threshold=5)
    for _ in range(4):
        status = engine.update([car(10, 100, 90, 180)])
        assert status["spaces"]["P1"] is None
        assert status["unknown"] == 1
    status = engine.update([car(10, 100, 90, 180)])
    assert status["spaces"]["P1"] is True


def test_smoothing_ignores_brief_detection_gaps():
    engine = ParkingOccupancy([LEFT], history_length=8, occupied_threshold=5)
    parked = [car(10, 100, 90, 180)]
    run(engine, [parked] * 8)
    # The detector misses the car for two frames: still occupied (6/8).
    status = run(engine, [[], []])
    assert status["spaces"]["P1"] is True


def test_smoothing_ignores_passing_vehicle():
    engine = ParkingOccupancy([LEFT], history_length=8, occupied_threshold=5)
    run(engine, [[]] * 8)
    status = run(engine, [[car(10, 100, 90, 180)]] * 3 + [[]])  # 3 frames only
    assert status["spaces"]["P1"] is False


def test_smoothing_switches_after_threshold():
    engine = ParkingOccupancy([LEFT], history_length=8, occupied_threshold=5)
    run(engine, [[]] * 8)
    parked = [car(10, 100, 90, 180)]
    assert run(engine, [parked] * 4)["spaces"]["P1"] is False
    assert run(engine, [parked])["spaces"]["P1"] is True
    # And back: needs 4 empty frames to drop below 5 of 8.
    assert run(engine, [[]] * 3)["spaces"]["P1"] is True
    assert run(engine, [[]])["spaces"]["P1"] is False


def test_reset_makes_spaces_unknown():
    engine = ParkingOccupancy([LEFT], history_length=4, occupied_threshold=2)
    run(engine, [[car(10, 100, 90, 180)]] * 4)
    engine.reset()
    assert engine.space_state(0) == UNKNOWN
    assert engine.status()["unknown"] == 1


def test_stable_space_ids():
    engine = ParkingOccupancy([LEFT, RIGHT], history_length=1, occupied_threshold=1, space_ids=[41, 7])
    status = engine.update([car(110, 100, 190, 180)])
    assert status["spaces"] == {41: False, 7: True}


def test_space_state_values():
    engine = ParkingOccupancy([LEFT, RIGHT], history_length=1, occupied_threshold=1)
    engine.update([car(10, 100, 90, 180)])
    assert engine.space_state(0) == OCCUPIED
    assert engine.space_state(1) == AVAILABLE


def test_invalid_threshold_rejected():
    with pytest.raises(ValueError):
        ParkingOccupancy([LEFT], history_length=3, occupied_threshold=4)


def test_scale_polygon():
    assert scale_polygon([[100, 50]], (200, 100), (400, 200)) == [[200, 100]]
    assert scale_polygon([[100, 50]], None, (400, 200)) == [[100, 50]]


def test_legacy_layout_file_still_loads():
    spaces = load_parking_spaces(SPACES_PATH)
    engine = ParkingOccupancy(spaces)
    status = engine.update([])
    assert status["capacity"] == len(spaces) == 6
    assert list(status["spaces"]) == ["P1", "P2", "P3", "P4", "P5", "P6"]
