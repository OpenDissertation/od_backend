import pytest

from od_backend.session_data import add


@pytest.mark.parametrize(
    ("lhs", "rhs", "expected"),
    [
        (0, 0, 0),
        (1, 2, 3),
        (-2, 6, 4),
    ],
)
def test_add(lhs: int, rhs: int, expected: int) -> None:
    assert add(lhs, rhs) == expected
