# 沧砼鉴｜高水压装夹工作台

下载 [index.html](./index.html)，用浏览器打开即可离线使用。页面内嵌脚本和六张 Abaqus 历史云图，可单独分享。

五个工作区共享当前水腔、孔圈和载荷参数。可直接通过导航切换，也可按 `Ctrl+K`（macOS 为 `⌘K`）打开快捷操作。

| 工作区 | 用途 |
| --- | --- |
| 孔位设计 | 操作三维装配、周向间距与交叉装配播放。孔数方案筛选批量比较最大间距、净距和间距变异系数，点击数据点可应用，支持 CSV。 |
| 应力实验室 | 在 241 × 131 网格上估算夹持附加压应力，读取探针与深度剖面，扫描九组参数。自设相对峰值阈值后可高亮云图范围，并读取达到阈值的网格点比例。 |
| 求解控制台 | 播放加载计划、布置采集通道并导出。粗细网格对照可应用模型规模限制内的尺寸，超过限制的作业在入队前拒绝。刷新可继续跟踪已提交作业。 |
| 云图阅览室 | 核对历史 S33、查看本次作业和多通道采集回放。保压窗口复核按实测时间覆盖计算合带率，并定位、导出不符合自设偏差带的时段。 |
| 工况档案 | 保存、恢复或并排预演工况。可预览和下载独立复盘 HTML，纳入当前加载计划、孔位、采集通道，以及选择的采集结果或历史图。 |

当前工况和通道布置会保存到当前浏览器的本地草稿。刷新会恢复最后一次有效设置。命名快照可长期区分不同工况和用于跨设备交换。

三维视口支持拖拽、滚轮或捏合缩放，并支持 Shift 拖拽平移。聚焦视口时可用方向键旋转、Shift 加方向键平移、加减键缩放，按 0 复位。网页优先使用 WebGL，无法启用时使用 Canvas 三维绘制。

深度剖面、应力扫描、装配预览、试验计划与采集回放均可离线运行。通过 FastAPI 打开时，孔数筛选、深度剖面、扫描、粗细网格对照与提交前核查使用后端接口。工况快照保存在当前浏览器，兼容之前导出的 JSON。

采集 CSV 的前两列为 `t_s,pressure_mpa`，时间以试验起始为 0，采样时间严格递增。可选列为 `displacement_mm`（DIC 位移）、`strain_ue`（应变）、`ae_count`（非负声发射计数）、`fiber_ue`（光纤应变）。可选通道允许空样本，各自按采样时间线性插值。保压段末初压力差要求实测完整覆盖该区间。加载演练采用计划数据，系统无 PLC 控制接口。

## 启动服务

需要 Python 3.10 或更新版本。以下命令适用于 Windows PowerShell，在仓库目录运行。

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m uvicorn backend.main:app --host 127.0.0.1 --port 8000 --workers 1
```

在浏览器打开 [工作台](http://127.0.0.1:8000/) 或 [OpenAPI 文档](http://127.0.0.1:8000/docs)。未配置 Abaqus 时，服务提供布孔、应力估算和历史云图，真实求解接口返回 HTTP 503。

要启用求解，在启动服务前将 `ABAQUS_PATH` 设置为本机已获许可、支持 `cae`、`python` 和 `viewer` 子命令的 Abaqus 启动器。可以使用启动器绝对路径，或已加入 `PATH` 的命令。

```powershell
$env:ABAQUS_PATH = 'C:\SIMULIA\Commands\abaqus.bat'
```

上面的路径是示例，请换成本机实际路径。若旧版 Abaqus 无法读取含中文字符的路径，可将 `ABAQUS_RESULTS_DIR` 指向纯英文绝对路径。服务使用 FastAPI BackgroundTasks 和单个 Uvicorn worker。

| 环境变量 | 默认值 | 用途 |
| --- | --- | --- |
| `ABAQUS_PATH` | 未设置 | Abaqus 启动器 |
| `ABAQUS_RESULTS_DIR` | `results` | SQLite 和作业文件目录 |
| `ABAQUS_MAX_RUNNING` | 1 | 同时运行的作业数 |
| `ABAQUS_QUEUE_LIMIT` | 8 | 排队和运行中的作业总上限 |
| `ABAQUS_TIMEOUT_SECONDS` | 1800 | 每个作业各阶段合计的时限，单位秒 |
| `ABAQUS_CPUS` | 2 | 每个 Abaqus/Standard 作业分配的 CPU 数 |

## 模型与结果

- 解析估算采用 Boussinesq 弹性半空间解，峰值为截面网格上的压应力幅值，孔力单位 kN，长度单位 mm，应力单位 MPa。该估算仅用于演示夹持力空间叠加，不能据此判定试件损伤。
- 真实作业使用线弹性混凝土板和钢法兰，底面固定，法兰与混凝土共节点，水腔顶面施加压力，每个入选孔在法兰顶面施加向下的等效集中力。模型用于当前方案的有限元演示，历史算例和工程实物的接触、预紧及开裂条件需另行建模。
- Abaqus/Standard 返回静力步最终帧。后处理提取 S33 积分点范围，再用 Abaqus Viewer 以 75% 节点平均阈值导图。云图 S33 正值为拉、负值为压，`peak_mpa` 为平均后云图的最大绝对值。
- 历史云图取自项目资料《Abaqus模拟情况》。每张云图使用自己的色标。调整孔位后仍可查阅原算例，生成新工况云图需重新求解。
- 本版本已验证前端和模拟求解进程的端到端流程。许可证、真实 ODB 和数值结果仍需在配置了 Abaqus 的环境验证。

[Abaqus CAE 命令行](https://docs.software.vt.edu/abaqusv2025/English/SIMACAECMDRefMap/simacmd-c-aclintintrointerface.htm) · [Abaqus Python 命令](https://docs.software.vt.edu/abaqusv2025/English/SIMACAECMDRefMap/simacmd-c-intpytintrointerpreter.htm) · [Abaqus 外推与节点平均](https://docs.software.vt.edu/abaqusv2026/English/SIMACAECAERefMap/simacae-t-conextrapbtn.htm)

## 目录

```text
Abaqus/
├── .gitignore
├── README.md
├── index.html
├── requirements.txt
├── docs/
│   └── API.md
├── backend/
│   ├── __init__.py
│   ├── main.py
│   ├── physics.py
│   ├── jobs.py
│   └── abaqus/
│       ├── build_model.py
│       ├── extract_s33.py
│       └── render_s33.py
└── results/                          # 运行后生成
    ├── jobs.sqlite3
    └── {job_id}/                     # 作业独立目录
        ├── input.json
        ├── build_model.py
        ├── extract_s33.py
        ├── render_s33.py
        ├── model.inp
        ├── mesh.json
        ├── clamp.odb
        ├── s33-extracted.json
        ├── s33.png
        ├── result.json
        └── *.log                     # 以及 Abaqus 生成的状态文件
```

[API 请求和响应示例](./docs/API.md) · [接口定义](./backend/main.py) · [孔位及解析计算](./backend/physics.py) · [作业管理](./backend/jobs.py) · [Abaqus 建模](./backend/abaqus/build_model.py) · [ODB 提取](./backend/abaqus/extract_s33.py) · [云图生成](./backend/abaqus/render_s33.py)
