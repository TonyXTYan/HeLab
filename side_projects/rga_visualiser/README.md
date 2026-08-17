# RGA visualiser

Small, dependency-free parser and interactive spectrum viewer for Stanford
Research Systems RGASoft `.rgadata` files.

The binary layout is not a published interchange format. The parser was
reverse-engineered from the RGASoft 0.24 file used for this example and checks
the magic header, embedded JSON configuration, scan sizes, and record bounds
before accepting a file.

## Run

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
