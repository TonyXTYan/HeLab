#!/usr/bin/env python3
"""Parse an SRS RGASoft .rgadata file and build an interactive HTML visualiser."""

from __future__ import annotations

import argparse
import json
import struct
from dataclasses import dataclass
from pathlib import Path
from typing import Any


MAGIC = b"SRS_RGA_DATA_FILE\r\n\x00"
BLOCK_MARKER = struct.pack("<I", 0x12345678)


@dataclass(frozen=True)
class Scan:
    """One spectrum and its elapsed time relative to the first scan."""

    config_index: int
    elapsed_seconds: float
    values: tuple[float, ...]


@dataclass(frozen=True)
class RGAData:
    """Decoded configuration and spectra from an RGASoft data file."""

    metadata: dict[str, Any]
    masses: tuple[float, ...]
    scans: tuple[Scan, ...]

    def as_json_dict(self) -> dict[str, Any]:
        """Return a compact, serialisable representation for the visualiser."""

        return {
            "metadata": self.metadata,
            "masses": self.masses,
            "times": [scan.elapsed_seconds for scan in self.scans],
            "scans": [scan.values for scan in self.scans],
        }


def _read_u32(data: bytes, offset: int) -> int:
    if offset + 4 > len(data):
        raise ValueError(f"Unexpected end of file at byte {offset}")
    return int(struct.unpack_from("<I", data, offset)[0])


def _expected_points(config: dict[str, Any]) -> int:
    start = float(config["startMass"])
    stop = float(config["stopMass"])
    points_per_amu = int(config["pointsPerAmu"])
    return round((stop - start) * points_per_amu) + 1


