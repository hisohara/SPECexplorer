from __future__ import annotations

import csv
import io
import re
import sqlite3
from pathlib import Path

DB_PATH = Path(__file__).resolve().parent.parent / "specexplorer.db"
SKU_CSV = Path(__file__).resolve().parent.parent / "SKU.csv"


def get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = get_conn()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS sku (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            generation TEXT NOT NULL,
            model TEXT NOT NULL,
            cores INTEGER NOT NULL,
            threads INTEGER NOT NULL,
            base_clock REAL,
            fmax REAL,
            all_core_boost REAL,
            tdp INTEGER,
            l3_cache INTEGER,
            ddr5 INTEGER,
            channel INTEGER
        );
        CREATE TABLE IF NOT EXISTS spec_result (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            benchmark_type TEXT NOT NULL,
            hardware_vendor TEXT,
            system_name TEXT,
            cores INTEGER,
            chips INTEGER,
            processor TEXT,
            result REAL,
            baseline REAL,
            sku_model TEXT,
            generation TEXT,
            spec_url TEXT
        );
    """)
    conn.commit()
    conn.close()


def load_sku_csv():
    """Load SKU.csv into sku table (idempotent — clears first)."""
    conn = get_conn()
    conn.execute("DELETE FROM sku")
    with open(SKU_CSV, newline="", encoding="utf-8") as f:
        reader = csv.reader(f)
        header = next(reader)
        for row in reader:
            if len(row) < 11 or not row[0].strip():
                continue
            conn.execute(
                "INSERT INTO sku (generation,model,cores,threads,base_clock,fmax,all_core_boost,tdp,l3_cache,ddr5,channel) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                (
                    row[0].strip(),
                    row[1].strip(),
                    int(row[2].strip()),
                    int(row[3].strip()),
                    float(row[4].strip()) if row[4].strip() else 0,
                    float(row[5].strip()) if row[5].strip() else 0,
                    float(row[6].strip()) if row[6].strip() else 0,
                    int(row[7].strip()),
                    int(row[8].strip()),
                    int(row[9].strip()),
                    int(row[10].strip()) if row[10].strip() else 0,
                ),
            )
    conn.commit()
    conn.close()


def get_sku_models() -> list[dict]:
    """Return all SKU models for matching, longest first to avoid partial matches."""
    conn = get_conn()
    rows = conn.execute("SELECT model, generation, cores FROM sku ORDER BY length(model) DESC, model").fetchall()
    conn.close()
    return [dict(r) for r in rows]


def import_spec_csv(content: bytes, benchmark_type: str) -> int:
    """Parse a SPEC result CSV, filter rows matching SKU models, insert into DB.

    Returns the number of imported rows.
    """
    sku_models = get_sku_models()
    text = content.decode("utf-8", errors="replace")
    reader = csv.reader(io.StringIO(text))
    header = next(reader)

    # Find column indices by name
    col = {h.strip().strip('"'): i for i, h in enumerate(header)}
    idx_processor = col.get("Processor")
    idx_cores = col.get("# Cores")
    idx_chips = col.get("# Chips")
    idx_result = col.get("Result")
    idx_baseline = col.get("Baseline")
    idx_vendor = col.get("Hardware Vendor\t") or col.get("Hardware Vendor")
    idx_system = col.get("System")
    idx_disclosures = col.get("Disclosure") or col.get("Disclosures")

    if idx_processor is None or idx_result is None:
        return 0

    conn = get_conn()
    count = 0
    for row in reader:
        if len(row) <= max(idx_processor, idx_result):
            continue
        processor = row[idx_processor].strip().strip('"')

        matched_sku = None
        matched_gen = None
        for sku in sku_models:
            # Word-boundary match: model must not be followed by alphanumeric
            if re.search(r'\b' + re.escape(sku["model"]) + r'(?![0-9A-Za-z])', processor):
                matched_sku = sku["model"]
                matched_gen = sku["generation"]
                break

        if matched_sku is None:
            continue

        try:
            result_val = float(row[idx_result].strip()) if row[idx_result].strip() else 0
        except ValueError:
            result_val = 0

        try:
            baseline_val = float(row[idx_baseline].strip()) if idx_baseline and row[idx_baseline].strip() else 0
        except (ValueError, IndexError):
            baseline_val = 0

        try:
            cores_val = int(row[idx_cores].strip()) if idx_cores is not None else 0
        except ValueError:
            cores_val = 0

        try:
            chips_val = int(row[idx_chips].strip()) if idx_chips is not None else 0
        except ValueError:
            chips_val = 0

        vendor = row[idx_vendor].strip().strip('"') if idx_vendor is not None and idx_vendor < len(row) else ""
        system_name = row[idx_system].strip().strip('"') if idx_system is not None and idx_system < len(row) else ""

        spec_url = ""
        if idx_disclosures is not None and idx_disclosures < len(row):
            href_match = re.search(r'HREF="([^"]+\.html)"', row[idx_disclosures])
            if href_match:
                spec_url = "https://spec.org" + href_match.group(1)

        conn.execute(
            "INSERT INTO spec_result (benchmark_type,hardware_vendor,system_name,cores,chips,processor,result,baseline,sku_model,generation,spec_url) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (benchmark_type, vendor, system_name, cores_val, chips_val, processor, result_val, baseline_val, matched_sku, matched_gen, spec_url),
        )
        count += 1

    conn.commit()
    conn.close()
    return count


def get_filter_options() -> dict:
    """Return available filter values from current data."""
    conn = get_conn()
    result = {
        "benchmark_types": [r["benchmark_type"] for r in conn.execute("SELECT DISTINCT benchmark_type FROM spec_result ORDER BY benchmark_type").fetchall()],
        "chips": [r["chips"] for r in conn.execute("SELECT DISTINCT chips FROM spec_result ORDER BY chips").fetchall()],
        "amd_skus": [dict(r) for r in conn.execute("SELECT model, cores, generation FROM sku WHERE generation IN ('Turin','Genoa') ORDER BY CASE generation WHEN 'Turin' THEN 0 WHEN 'Genoa' THEN 1 END, cores, model").fetchall()],
        "intel_skus": [dict(r) for r in conn.execute("SELECT model, cores, generation FROM sku WHERE generation NOT IN ('Turin','Genoa') ORDER BY CASE WHEN generation LIKE 'Granite Rapids%' THEN 'Granite Rapids' ELSE generation END, cores, model").fetchall()],
        "amd_sku_specs": [dict(r) for r in conn.execute("SELECT generation, model, cores, threads, base_clock, fmax, all_core_boost, tdp, l3_cache, ddr5, channel FROM sku WHERE generation IN ('Turin','Genoa') ORDER BY CASE generation WHEN 'Turin' THEN 0 WHEN 'Genoa' THEN 1 END, cores, model").fetchall()],
        "intel_sku_specs": [dict(r) for r in conn.execute("SELECT generation, model, cores, threads, base_clock, fmax, all_core_boost, tdp, l3_cache, ddr5, channel FROM sku WHERE generation NOT IN ('Turin','Genoa') ORDER BY CASE WHEN generation LIKE 'Granite Rapids%' THEN 'Granite Rapids' ELSE generation END, cores, model").fetchall()],
    }
    conn.close()
    return result


def get_sku_info(models: list[str]) -> dict:
    """Return SKU info keyed by model name."""
    conn = get_conn()
    placeholders = ",".join("?" * len(models))
    rows = conn.execute(
        f"SELECT model, generation, cores, tdp, channel FROM sku WHERE model IN ({placeholders})",
        models,
    ).fetchall()
    conn.close()
    return {r["model"]: dict(r) for r in rows}


def query_results(
    benchmark_type: str = None,
    chips: list[int] = None,
    sku_models: list[str] = None,
) -> list[dict]:
    """Query spec_result with filters (AND condition)."""
    conn = get_conn()
    conditions = []
    params = []

    if benchmark_type:
        conditions.append("benchmark_type = ?")
        params.append(benchmark_type)

    if chips:
        placeholders = ",".join("?" * len(chips))
        conditions.append(f"chips IN ({placeholders})")
        params.extend(chips)

    if sku_models:
        placeholders = ",".join("?" * len(sku_models))
        conditions.append(f"sku_model IN ({placeholders})")
        params.extend(sku_models)

    where = " AND ".join(conditions) if conditions else "1=1"
    sql = f"""SELECT s.generation, s.sku_model, s.processor, COALESCE(k.tdp, 0) as tdp,
        s.system_name, s.hardware_vendor, s.cores, s.chips, s.benchmark_type,
        s.result, s.baseline, s.spec_url, COALESCE(k.channel, 0) as channel
        FROM spec_result s LEFT JOIN sku k ON s.sku_model = k.model
        WHERE {where} ORDER BY s.generation, s.sku_model, s.result DESC"""
    rows = conn.execute(sql, params).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_sku_count() -> int:
    conn = get_conn()
    count = conn.execute("SELECT COUNT(*) as cnt FROM sku").fetchone()["cnt"]
    conn.close()
    return count


def get_result_count() -> int:
    conn = get_conn()
    count = conn.execute("SELECT COUNT(*) as cnt FROM spec_result").fetchone()["cnt"]
    conn.close()
    return count


def clear_results():
    conn = get_conn()
    conn.execute("DELETE FROM spec_result")
    conn.commit()
    conn.close()
