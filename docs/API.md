# 工作台 API 示例

服务启动后通过 [OpenAPI 文档](http://127.0.0.1:8000/docs) 调用接口。请求体使用 `Content-Type: application/json`，单位为 mm、kN、MPa。

## 优化孔位

`POST /api/layout/optimize`

```json
{"L":200,"W":100,"off":20,"nx":1,"ny":1,"n":2}
```

响应示例。

```json
{
  "candidate_count":4,
  "perimeter_mm":760.0,
  "initial":{
    "ids":["01","03"],
    "holes":[{"hole_id":"01","x_mm":-120,"y_mm":-70},{"hole_id":"03","x_mm":120,"y_mm":70}],
    "max_gap_mm":380.0,"cv":0.0,"eccentricity_mm":0.0
  },
  "biased":{
    "ids":["02","03"],
    "holes":[{"hole_id":"02","x_mm":120,"y_mm":-70},{"hole_id":"03","x_mm":120,"y_mm":70}],
    "max_gap_mm":620.0,"cv":0.631578947368421,"eccentricity_mm":120.0
  },
  "moved":{"from":"01","to":"02"},
  "score":0.0,
  "fallback":false
}
```

## 比较不同孔数

`POST /api/layout/study`

```json
{"L":1200,"W":600,"off":80,"nx":24,"ny":16,"counts":[14,32,48],"bolt_diameter_mm":45}
```

最多 12 个互不重复的候选数量。响应含 `candidate_count` 以及按数量升序的 `options`，每项的字段包括 `count`、`max_gap_mm`、`cv`、`eccentricity_mm`、`net_clearance_mm` 和 `fallback`。净距为入选孔对最短中心距减去给定外径。单孔的净距返回 `null`。

## 估算装夹附加压应力

`POST /api/stress/estimate`

```json
{
  "holes":[{"hole_id":"01","x_mm":0,"y_mm":0}],
  "force_kn":10,
  "depth_mm":50,
  "ring_length_mm":240,
  "ring_width_mm":140
}
```

```json
{
  "peak_mpa":1.909859317102744,
  "peak_position_mm":{"x":0,"y":0},
  "grid":{"columns":241,"rows":131,"padding_mm":60,"x_mm":[-180,180],"y_mm":[-130,130]},
  "method":"boussinesq_elastic_halfspace"
}
```

孔圈长宽同时填写或同时省略。省略时按传入孔位的坐标对称取界再外扩 60 mm。

## 扫描载荷和截面深度

`POST /api/stress/sweep`

```json
{"holes":[{"hole_id":"01","x_mm":0,"y_mm":0}],"ring_length_mm":240,"ring_width_mm":140}
```

返回 `cases`、`grid` 和 `method`。 `cases` 包含 25／50／100 mm 与 5／10／20 kN 的九种组合，按深度、孔力升序排列。下列为其中一个结果条目。

```json
{"force_kn":10,"depth_mm":50,"peak_mpa":1.909859317102744,"peak_position_mm":{"x":0,"y":0}}
```

调用不要求安装 Abaqus。扫描采用与单次估算相同的网格和输入约束，利用点载模型对力的线性关系复用计算。

## 计算深度剖面

`POST /api/stress/section`

```json
{"holes":[{"hole_id":"01","x_mm":0,"y_mm":0}],"force_kn":10,"axis":"x","slice_mm":0,"ring_length_mm":240,"ring_width_mm":140}
```

`axis` 取 `x` 或 `y`。`slice_mm` 是另一条水平轴上固定的坐标，单位 mm。沿指定轴覆盖孔圈并外扩 60 mm，深度从 10 mm 到 160 mm。响应包括 `axis`、`slice_mm`、`lateral_mm` 和 `depth_mm` 两组坐标范围、`columns: 121`、`rows: 61`、`values_mpa` 与 `peak_mpa`。矩阵从浅到深排列，每行按水平坐标升序排列。上例的峰值约为 47.746483 MPa。

该接口和应力估算使用相同的 Boussinesq 集中力叠加模型，可在无 Abaqus 的环境运行。

## 提交前检查网格与加载

`POST /api/simulation/preflight`

请求体与 `POST /api/simulation/run` 相同。接口使用真实建模脚本中的分段逻辑计算网格和压力面，未配置 Abaqus 时也可调用。下列为默认工况（1200 × 600 mm 水腔、32 根、5 MPa、50 mm 目标网格）响应。

```json
{
  "elements":11896,
  "pressure_faces":504,
  "thrust_kn":3600.0,
  "within_mesh_limit":true,
  "mesh_limit":160000
}
```

限制判断基于规则包络网格的单元数上界，可能高于 `elements`。该检查不执行静力求解，也不替代网格收敛和接触条件验证。

## 对照粗细网格

`POST /api/simulation/mesh-study`

请求与提交求解相同。以 `mesh_mm` 为基准，计算粗、原始、细三档，即目标尺寸的 1.5、1、0.75 倍。限制在 10–250 mm 内并去掉相同尺寸。响应为 `options` 数组，每项含 `mesh_mm` 和对应的网格预检结果。超过模型单元数限制时，真实作业接口在入队前返回 HTTP 422。网格规模对照不执行数值收敛检验。

## 提交真实求解

`POST /api/simulation/run`

```json
{
  "L":200,"W":100,"off":20,"nx":1,"ny":1,"n":2,
  "holes":[{"hole_id":"01","x_mm":-120,"y_mm":-70},{"hole_id":"03","x_mm":120,"y_mm":70}],
  "force_kn":10,"pressure_mpa":5,
  "plate_thickness_mm":100,"flange_thickness_mm":25,"flange_lip_mm":25,"plate_edge_mm":100,"mesh_mm":50,
  "concrete_e_mpa":33000,"concrete_nu":0.2,"flange_e_mpa":200000,"flange_nu":0.3
}
```

孔号和坐标可直接取布孔响应中的 `initial.holes` 或 `biased.holes`。示例设置了全部可选模型参数。

```json
{"job_id":"5d667d6e-47a1-426a-abb4-c624beab9b66","status":"queued","progress":0}
```

受理返回 HTTP 202，队列已满返回 HTTP 429，求解器未配置返回 HTTP 503。输入不符合字段约束时返回 HTTP 422。

## 查看最近求解任务

`GET /api/simulation/jobs?limit=20`

```json
{
  "jobs":[
    {
      "job_id":"5d667d6e-47a1-426a-abb4-c624beab9b66",
      "status":"done","progress":100,"message":"求解和云图导出完成。",
      "updated_at":1795757400,"bolt_count":2,"pressure_mpa":5
    }
  ]
}
```

按提交时间倒序返回。`limit` 取 1–50，默认 20。`updated_at` 是 Unix 时间戳（秒）。可用作业编号查询状态或读取结果。未提交作业时返回空数组。

## 查询作业状态

`GET /api/simulation/5d667d6e-47a1-426a-abb4-c624beab9b66/status`

```json
{"job_id":"5d667d6e-47a1-426a-abb4-c624beab9b66","status":"running","progress":52,"message":"Abaqus/Standard 求解中。"}
```

状态为 `queued`、`running`、`done` 或 `failed`。进度范围 0–100，`done` 时为 100。

## 读取作业结果

`GET /api/simulation/5d667d6e-47a1-426a-abb4-c624beab9b66/result`

以下示例数值用于说明响应字段。

```json
{
  "job_id":"5d667d6e-47a1-426a-abb4-c624beab9b66",
  "s33_url":"/api/simulation/5d667d6e-47a1-426a-abb4-c624beab9b66/files/s33.png",
  "odb_url":"/api/simulation/5d667d6e-47a1-426a-abb4-c624beab9b66/files/clamp.odb",
  "odb_name":"clamp.odb",
  "legend_min_mpa":-12.0,"legend_max_mpa":2.0,"peak_mpa":12.0,
  "integration_point_min_mpa":-14.0,"integration_point_max_mpa":2.4,
  "averaging_threshold_percent":75,"frame_index":8
}
```

未完成或失败的作业返回 HTTP 409，找不到作业返回 HTTP 404。PNG 可从工作台或 `s33_url` 下载，ODB 对应 `odb_url`。作业输入保存在对应作业目录。

## 查阅历史算例

`GET /api/archive`

返回三组算例。每组的 `components` 包含 `concrete` 与 `tank`，提供独立 S33 范围、原始来源及 PNG 地址。可用 `GET /api/archive/partial/concrete.png` 直接读取部分杆件算例的混凝土云图。

下面展示响应中部分杆件算例的条目。

```json
{
  "id":"partial","label":"去掉部分杆件","pressure_mpa":5,
  "source":"《Abaqus模拟情况.docx》二、去掉部分钢筋，Youhua3 的 wjc 应力分布。",
  "components":{
    "concrete":{"label":"混凝土 S33","asset":35,"odb_name":"wjc.odb","legend_min_mpa":-68.5,"legend_max_mpa":28.22,"image_url":"/api/archive/partial/concrete.png"},
    "tank":{"label":"水箱 S33","asset":34,"odb_name":"wjc.odb","legend_min_mpa":-1704,"legend_max_mpa":1903,"image_url":"/api/archive/partial/tank.png"}
  }
}
```

## 查询后端模式

`GET /api/simulation/availability`

```json
{"available":false,"mode":"demo","reason":"未配置有效的 ABAQUS_PATH。"}
```

检测到启动器时返回 `{"available":true,"mode":"abaqus","reason":null}`。许可证和求解器启动情况由实际作业验证。
