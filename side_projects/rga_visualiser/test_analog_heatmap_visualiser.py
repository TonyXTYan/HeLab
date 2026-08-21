"""Focused tests for the automated analogue RGA heat-map visualiser."""

from datetime import datetime
from pathlib import Path

import pytest

from side_projects.rga_visualiser.analog_heatmap_visualiser import (
    HeatmapData,
    build_figure,
    discover_analog_files,
    high_end_log_colorscale,
    load_heatmap_data,
    parse_analog_timestamp,
    transformed_values,
)
from side_projects.rga_visualiser.rga_visualiser import RGAData, Scan


def sample_heatmap_data() -> HeatmapData:
    return HeatmapData(
        masses=(1.0, 2.0, 3.0),
        times=(datetime(2026, 8, 20, 12, 0), datetime(2026, 8, 20, 12, 1)),
        values=((1e-10, 0.0, 1e-8), (1e-9, -1e-12, 1e-5)),
        source_files=2,
    )


def test_parse_analog_timestamp_includes_milliseconds() -> None:
    timestamp = parse_analog_timestamp(Path("Analog-20260820-122531-053.rgadata"))
    assert timestamp == datetime(2026, 8, 20, 12, 25, 31, 53000)


def test_parse_analog_timestamp_rejects_other_names() -> None:
    with pytest.raises(ValueError, match="does not contain"):
        parse_analog_timestamp(Path("manual.rgadata"))


def test_discover_analog_files_filters_and_sorts(tmp_path: Path) -> None:
    later = tmp_path / "Analog-20260820-122531-053.rgadata"
    earlier = tmp_path / "Analog-20260819-122531-053.rgadata"
    later.write_bytes(b"")
    earlier.write_bytes(b"")
    (tmp_path / "manual.rgadata").write_bytes(b"")
    (tmp_path / "Analog-20260821-122531-053.rgaview").write_bytes(b"")
    assert discover_analog_files(tmp_path) == [earlier, later]


def test_load_limit_returns_exact_newest_scans(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    paths = [
        Path("Analog-20260819-120000-000.rgadata"),
        Path("Analog-20260820-120000-000.rgadata"),
    ]
    parsed_paths: list[Path] = []

    def fake_parse(path: Path) -> RGAData:
        parsed_paths.append(path)
        return RGAData(
            metadata={},
            masses=(1.0, 2.0),
            scans=tuple(
                Scan(0, float(index), (float(index), float(index + 1)))
                for index in range(4)
            ),
        )

    monkeypatch.setattr(
        "side_projects.rga_visualiser.analog_heatmap_visualiser.parse_rgadata",
        fake_parse,
    )
    data = load_heatmap_data(paths, max_scans=3)

    assert parsed_paths == [paths[-1]]
    assert len(data.times) == 3
    assert data.times[0] == datetime(2026, 8, 20, 12, 0, 1)
    assert data.source_files == 1


def test_log_transform_omits_non_positive_values() -> None:
    transformed = transformed_values(sample_heatmap_data().values, True)
    assert transformed[0] == (-10.0, None, -8.0)
    assert transformed[1] == (-9.0, None, -5.0)


def test_log_colorscale_expands_the_top_four_decades() -> None:
    scale = high_end_log_colorscale(((-10.0, -9.0), (-8.0, -5.0)))
    assert not isinstance(scale, str)
    assert scale[0] == [0.0, "#440154"]
    assert scale[1][0] == pytest.approx(1.0 / 5.0)
    assert scale[1][1] == "#482878"
    assert scale[-1] == [1.0, "#fde725"]


def test_log_colorscale_keeps_normal_viridis_within_four_decades() -> None:
    assert high_end_log_colorscale(((-10.0, -9.0), (-7.0, -6.0))) == "Viridis"


def test_heatmap_uses_mass_horizontal_and_time_vertical() -> None:
    figure = build_figure(sample_heatmap_data(), surface=False, log_colour=True)
    trace = figure.data[0]
    assert trace.type == "heatmap"
    assert tuple(trace.x) == (1.0, 2.0, 3.0)
    assert tuple(trace.y) == (
        "2026-08-20 12:00:00.000",
        "2026-08-20 12:01:00.000",
    )
    assert figure.layout.xaxis.title.text == "Mass-to-charge ratio (amu/e)"
    assert figure.data[0].colorscale[1][0] == pytest.approx(1.0 / 5.0)
    assert [annotation.text for annotation in figure.layout.annotations] == [
        "H2 (2)",
        "He3 (3)",
    ]
    assert not figure.layout.shapes


def test_surface_and_top_down_camera() -> None:
    figure = build_figure(
        sample_heatmap_data(), surface=True, log_colour=False, top_down=True
    )
    assert figure.data[0].type == "surface"
    assert len(figure.data) == 1
    assert figure.layout.scene.camera.projection.type == "orthographic"
    assert figure.layout.scene.camera.eye.z == 2.5
    assert figure.layout.scene.xaxis.tickmode is None
    assert [annotation.text for annotation in figure.layout.scene.annotations] == [
        "H2",
        "He3",
    ]
    assert all(
        annotation.y == "2026-08-20 12:01:00.000"
        for annotation in figure.layout.scene.annotations
    )
    assert all(
        annotation.textangle == -45
        for annotation in figure.layout.scene.annotations
    )


def test_common_gas_labels_can_be_hidden() -> None:
    figure = build_figure(
        sample_heatmap_data(),
        surface=False,
        log_colour=True,
        gas_labels=False,
    )
    assert not figure.layout.shapes
    assert not figure.layout.annotations

    surface = build_figure(
        sample_heatmap_data(),
        surface=True,
        log_colour=True,
        gas_labels=False,
    )
    assert surface.layout.scene.xaxis.tickmode is None
    assert not surface.layout.scene.annotations
