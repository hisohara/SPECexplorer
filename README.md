# SPECexplorer

A web application for exploring and analyzing SPEC CPU 2017 benchmark results. Built with FastAPI, htmx, and SQLite.

## Features

- Import and browse SPEC CPU 2017 INT/FP benchmark results
- Filter by benchmark type, socket count, and SKU model
- Interactive charts with Chart.js (min/max/avg, Base/TDP, Base/core views)
- SKU Specifications browser with sortable tables
- TCO Analysis with configurable parameters (memory, licensing, power)

## Prerequisites

- Python 3.8+
- SPEC CPU 2017 result CSV files (downloaded from [spec.org](https://www.spec.org/cpu2017/results/))

## Installation

```bash
git clone git@github.com:hisohara/SPECexplorer.git
cd SPECexplorer
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## Usage

### Start the server

```bash
source .venv/bin/activate
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

The app will be available at http://localhost:8000.

### Import benchmark data

1. Download SPEC CPU 2017 result CSVs from [spec.org](https://www.spec.org/cpu2017/results/).
2. Open the app in your browser.
3. Use the upload form to import INT and/or FP result CSV files.

SKU data is loaded automatically from `SKU.csv` on first startup.

### SKU data

The bundled `SKU.csv` includes the following CPU generations:

- AMD EPYC — Genoa, Turin
- Intel Xeon — Granite Rapids

You can add your own SKUs by editing `SKU.csv`. After modifying the file, delete `specexplorer.db` and restart the server to recreate the database.
