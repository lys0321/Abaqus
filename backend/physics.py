"""Geometry and elastic half-space estimates in N, mm and MPa."""
from math import hypot, pi, sqrt
from typing import Annotated

import numpy as np
from pydantic import BaseModel, ConfigDict, Field, model_validator

Coordinate = Annotated[float, Field(ge=-12000, le=12000)]
GRID_COLUMNS, GRID_ROWS, GRID_PADDING_MM = 241, 131, 60.0


class RequestModel(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


class Hole(RequestModel):
    hole_id: str = Field(pattern=r"^\d{1,3}$")
    x_mm: Coordinate
    y_mm: Coordinate


class LayoutRequest(RequestModel):
    L: float = Field(ge=1, le=5000)
    W: float = Field(ge=1, le=5000)
    off: float = Field(ge=0, le=1000)
    nx: int = Field(ge=1, le=255)
    ny: int = Field(ge=1, le=255)
    n: int = Field(ge=1, le=512)

    @model_validator(mode="after")
    def validate_counts(self):
        count = 2 * (self.nx + self.ny)
        if count > 512 or self.n > count:
            raise ValueError("候选孔数最多为 512，且入选孔数不得超过候选孔数。")
        return self


def ring(request):
    x, y = request.L / 2 + request.off, request.W / 2 + request.off
    nx, ny = request.nx, request.ny
    return np.array([
        *((-x + 2 * x * (i / nx), -y) for i in range(nx)),
        *((x, -y + 2 * y * (i / ny)) for i in range(ny)),
        *((x - 2 * x * (i / nx), y) for i in range(nx)),
        *((-x, y - 2 * y * (i / ny)) for i in range(ny)),
    ], dtype=np.float64)


def stats(ids, points, arc, perimeter):
    locations = arc[ids]
    gaps = np.diff(np.r_[locations, perimeter + locations[0]])
    avg = perimeter / len(ids)
    x, y = points[ids].mean(axis=0)
    return {
        "max_gap_mm": float(gaps.max()),
        "cv": float(sqrt(((gaps / avg - 1) ** 2).mean())),
        "eccentricity_mm": hypot(x, y),
    }


def optimize(request):
    points = ring(request)
    arc = np.r_[0., np.cumsum(np.linalg.norm(np.roll(points, -1, axis=0) - points, axis=1))]
    perimeter = float(arc[-1])
    step = perimeter / request.n
    offsets = np.arange(request.n) * step
    best = None
    best_score = float("inf")
    for start in arc[:-1]:
        targets = (start + offsets) % perimeter
        delta = np.abs(targets[:, None] - arc[:-1])
        indices = np.minimum(delta, perimeter - delta).argmin(axis=1)
        if len(set(indices)) != request.n:
            continue
        ids = sorted(indices.tolist())
        metrics = stats(ids, points, arc, perimeter)
        score = metrics["cv"] + metrics["eccentricity_mm"] / step
        if score < best_score - 1e-12:
            best, best_score = ids, score

    fallback = best is None
    if fallback:
        best = [i * len(points) // request.n for i in range(request.n)]

    biased = best.copy()
    occupied = set(best)
    moved = None
    for k, index in enumerate(best):
        successor = (index + 1) % len(points)
        if successor not in occupied:
            biased[k] = successor
            moved = {"from": f"{index + 1:02d}", "to": f"{successor + 1:02d}"}
            break
    biased.sort()

    def describe(ids):
        return {
            "ids": [f"{i + 1:02d}" for i in ids],
            "holes": [
                {"hole_id": f"{i + 1:02d}", "x_mm": float(points[i, 0]), "y_mm": float(points[i, 1])}
                for i in ids
            ],
            **stats(ids, points, arc, perimeter),
        }

    initial = describe(best)
    return {
        "candidate_count": len(points), "perimeter_mm": perimeter,
        "initial": initial, "biased": describe(biased), "moved": moved,
        "score": initial["cv"] + initial["eccentricity_mm"] / step, "fallback": fallback,
    }


class StressGeometry(RequestModel):
    holes: list[Hole] = Field(min_length=1, max_length=512)
    ring_length_mm: float | None = Field(default=None, gt=0, le=12000)
    ring_width_mm: float | None = Field(default=None, gt=0, le=12000)

    @model_validator(mode="after")
    def validate_grid(self):
        if (self.ring_length_mm is None) != (self.ring_width_mm is None):
            raise ValueError("孔圈长宽应同时提供或同时省略。")
        if len({int(h.hole_id) for h in self.holes}) != len(self.holes):
            raise ValueError("孔号不可重复。")
        if self.ring_length_mm is not None and any(
            abs(h.x_mm) > self.ring_length_mm / 2 + 1e-6 or
            abs(h.y_mm) > self.ring_width_mm / 2 + 1e-6 for h in self.holes
        ):
            raise ValueError("存在孔位超出指定孔圈。")
        return self


class StressRequest(StressGeometry):
    force_kn: float = Field(gt=0, le=200)
    depth_mm: float = Field(ge=1, le=1000)


def estimate(request):
    half_x = request.ring_length_mm / 2 if request.ring_length_mm is not None else max(abs(h.x_mm) for h in request.holes)
    half_y = request.ring_width_mm / 2 if request.ring_width_mm is not None else max(abs(h.y_mm) for h in request.holes)
    x = np.linspace(-half_x - GRID_PADDING_MM, half_x + GRID_PADDING_MM, GRID_COLUMNS)
    y = np.linspace(half_y + GRID_PADDING_MM, -half_y - GRID_PADDING_MM, GRID_ROWS)
    field = np.zeros((GRID_ROWS, GRID_COLUMNS))
    depth = request.depth_mm
    coefficient = 3 * request.force_kn * 1000 * depth ** 3 / (2 * pi)
    for hole in request.holes:
        q = (x[None, :] - hole.x_mm)**2 + (y[:, None] - hole.y_mm)**2 + depth**2
        field += coefficient / (q*q*np.sqrt(q))
    row, col = np.unravel_index(field.argmax(), field.shape)
    return {
        "peak_mpa": float(field[row, col]),
        "peak_position_mm": {"x": float(x[col]), "y": float(y[row])},
        "grid": {"columns": GRID_COLUMNS, "rows": GRID_ROWS, "padding_mm": GRID_PADDING_MM,
                 "x_mm": [float(x[0]), float(x[-1])], "y_mm": [float(y[-1]), float(y[0])]},
        "method": "boussinesq_elastic_halfspace",
    }


def sweep_stress(geometry: StressGeometry):
    forces, depths = (5, 10, 20), (25, 50, 100)
    cases = []
    for depth in depths:
        reference = estimate(StressRequest(**geometry.model_dump(), force_kn=forces[0], depth_mm=depth))
        for force in forces:
            cases.append({
                "force_kn": force, "depth_mm": depth,
                "peak_mpa": reference["peak_mpa"] * (force / forces[0]),
                "peak_position_mm": reference["peak_position_mm"],
            })
    return {"cases": cases, "grid": reference["grid"], "method": reference["method"]}


class SimulationRequest(LayoutRequest):
    holes: list[Hole] = Field(min_length=1, max_length=512)
    pressure_mpa: float = Field(gt=0, le=50)
    force_kn: float = Field(gt=0, le=200)
    plate_thickness_mm: float = Field(default=500, ge=20, le=1500)
    flange_thickness_mm: float = Field(default=25, ge=5, le=200)
    flange_lip_mm: float = Field(default=25, ge=5, le=200)
    plate_edge_mm: float = Field(default=100, ge=10, le=1000)
    mesh_mm: float = Field(default=50, ge=10, le=250)
    concrete_e_mpa: float = Field(default=33000, gt=0, le=400000)
    concrete_nu: float = Field(default=0.2, ge=0, lt=0.5)
    flange_e_mpa: float = Field(default=200000, gt=0, le=400000)
    flange_nu: float = Field(default=0.3, ge=0, lt=0.5)

    @model_validator(mode="after")
    def validate_holes(self):
        candidates = ring(self)
        seen = set()
        if len(self.holes) != self.n:
            raise ValueError("实际孔位数必须等于 n。")
        for hole in self.holes:
            index = int(hole.hole_id) - 1
            if index in seen or not 0 <= index < len(candidates):
                raise ValueError("孔号重复或超出候选孔范围。")
            x, y = candidates[index]
            if abs(x - hole.x_mm) > 1e-5 or abs(y - hole.y_mm) > 1e-5:
                raise ValueError(f"孔 {hole.hole_id} 坐标与当前孔圈候选点不一致。")
            seen.add(index)
        return self
