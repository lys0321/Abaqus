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
