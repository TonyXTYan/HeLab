# RGA visualiser

Small, dependency-free parser and interactive spectrum viewer for Stanford
Research Systems RGASoft `.rgadata` files.

The comparison application uses the same Python virtual environment and
Plotly/PyQt dependencies as HeLab. It does not require a separate environment.

The binary layout is not a published interchange format. The parser was
reverse-engineered from the RGASoft 0.24 file used for this example and checks
the magic header, embedded JSON configuration, scan sizes, and record bounds
before accepting a file.

## Run

### Compare files interactively

Activate the HeLab environment, then launch the comparison window:

```bash
source .venv/bin/activate
python -m side_projects.rga_visualiser.rgadata_compare
```

You can optionally provide the initial folder:

```bash
python -m side_projects.rga_visualiser.rgadata_compare /path/to/RGAData
```

If no folder is given, the window (and the **Open folder…** dialog) defaults to
`/Volumes/100.123.123.201-1/Users/helium/Documents/RGAData` when that network
share is mounted.

Use **Open folder…** to list `.rgadata` files directly inside a folder. Tick
files to add them to the Plotly graph. Highlight a file to choose one scan, the
mean of every scan, or the mean of a checked subset. Normalisation is applied
independently to each displayed trace when enabled.

### Generate one standalone visualisation

```bash
python side_projects/rga_visualiser/rga_visualiser.py \
  /path/to/input.rgadata \
  --output /path/to/rga-spectrum.html
```

Then open the generated HTML file in a browser. The viewer embeds the scan data
but loads D3 7.9.0 from jsDelivr, so the browser needs network access when the
page is opened.

For machine-readable output:

```bash
python side_projects/rga_visualiser/rga_visualiser.py \
  /path/to/input.rgadata \
  --json /path/to/rga-spectrum.json
```

## Included example

`20260817-rga-spectrum.html` is the standalone version of the visualisation
created from `20260817.rgadata`. The original binary data file is not copied
into the repository.
