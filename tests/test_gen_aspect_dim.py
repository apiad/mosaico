"""aspect_to_dims: pure function from 'W:H' string to (width, height)."""
import pytest

from mosaico.gen import aspect_to_dims


@pytest.mark.parametrize("aspect,expected", [
    ("1:1", (1024, 1024)),
    ("4:3", (1184, 896)),
    ("3:4", (896, 1184)),
    ("3:2", (1248, 832)),
    ("2:3", (832, 1248)),
    ("16:9", (1376, 768)),
    ("9:16", (768, 1376)),
])
def test_aspect_to_dims_table(aspect, expected):
    assert aspect_to_dims(aspect) == expected


def test_aspect_to_dims_outputs_are_multiples_of_32():
    for aspect in ["1:1", "4:3", "3:4", "3:2", "2:3", "16:9", "9:16"]:
        w, h = aspect_to_dims(aspect)
        assert w % 32 == 0, f"{aspect} width {w} not multiple of 32"
        assert h % 32 == 0, f"{aspect} height {h} not multiple of 32"


def test_aspect_to_dims_total_pixels_within_target():
    target = 1024 * 1024
    for aspect in ["1:1", "4:3", "3:4", "3:2", "2:3", "16:9", "9:16"]:
        w, h = aspect_to_dims(aspect)
        assert 0.9 * target <= w * h <= 1.05 * target, (
            f"{aspect} -> {w}x{h} = {w*h} px outside [0.9T, 1.05T]"
        )


def test_aspect_to_dims_rejects_garbage():
    with pytest.raises(ValueError):
        aspect_to_dims("not-an-aspect")
    with pytest.raises(ValueError):
        aspect_to_dims("16x9")  # x not :
    with pytest.raises(ValueError):
        aspect_to_dims("0:1")
    with pytest.raises(ValueError):
        aspect_to_dims("1:0")
