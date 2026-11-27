"""Serve the workbench and lightweight Abaqus task API."""
from contextlib import asynccontextmanager
from functools import cache
from pathlib import Path
from uuid import UUID
import base64
import json
import re

from fastapi import BackgroundTasks, FastAPI, HTTPException, Query
from fastapi.responses import FileResponse, Response

from .abaqus.build_model import mesh_preflight
from .jobs import Jobs, QueueFull, Settings
from .physics import (
    LayoutRequest, SimulationRequest, StressGeometry, StressRequest, StressSectionRequest,
    estimate, optimize, stress_section, sweep_stress,
)

ROOT = Path(__file__).resolve().parents[1]
PAGE = ROOT / "index.html"


@cache
def archive_data():
    page = PAGE.read_text(encoding="utf-8")
    catalog = re.search(r'<script id="archive-data" type="application/json">([\s\S]+?)</script>', page)
    images = re.search(r"const archiveImages = (\{[^\n]+\});", page)
    if catalog is None or images is None:
        raise RuntimeError("Missing embedded Abaqus archive.")
    return json.loads(catalog[1]), json.loads(images[1])


def create_app(settings=None):
    jobs = Jobs(settings or Settings.from_env())

    @asynccontextmanager
    async def lifespan(app):
        jobs.initialize()
        yield

    app = FastAPI(title="沧砼鉴 Abaqus 工作台", version="1.0", lifespan=lifespan)

    def get_job(job_id):
        row = jobs.get(str(job_id))
        if row is None:
            raise HTTPException(404, "找不到作业。")
        return row

    @app.get("/", include_in_schema=False)
    def home():
        return FileResponse(PAGE, media_type="text/html")

    @app.post("/api/layout/optimize")
    def layout(request: LayoutRequest):
        return optimize(request)

    @app.post("/api/stress/estimate")
    def stress(request: StressRequest):
        return estimate(request)

    @app.post("/api/stress/sweep")
    def sweep(request: StressGeometry):
        return sweep_stress(request)

    @app.post("/api/stress/section")
    def section(request: StressSectionRequest):
        return stress_section(request)

    @app.get("/api/simulation/availability")
    def availability():
        available = bool(jobs.settings.abaqus)
        return {"available": available, "mode": "abaqus" if available else "demo",
                "reason": None if available else "未配置有效的 ABAQUS_PATH。"}

    @app.post("/api/simulation/preflight")
    def preflight(request: SimulationRequest):
        return mesh_preflight(request.model_dump())

    @app.post("/api/simulation/run", status_code=202)
    def submit(request: SimulationRequest, background: BackgroundTasks):
        if not jobs.settings.abaqus:
            raise HTTPException(503, "未配置有效的 ABAQUS_PATH。当前为演示模式。")
        try:
            job_id = jobs.create(request.model_dump())
        except QueueFull:
            raise HTTPException(429, "作业队列已满，请稍后重试。", headers={"Retry-After": "15"})
        background.add_task(jobs.run, job_id)
        return {"job_id": job_id, "status": "queued", "progress": 0}

    @app.get("/api/simulation/jobs")
    def recent_jobs(limit: int = Query(20, ge=1, le=50)):
        return {"jobs": jobs.recent(limit)}

    @app.get("/api/simulation/{job_id}/status")
    def status(job_id: UUID):
        row = get_job(job_id)
        return {"job_id": row["id"], "status": row["status"],
                "progress": row["progress"], "message": row["message"]}

    @app.get("/api/simulation/{job_id}/result")
    def result(job_id: UUID):
        row = get_job(job_id)
        if row["status"] != "done":
            raise HTTPException(409, "作业尚无可用结果。")
        base = f"/api/simulation/{job_id}/files"
        return {"job_id": str(job_id), **json.loads(row["result"]),
                "s33_url": base + "/s33.png", "odb_url": base + "/clamp.odb"}

    @app.get("/api/simulation/{job_id}/files/{name}")
    def result_file(job_id: UUID, name: str):
        row = get_job(job_id)
        if row["status"] != "done" or name not in {"s33.png", "clamp.odb"}:
            raise HTTPException(404, "结果文件不可用。")
        item = jobs.settings.results / str(job_id) / name
        if not item.is_file():
            raise HTTPException(404, "结果文件已移除。")
        mime = "image/png" if name.endswith(".png") else "application/octet-stream"
        return FileResponse(item, media_type=mime)

    @app.get("/api/archive")
    def archive():
        rows, _ = archive_data()
        return {"cases": [
            {**case, "components": {
                name: {**component, "image_url": f"/api/archive/{case['id']}/{name}.png"}
                for name, component in case["components"].items()
            }}
            for case in rows
        ]}

    @app.get("/api/archive/{case_id}/{component}.png")
    def archive_image(case_id: str, component: str):
        rows, images = archive_data()
        for case in rows:
            if case["id"] == case_id and component in case["components"]:
                item = case["components"][component]
                if item["asset"] is None:
                    raise HTTPException(404, "原图未收录。")
                return Response(base64.b64decode(images[str(item["asset"])]), media_type="image/png")
        raise HTTPException(404, "找不到历史云图。")

    return app


app = create_app()
