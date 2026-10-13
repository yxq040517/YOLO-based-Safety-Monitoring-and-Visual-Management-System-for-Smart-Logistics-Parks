# 基于 YOLO 的智慧物流园区安全监测与可视化管理系统

本项目以图片、视频和摄像头目标检测为核心，将 YOLO 检测结果转换为可查看、可定位、可人工复核的风险记录。主要流程为：**提交素材 → 目标检测 → 规则判定 → 查看证据 → 标记复核结论**。

源码仓库：[yxq040517 / YOLO-based-Safety-Monitoring-and-Visual-Management-System-for-Smart-Logistics-Parks](https://github.com/yxq040517/YOLO-based-Safety-Monitoring-and-Visual-Management-System-for-Smart-Logistics-Parks)。

## 功能说明

- 图片、视频检测：显示目标框、类别、置信度，生成标注结果并支持下载。
- 风险规则：支持烟火提示、固定画面的警戒区域入侵，以及可选的防护用品缺失、人车相对位置提示。
- 检测报告：汇总触发规则、风险等级和复核状态，支持定位视频时间点。
- 风险复核：按“待复核 → 有效风险或误报 → 已处理”记录结论与原因。
- 连续事件去重：同一来源的同类风险持续出现时只生成一条记录；连续正常帧后再次出现才可重新触发，仍受冷却时间约束。
- 辅助功能：浏览器摄像头、RTSP 摄像头演示、检测概览、规则配置、模型状态和账户管理。

检测概览优先显示待处理风险，可直接进入待复核、已确认和处理中事件的筛选列表。模型状态、进行中任务和最近更新时间集中在顶部，模型原因可展开查看；最近事件与任务各展示 5 条，完整记录保留在对应列表页面。

防护用品缺失和人车相对位置规则默认关闭。人车提示基于画面中的相对位置，不代表实际距离；未触发规则也不能直接视为安全结论。

## 技术栈

| 层次 | 技术与用途 |
| --- | --- |
| 前端 | Vue 3、TypeScript、Vite、Element Plus、Pinia、Vue Router、ECharts |
| 后端 | FastAPI、Uvicorn、SQLAlchemy、Alembic；提供认证、任务、媒体与风险复核 API |
| 目标检测 | Ultralytics YOLO、PyTorch、OpenCV；连续来源使用 ByteTrack 维护跟踪状态 |
| 数据存储 | 本地运行默认 SQLite；Docker Compose 使用 PostgreSQL 16 |
| 任务执行 | 本地任务执行器；Docker Compose 使用 Celery 与 Redis |
| 视频与部署 | FFmpeg / FFprobe；Docker Compose 与 Nginx |

## 项目结构

```text
项目根目录/
├── backend/
│   ├── app/                 # API、认证、检测、风险规则与任务执行
│   ├── alembic/             # 数据库迁移
│   ├── tests/               # 后端回归测试
│   ├── training.py          # 模型训练与部署产物校验
│   └── requirements*.txt    # 运行、机器学习和开发依赖
├── frontend/
│   ├── src/                 # 页面、组件、路由与状态管理
│   ├── tests/               # 前端回归测试
│   └── package.json         # npm 命令与依赖
├── scripts/                 # 本地启动、配置生成、GPU 安装与数据集审计
├── deploy/                  # Dockerfile 与 Nginx 配置
├── docs/                    # 设计与维护记录
├── compose.yaml             # 容器化部署入口
├── .env.example             # Docker 环境变量模板，不含真实密钥
├── 启动系统.cmd             # Windows 本地启动入口
├── 安装GPU训练环境.cmd      # Windows CUDA 环境安装入口
└── 训练模型.cmd             # Windows 训练入口
```

`storage/` 为本地运行时目录，`物流数据集/` 为可选训练输入；两者不随源码提交，具体准备方式见下文。

## 运行环境

本说明优先面向 Windows 本地运行。推荐准备：

- **Python 3.10 64 位**，安装时将 Python 加入 PATH。
- **Node.js 22 或更新版本**，包含 npm。
- **FFmpeg**，将其 `bin` 目录加入 PATH；视频功能同时需要 `ffmpeg` 和 `ffprobe`。
- Git，用于克隆仓库。

安装来源：[Python](https://www.python.org/downloads/)、[Node.js](https://nodejs.org/)、[FFmpeg](https://ffmpeg.org/download.html)。

在新开的 PowerShell 中检查：

```powershell
python --version
node --version
npm --version
ffmpeg -version
ffprobe -version
```

**没有 NVIDIA 显卡也能进行检测**：系统自动选择 CPU，速度会比 GPU 慢。首次安装需要联网下载 Python 和前端依赖。

## 克隆后必须准备的模型文件

本仓库仅发布源码，不包含模型、训练数据集或运行数据库。检测前，请自行训练生成模型，或向项目维护者获取有权使用的以下两个配套文件：

```text
项目根目录/
└── storage/
    └── models/
        ├── best.pt
        └── manifest.json
```

- 必须同时放置 `best.pt` 和它对应的 `manifest.json`。
- 系统会检查权重大小、SHA256、训练元数据及物流数据集的 20 类顺序。
- 通用预训练权重 `yolo11n.pt` 不能替代这里的物流检测模型。
- 仅使用检测功能不需要训练数据集；没有模型时可以启动页面，但检测功能不可用。
- 模型清单中的历史绝对路径属于训练来源记录，换电脑或盘符后不需要为推理修改这些路径。

本仓库未提供模型下载地址或自动下载脚本；自行训练时，请按下文准备真实数据集，训练通过产物校验后会生成配套部署文件。

## 本地启动

### 首次安装并启动

在 PowerShell 中克隆仓库并进入项目根目录：

```powershell
git clone https://github.com/yxq040517/YOLO-based-Safety-Monitoring-and-Visual-Management-System-for-Smart-Logistics-Parks.git logistics-safety
Set-Location logistics-safety
```

首次安装并启动：

```powershell
.\启动系统.cmd --install
```

脚本会自动创建 `.venv`、安装后端依赖、通过 `npm ci` 安装前端依赖，然后启动前后端。

启动后访问：

- 系统页面：<http://localhost:15173>
- API 文档：<http://127.0.0.1:18080/docs>
- API 存活检查：<http://127.0.0.1:18080/api/health>

首次使用需在页面创建管理员账户，密码至少 10 个字符。**项目没有默认账号和默认密码**。

### 后续启动和停止

```powershell
.\启动系统.cmd
```

在启动窗口按 `Ctrl+C` 停止前后端。不要在已有实例运行时重复启动；`15173` 和 `18080` 端口必须空闲。

原生本地启动默认使用 SQLite 和本地任务执行，不需要额外安装 PostgreSQL 或 Redis。目录、数据库和数据库迁移会在启动时准备；根目录 `.env` 不会被原生启动脚本自动读取。

如果需要明确使用 CPU，在同一个 PowerShell 窗口中执行：

```powershell
$env:INFERENCE_DEVICE="cpu"
.\启动系统.cmd
```

## 使用流程

1. 在“开始检测”上传图片或视频，选择检测参数并提交。
2. 在“检测记录”打开任务，查看标注结果和规则判定摘要。
3. 对视频中的风险点击“定位”回看对应时间点，点击“复核”记录结论。
4. 将有效风险标记为已处理，或填写原因后标记为误报。
5. 在辅助功能中使用摄像头演示、查看概览或调整规则。

管理员可创建账户；操作员可提交检测和复核结果；观察员主要用于查看结果。

RTSP 地址需要在使用者当前网络内可访问。摄像头检测需手动启动，服务重启后需重新启动摄像头检测。实时流保存风险快照和最新预览，不提供连续视频归档。当前警戒区域为全局规则配置，应结合固定机位设置。

默认单文件上传上限为 512 MB，视频时长上限为 4 小时。实际耗时取决于素材长度、分辨率和运行硬件。

## 模型训练（可选）

只运行检测时可以跳过本节。训练前需要额外准备真实数据集：

```text
物流数据集/
├── data.yaml
├── train/
│   ├── images/
│   └── labels/
├── valid/
│   ├── images/
│   └── labels/
└── test/
    ├── images/
    └── labels/
```

`data.yaml` 必须使用项目预期的 20 类顺序，图片和 YOLO 标签文件名需对应。训练数据集也被 `.gitignore` 排除，需要单独获取。

### GPU 环境

如果已安装依赖且使用 NVIDIA 显卡，可运行：

```powershell
.\安装GPU训练环境.cmd
```

此快捷脚本仅适用于 **Windows、Python 3.10、64 位环境**，安装固定的 CUDA 12.8 PyTorch 包并验证 GPU；还需要兼容的 NVIDIA 驱动。其他 Python 版本或系统不能直接使用此脚本。

### 正式训练

以下命令显式使用 CUDA，并根据显存选择 batch：

```powershell
.\训练模型.cmd --epochs 30 --batch 4 --imgsz 640 --device 0
```

不指定参数时，正式训练默认 100 个 epoch、batch 4、图像尺寸 640。默认 `--device auto` 要求 CUDA；CPU 训练必须明确指定：

```powershell
.\训练模型.cmd --epochs 30 --batch 2 --device cpu
```

训练启动器自动启用 `--group-splits`，按原图标识将同源变体分配至同一个集合，优先级为 `train > test > val`。它生成每次运行专属的图片列表，不搬动原始文件；训练前检查列表重叠，恢复训练时校验保存的列表与输入。

正式训练完成后，使用最佳权重单独评估 test 集，并将 `test_metrics` 与验证集指标分别记录。通过产物校验后会自动更新 `storage/models/` 中的部署模型。训练耗时可能较长，需预留磁盘空间和 GPU 使用时间。

### 冒烟训练与断点恢复

验证训练流程的小样本单轮运行：

```powershell
.\训练模型.cmd --smoke --device 0 --batch 2 --imgsz 320
```

冒烟产物隔离保存到 `storage/training/smoke/`，默认不替换现有部署模型；小样本指标不能用于评估实际检测效果。

恢复同一运行的 `last.pt`，将 `运行名称` 替换为实际目录名：

```powershell
.\训练模型.cmd --name "运行名称" --resume
```

恢复训练依赖原运行的参数、图片列表和文件校验值，不建议把旧训练目录搬到另一台电脑后直接续跑。更多参数可查看：

```powershell
.\.venv\Scripts\python.exe backend\training.py --help
```

## Docker 运行（可选）

安装并启动 Docker 后，在项目根目录执行：

```powershell
python scripts/configure.py
docker compose up --build -d
```

`configure.py` 会生成当前环境专用的 `.env`，已有文件不会被覆盖。模型文件仍需放在 `storage/models/`。

访问 <http://localhost:8080>，停止服务使用：

```powershell
docker compose down
```

Compose 使用 PostgreSQL 和 Redis，数据库数据保存在命名卷中。当前后端镜像安装 CPU 版 PyTorch，未配置 NVIDIA GPU 容器运行。网页端口绑定本机 `127.0.0.1`，直接启动不会对外开放。

## 临时通过 HTTPS 分享

本机运行与仓库克隆是两种方式：HTTPS 分享时，对方只需要浏览器，检测仍在你的电脑执行。

可使用 [Cloudflare Quick Tunnel](https://developers.cloudflare.com/cloudflare-one/networks/connectors/cloudflare-tunnel/do-more-with-tunnels/trycloudflare/)：

```powershell
winget install --id Cloudflare.cloudflared --exact
```

安装后重新打开 PowerShell，启动隧道并保留窗口：

```powershell
cloudflared tunnel --url http://127.0.0.1:15173
```

取得输出的随机 HTTPS 地址后，在项目根目录另开 PowerShell，将下面的示例域名替换为实际域名：

```powershell
$env:__VITE_ADDITIONAL_SERVER_ALLOWED_HOSTS="abc-example.trycloudflare.com"
$env:CORS_ORIGINS="https://abc-example.trycloudflare.com,http://localhost:15173,http://127.0.0.1:15173"
.\启动系统.cmd
```

第一项仅填域名，第二项包含 `https://`。若项目已经运行，先停止后再带上述环境变量启动。隧道先于项目启动时，公网地址暂时返回 502，项目启动后即可使用。

将 HTTPS 地址和为对方创建的账户提供给对方即可。两个窗口和电脑需保持运行；分别按 `Ctrl+C` 停止。临时隧道重启后地址通常改变，适合演示与测试。

## 开发验证

安装后端开发依赖并从 `backend` 目录运行测试：

```powershell
.\.venv\Scripts\python.exe -m pip install -r backend\requirements-dev.txt
Push-Location backend
..\.venv\Scripts\python.exe -m pytest tests -q
Pop-Location
```

前端回归测试、类型检查与构建（测试复用现有依赖，不需要额外安装测试框架）：

```powershell
Push-Location frontend
npm test
npm run typecheck
npm run build
Pop-Location
```

前端回归测试覆盖统计柱状图渲染、页面轮询暂停与恢复、重复刷新合并、卸载时的定时器清理，以及风险详情切换时的请求取消和旧响应隔离。后端测试同时覆盖上传任务事务不阻塞异步请求、队列满时清理素材、执行器提交失败记录和浏览器摄像头会话释放。

## 常见问题

- **刷新页面后出现“恢复登录连接”**：身份服务可能暂时不可用，当前浏览器会话中的登录信息仍保留。恢复网络或服务后点击“重新连接并继续”返回原页面；凭据明确失效时才需要重新登录。
- **模型查询报错但任务仍在执行**：工作台的模型状态与任务进度独立刷新。任务查询失败时可点击“重试读取进度”；已提交的后台检测不依赖页面模型提示。
- **找不到 python、npm、ffmpeg 或 ffprobe**：检查安装和 PATH，重新打开终端后再次运行版本检查。
- **提示依赖缺失**：在项目根目录执行 `启动系统.cmd --install`。不要复制其他电脑的 `.venv` 或 `node_modules` 作为安装方式。
- **页面能打开但模型不可用**：检查 `storage/models/` 中是否同时有配套权重与清单；不要把通用预训练模型改名为 `best.pt`。
- **模型校验和不匹配**：重新获取匹配的两个文件，确保下载完整；不要手工修改清单中的校验值。
- **端口被占用**：停止已有的项目实例或占用 15173、18080 的程序，再启动。
- **没有显卡或 CUDA 不可用**：推理可使用 CPU；训练需显式指定 `--device cpu`，或检查 GPU 驱动和 PyTorch 环境。
- **另一台电脑打不开 localhost**：localhost 只指向访问者自己的电脑。仓库克隆后各自本地启动，或按 HTTPS 分享步骤提供公网地址。
- **摄像头打不开**：浏览器摄像头需要本机 localhost 或 HTTPS，并允许摄像头权限；RTSP 则需检查地址、凭据和网络连通性。

## 仓库发布说明

本次提交包含前后端源码、依赖清单与锁文件、数据库迁移、测试、启动和训练脚本、Docker 配置与项目文档。`.gitignore` 排除 `.venv/`、`frontend/node_modules/`、前端构建与类型检查产物、Python 缓存、运行数据库、上传素材、训练数据集、模型权重和 `.env`，不影响本机已有文件。

如需另外分发模型，应先确认分发授权，并提供匹配的 `best.pt` 与 `manifest.json`；不要上传运行数据库、账户信息或原始监控素材。

数据集、模型和演示素材的使用与分发须遵守各自授权。克隆者会生成自己的本地数据库和账户，不需要修改项目中的本机 IP 或训练清单的历史盘符。
