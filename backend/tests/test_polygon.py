import pytest
from pydantic import ValidationError

from app.schemas import Settings
from app.rules import inside


def test_concave_zone_with_disjoint_collinear_edges_round_trips():
    points = [
        [0, 0],
        [0.25, 0],
        [0.25, 0.25],
        [0.75, 0.25],
        [0.75, 0],
        [1, 0],
        [1, 1],
        [0, 1],
    ]
    settings = Settings(enable_intrusion=True, zone_polygon=points)
    polygon = Settings.model_validate_json(settings.model_dump_json()).zone_polygon
    assert inside((0.5, 0.5), polygon)
    assert not inside((0.5, 0.1), polygon)


@pytest.mark.parametrize(
    "points",
    [
        [[0, 0], [1, 1], [0, 1], [0.8, 0]],  # Crossing with nonzero signed area.
        [
            [0, 0],
            [1, 0],
            [1, 1],
            [0.5, 0],
            [0, 1],
        ],  # Nonadjacent vertex touches an edge.
        [
            [0, 0],
            [0.75, 0],
            [0.75, 0.5],
            [0.25, 0.5],
            [0.25, 0],
            [1, 0],
            [1, 1],
            [0, 1],
        ],  # Overlapping edges.
        [[0, 0], [1, 0], [0.5, 0], [0.5, 1], [0, 1]],  # Adjacent edges backtrack.
        [[0, 0], [1, 0], [1, 1], [0, 0], [0, 1]],  # Repeated vertex.
        [[0, 0], [0.5, 0], [1, 0]],  # Zero area.
        [[0, 0], [1, 1]],  # Too few vertices.
    ],
    ids=[
        "crossing",
        "touching",
        "overlap",
        "backtracking",
        "duplicate",
        "zero-area",
        "too-short",
    ],
)
def test_invalid_polygon_is_rejected(points):
    with pytest.raises(ValidationError):
        Settings(zone_polygon=points)
