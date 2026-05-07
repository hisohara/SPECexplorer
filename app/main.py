from typing import Optional

from fastapi import FastAPI, File, Form, Request, UploadFile
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pathlib import Path

from . import database as db

app = FastAPI(title="SPEC CPU 2017 Explorer")
templates = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))
app.mount("/static", StaticFiles(directory=str(Path(__file__).parent / "static")), name="static")


@app.on_event("startup")
def startup():
    db.init_db()
    if db.get_sku_count() == 0:
        db.load_sku_csv()


@app.get("/", response_class=HTMLResponse)
def index(request: Request):
    filter_opts = db.get_filter_options()
    result_count = db.get_result_count()
    return templates.TemplateResponse(request, "index.html", {
        "filter_opts": filter_opts,
        "result_count": result_count,
    })


@app.post("/upload", response_class=HTMLResponse)
async def upload(request: Request, fp_file: Optional[UploadFile] = File(None), int_file: Optional[UploadFile] = File(None)):
    imported = 0
    if fp_file and fp_file.filename:
        content = await fp_file.read()
        imported += db.import_spec_csv(content, "FP")
    if int_file and int_file.filename:
        content = await int_file.read()
        imported += db.import_spec_csv(content, "INT")

    filter_opts = db.get_filter_options()
    result_count = db.get_result_count()
    return templates.TemplateResponse(request, "index.html", {
        "filter_opts": filter_opts,
        "result_count": result_count,
        "message": f"Imported {imported} SPEC results",
    })


@app.post("/clear", response_class=HTMLResponse)
def clear(request: Request):
    db.clear_results()
    filter_opts = db.get_filter_options()
    return templates.TemplateResponse(request, "index.html", {
        "filter_opts": filter_opts,
        "result_count": 0,
        "message": "All data cleared",
    })


@app.post("/filter", response_class=HTMLResponse)
async def filter_results(request: Request):
    form = await request.form()

    benchmark_type = form.get("benchmark_type") or None
    selected_chips = [int(c) for c in form.getlist("chips") if c]
    sku_models = form.getlist("sku_model")

    results = db.query_results(
        benchmark_type=benchmark_type,
        chips=selected_chips or None,
        sku_models=sku_models or None,
    )

    # Build per-SKU/chips summary (min/max/avg of baseline)
    from collections import defaultdict
    sku_data = defaultdict(list)
    for r in results:
        sku_data[(r["sku_model"], r["chips"])].append(r)
    summary = []
    for (model, chips) in sorted(sku_data.keys()):
        rows = sku_data[(model, chips)]
        baselines = [(r["baseline"], r) for r in rows if r["baseline"]]
        if not baselines:
            continue
        baselines.sort(key=lambda x: x[0])
        min_val, min_row = baselines[0]
        max_val, max_row = baselines[-1]
        avg_val = sum(b for b, _ in baselines) / len(baselines)
        summary.append({
            "sku_model": model,
            "chips": chips,
            "generation": rows[0]["generation"],
            "cores": rows[0]["cores"],
            "min_base": min_val,
            "min_system": min_row["system_name"],
            "min_url": min_row.get("spec_url", ""),
            "max_base": max_val,
            "max_system": max_row["system_name"],
            "max_url": max_row.get("spec_url", ""),
            "avg_base": round(avg_val, 2),
            "tdp": rows[0]["tdp"],
            "avg_base_per_tdp": round(avg_val / rows[0]["tdp"], 2) if rows[0]["tdp"] > 0 else 0,
            "count": len(baselines),
            "channel": rows[0].get("channel", 0),
        })

    # Add placeholder rows for selected SKUs with no results
    if sku_models:
        existing_models = {s["sku_model"] for s in summary}
        missing_models = [m for m in sku_models if m not in existing_models]
        if missing_models:
            sku_info = db.get_sku_info(missing_models)
            chips_list = selected_chips or [1]
            for model in missing_models:
                info = sku_info.get(model, {})
                for c in chips_list:
                    summary.append({
                        "sku_model": model,
                        "chips": c,
                        "generation": info.get("generation", ""),
                        "cores": info.get("cores", 0) * c,
                        "min_base": None,
                        "min_system": "",
                        "min_url": "",
                        "max_base": None,
                        "max_system": "",
                        "max_url": "",
                        "avg_base": None,
                        "tdp": info.get("tdp", 0),
                        "avg_base_per_tdp": None,
                        "count": 0,
                        "channel": info.get("channel", 0),
                    })
        summary.sort(key=lambda s: (s["generation"], s["sku_model"], s["chips"]))

    return templates.TemplateResponse(request, "results.html", {
        "results": results,
        "count": len(results),
        "selected_skus": sku_models,
        "summary": summary,
    })
