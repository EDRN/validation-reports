# LTP2, PMRI, and PDAC Report Generators

This package contains only the three Python scripts for generating the LTP2, PMRI, and PDAC validation reports. Raw validation data and generated reports are not included.

## Requirements

- Python 3.10 or newer
- `pandas`

Create a virtual environment and install the dependency:

```sh
python3 -m venv .venv
source .venv/bin/activate
python -m pip install pandas
```

On Windows, activate with `.venv\Scripts\activate`.

## Run

Run commands from this folder and replace the example paths with the recipient's raw CSV and output paths.

LTP2, for one raw validation CSV:

```sh
python generate_ldyt_reports.py "/path/to/LTP2-raw-validation.csv" --output-dir "/path/to/output"
```

PMRI, for one raw validation CSV:

```sh
python generate_pmri_reports.py "/path/to/PMRI-raw-validation.csv"
```

The PMRI reports are written beside the input CSV. To choose their output folder, place the source CSV in that folder or update `output_paths` in `generate_pmri_reports.py` before running.

PDAC, for one or more site CSVs:

```sh
python build_pdac_reports.py --input-files "/path/to/BCM.csv" "/path/to/UPMC.csv" --output-dir "/path/to/output"
```

Run any script with `--help` to see its options. The scripts have defaults from the original workstation; pass input and output paths explicitly so they work on another computer. Inputs must be the corresponding raw validation exports and include the columns expected by that project's script.

## Included code

- `generate_ldyt_reports.py`: LTP2 PHI, validation detail/summary, and pivot reports.
- `generate_pmri_reports.py`: PMRI PHI, validation detail/summary, and pivot reports.
- `build_pdac_reports.py`: PDAC per-site validation, PHI, and pivot reports.

These scripts process potentially sensitive validation data. Share the scripts separately from any raw data or generated reports, and review output files before distribution.