def parse_rgadata(path: Path) -> RGAData:
    """Decode the RGASoft 0.24 layout observed in SRS RGA data files."""

    raw = path.read_bytes()
    if not raw.startswith(MAGIC):
        raise ValueError(f"{path} is not an SRS RGASoft data file")

    config_marker = raw.find(BLOCK_MARKER, len(MAGIC))
    if config_marker < 0:
        raise ValueError("Configuration block marker was not found")

    config_length = _read_u32(raw, config_marker + 4)
    config_start = config_marker + 8
    config_end = config_start + config_length
    if config_end > len(raw):
        raise ValueError("Configuration block extends beyond the file")

    try:
        metadata = json.loads(raw[config_start:config_end].decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("Configuration block is not valid UTF-8 JSON") from exc
    if not isinstance(metadata, dict):
        raise ValueError("Configuration JSON is not an object")

    configs = metadata.get("cfgs")
    if not isinstance(configs, list) or not configs:
        raise ValueError("Configuration does not contain any scan definitions")
    if not all(isinstance(config, dict) for config in configs):
        raise ValueError("Scan configurations have an unexpected type")

    data_marker = raw.find(BLOCK_MARKER, config_end)
    if data_marker < 0:
        raise ValueError("Spectrum data block marker was not found")

    # The word following the marker is retained by RGASoft but is not required
    # to delimit records. Records begin eight bytes after the marker.
    cursor = data_marker + 8
    scans: list[Scan] = []
    while cursor < len(raw):
        elapsed_seconds = 0.0
        if scans:
            if len(raw) - cursor == 4:
                break  # tolerate a terminal timing word in a live-written file
            elapsed_seconds = _read_u32(raw, cursor) / 1000.0
            cursor += 4

        if cursor + 8 > len(raw):
            raise ValueError(f"Incomplete scan header at byte {cursor}")
        config_index, point_count = struct.unpack_from("<II", raw, cursor)
        cursor += 8
        if config_index >= len(configs):
            raise ValueError(f"Scan references unknown configuration {config_index}")

        config = configs[config_index]
        expected_points = _expected_points(config)
        if point_count != expected_points:
            raise ValueError(
                f"Scan has {point_count} points; configuration expects "
                f"{expected_points}"
            )

        byte_count = point_count * 4
        if cursor + byte_count > len(raw):
            raise ValueError(f"Incomplete scan data at byte {cursor}")
        values = struct.unpack_from(f"<{point_count}f", raw, cursor)
        cursor += byte_count
        scans.append(Scan(config_index, elapsed_seconds, values))

    if not scans:
        raise ValueError("No complete spectra were found")

    first_config = configs[scans[0].config_index]
    start_mass = float(first_config["startMass"])
    points_per_amu = int(first_config["pointsPerAmu"])
    masses = tuple(
        start_mass + index / points_per_amu
        for index in range(len(scans[0].values))
    )
    if any(len(scan.values) != len(masses) for scan in scans):
        raise ValueError("Visualiser currently requires all scans to share one mass grid")

    return RGAData(metadata, masses, tuple(scans))


HTML_TEMPLATE = r'''<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>__TITLE__</title>
<style>
:root {
  color-scheme: light dark;
  --background: light-dark(#ffffff, #181818);
  --foreground: light-dark(#18181b, #f4f4f5);
  --muted: light-dark(#71717a, #a1a1aa);
  --border: light-dark(#d4d4d8, #52525b);
  --popover: light-dark(#ffffff, #27272a);
  --s1: light-dark(#2563eb, #60a5fa);
  --s2: light-dark(#dc2626, #f87171);
  --s3: light-dark(#16a34a, #4ade80);
  --s4: light-dark(#9333ea, #c084fc);
  --s5: light-dark(#d97706, #fbbf24);
  --s6: light-dark(#0891b2, #22d3ee);
}
* { box-sizing: border-box; }
body { background: var(--background); color: var(--foreground); font: 14px system-ui, sans-serif; margin: 0; padding: 24px; }
#rga-visualiser { margin: 0 auto; max-width: 1100px; width: 100%; }
h1 { font-size: 20px; margin: 0 0 3px; }
.subtitle { color: var(--muted); font-size: 12px; margin-bottom: 9px; }
.legend { display: flex; flex-wrap: wrap; gap: 4px 16px; margin: 0 0 7px 74px; }
.legend button { appearance: none; background: transparent; border: 0; color: var(--foreground); cursor: pointer; font: inherit; font-size: 12px; padding: 3px 0; }
.legend button[aria-pressed="false"] { opacity: .35; }
.swatch { display: inline-block; height: 3px; margin-right: 6px; vertical-align: 3px; width: 18px; }
.chart { min-height: 380px; position: relative; width: 100%; }
svg { display: block; width: 100%; }
svg text { fill: var(--foreground); font-size: 12px; }
.axis path, .axis line { stroke: var(--border); }
.grid line { stroke: var(--border); stroke-opacity: .4; }
.grid path { display: none; }
.series { fill: none; stroke-width: 1.5; vector-effect: non-scaling-stroke; }
.tooltip { background: var(--popover); border: 1px solid var(--border); font-size: 12px; line-height: 1.45; padding: 7px 9px; pointer-events: none; position: absolute; z-index: 2; }
.tooltip-row { display: flex; gap: 12px; justify-content: space-between; white-space: nowrap; }
.tooltip-row span:first-child { color: var(--muted); }
.note { color: var(--muted); font-size: 11px; margin-left: 74px; }
@media (max-width: 480px) {
  body { padding: 12px; }
  .legend, .note { margin-left: 0; }
  .chart { min-height: 340px; }
}
</style>
</head>
<body>
<main id="rga-visualiser">
  <h1>__HEADING__</h1>
  <div class="subtitle">__SUBTITLE__</div>
  <div class="legend" aria-label="Toggle scans"></div>
  <div class="chart"></div>
  <div class="note">Logarithmic current scale; non-positive readings are omitted.</div>
</main>
<script src="https://cdn.jsdelivr.net/npm/d3@7.9.0/dist/d3.min.js"></script>
<script>
(() => {
  const raw = __PAYLOAD__;
  const root = document.getElementById("rga-visualiser");
  const palette = ["var(--s1)","var(--s2)","var(--s3)","var(--s4)","var(--s5)","var(--s6)"];
  const series = raw.scans.map((values, index) => ({
    name: `Scan ${index + 1}`,
    time: raw.times[index],
    color: palette[index % palette.length],
    visible: true,
    values: raw.masses.map((x, point) => ({x, y: values[point]}))
  }));
  const legend = d3.select(root).select(".legend");
  series.forEach(item => {
    const button = legend.append("button").attr("type", "button").attr("aria-pressed", "true");
    button.append("span").attr("class", "swatch").style("background", item.color);
    button.append("span").text(`${item.name} (+${item.time.toFixed(1)} s)`);
    button.on("click", () => {
      item.visible = !item.visible;
      button.attr("aria-pressed", String(item.visible));
      draw();
    });
  });
  const chart = d3.select(root).select(".chart");
  const tooltip = chart.append("div").attr("class", "tooltip").attr("role", "tooltip").style("display", "none");

  function interpolate(values, xValue) {
    const index = d3.bisector(point => point.x).left(values, xValue);
    if (index <= 0) return values[0].y;
    if (index >= values.length) return values[values.length - 1].y;
    const a = values[index - 1], b = values[index];
    const fraction = (xValue - a.x) / (b.x - a.x);
    return a.y + fraction * (b.y - a.y);
  }

  function draw() {
    chart.selectAll("svg").remove();
    tooltip.style("display", "none");
    const width = Math.max(320, chart.node().clientWidth);
    const height = width < 480 ? 340 : 390;
    const margin = {top: 10, right: 18, bottom: 48, left: width < 480 ? 66 : 74};
    const plotWidth = width - margin.left - margin.right;
    const plotHeight = height - margin.top - margin.bottom;
    const positive = series.flatMap(item => item.values.filter(point => point.y > 0).map(point => point.y));
    const currentExtent = d3.extent(positive);
    const x = d3.scaleLinear().domain(d3.extent(raw.masses)).range([0, plotWidth]);
    const y = d3.scaleLog().domain([currentExtent[0] / 1.6, currentExtent[1] * 1.6]).nice().range([plotHeight, 0]);
    const svg = chart.append("svg").attr("viewBox", `0 0 ${width} ${height}`).attr("aria-label", "RGA ion current versus mass");
    const plot = svg.append("g").attr("transform", `translate(${margin.left},${margin.top})`);
    plot.append("rect").attr("data-chart-frame", "").attr("width", plotWidth).attr("height", plotHeight).attr("fill", "none").attr("stroke", "var(--border)");
    const yTicks = y.ticks(6);
    plot.append("g").attr("class", "grid").call(d3.axisLeft(y).tickValues(yTicks).tickSize(-plotWidth).tickFormat(""));
    plot.append("g").attr("class", "axis").attr("transform", `translate(0,${plotHeight})`).call(d3.axisBottom(x).ticks(width < 480 ? 4 : 7));
    plot.append("g").attr("class", "axis").call(d3.axisLeft(y).tickValues(yTicks).tickFormat(d3.format(".0e")));
    svg.append("text").attr("class", "axis-title").attr("data-axis", "x").attr("text-anchor", "middle").attr("x", margin.left + plotWidth / 2).attr("y", height - 8).text("Mass-to-charge ratio (amu/e)");
    svg.append("text").attr("class", "axis-title").attr("data-axis", "y").attr("text-anchor", "middle").attr("transform", `translate(15,${margin.top + plotHeight / 2}) rotate(-90)`).text("Ion current (A)");
    const line = d3.line().defined(point => point.y > 0).x(point => x(point.x)).y(point => y(point.y));
    series.forEach(item => plot.append("path").datum(item.values).attr("class", "series").attr("d", line).attr("stroke", item.color).style("display", item.visible ? null : "none"));
    const guide = plot.append("line").attr("data-chart-hover-guide", "").attr("y1", 0).attr("y2", plotHeight).attr("stroke", "var(--foreground)").attr("stroke-opacity", .4).attr("stroke-dasharray", "3,3").style("display", "none");
    const markers = series.map(item => plot.append("circle").attr("data-chart-hover-marker", "").attr("r", 3.5).attr("fill", item.color).attr("stroke", "var(--popover)").attr("stroke-width", 1.5).style("display", "none"));
    plot.append("rect").attr("data-chart-hit", "").attr("data-chart-hover-overlay", "cross-series").attr("width", plotWidth).attr("height", plotHeight).attr("fill", "transparent").style("cursor", "crosshair")
      .on("pointerenter", () => { guide.style("display", null); tooltip.style("display", null); })
      .on("pointerleave", () => { guide.style("display", "none"); markers.forEach(marker => marker.style("display", "none")); tooltip.style("display", "none"); })
      .on("pointermove", function(event) {
        const pointer = d3.pointer(event, this);
        const pixelX = Math.max(0, Math.min(plotWidth, pointer[0]));
        const mass = x.invert(pixelX);
        guide.attr("x1", pixelX).attr("x2", pixelX);
        let rows = `<div class="tooltip-row"><span>Mass</span><strong>${mass.toFixed(2)} amu/e</strong></div>`;
        series.forEach((item, index) => {
          if (!item.visible) { markers[index].style("display", "none"); return; }
          const value = interpolate(item.values, mass);
          if (value > 0) markers[index].attr("cx", pixelX).attr("cy", y(value)).style("display", null);
          rows += `<div class="tooltip-row"><span>${item.name}</span><strong>${d3.format(".3e")(value)} A</strong></div>`;
        });
        tooltip.html(rows);
        const xPosition = margin.left + pixelX;
        const yPosition = margin.top + Math.max(24, Math.min(plotHeight - 24, pointer[1]));
        const flip = xPosition > width - 245;
        tooltip.style("left", `${flip ? xPosition - tooltip.node().offsetWidth - 12 : xPosition + 10}px`).style("top", `${yPosition}px`).style("transform", "translateY(-50%)");
      });
  }
  new ResizeObserver(draw).observe(chart.node());
  draw();
})();
</script>
</body>
</html>
'''


def build_html(data: RGAData, source: Path) -> str:
    """Create a standalone interactive spectrum visualiser."""

    schedule = data.metadata.get("schedule", {})
    start_time = schedule.get("scanStartTime", "unknown start time")
    connection = data.metadata.get("connection", {})
    serial_number = connection.get("deviceSN", "unknown")
    heading = f"RGA mass spectrum — {source.stem}"
    subtitle = (
        f"{len(data.scans)} scans · {data.masses[0]:g}–{data.masses[-1]:g} amu · "
        f"SRS device SN {serial_number} · started {start_time}"
    )
    payload = json.dumps(data.as_json_dict(), separators=(",", ":"), allow_nan=False)
    return (
        HTML_TEMPLATE.replace("__TITLE__", heading)
        .replace("__HEADING__", heading)
        .replace("__SUBTITLE__", subtitle)
        .replace("__PAYLOAD__", payload.replace("</", "<\\/"))
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path, help="RGASoft .rgadata file")
    parser.add_argument("--output", type=Path, help="standalone HTML destination")
    parser.add_argument("--json", type=Path, dest="json_output", help="optional decoded JSON destination")
    args = parser.parse_args()
    if args.output is None and args.json_output is None:
        parser.error("provide --output, --json, or both")

    data = parse_rgadata(args.input)
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(build_html(data, args.input), encoding="utf-8")
        print(args.output)
    if args.json_output is not None:
        args.json_output.parent.mkdir(parents=True, exist_ok=True)
        args.json_output.write_text(
            json.dumps(data.as_json_dict(), indent=2, allow_nan=False) + "\n",
            encoding="utf-8",
        )
        print(args.json_output)


if __name__ == "__main__":
    main()
