# 田诊卫士 · 智能体版

“码上智农，电亮未来”智能体创新应用比赛 · 智慧农业方向

面向小农户的番茄病害诊断与安全用药智能体。大模型负责理解、追问和规划工具，确定性规则引擎负责逐条否决；所有用药条目来自知识库记录，天气窗口始终标记为模拟数据。

本目录是在原“田诊卫士”农业决策辅助软件上的智能体改造版。本版新增对话式智能体、工具调用、会话管理和离线规划回退，并保留原有的视觉诊断、规则校验、来源展示与施药窗口能力。

## 这个版本新增了什么

- **对话式入口** `/agent`：多轮对话、叶片照片上传、工具调用轨迹、候选记录/逐条校验/模拟窗口卡片。
- **大模型工具调用**：`get_leaf_diagnosis`、`search_disease`、`get_candidate_records`、`validate_prescription`、`get_spray_window`、`ask_user`、`get_kb_status`。
- **安全闭环**：大模型不直接生成农药剂量；任何用药建议必须先经过 `ConstraintEngine`。`blocked` 条目不得推荐，`needs_review` 必须标注“待核验/需补充”。
- **本地规划回退**：未配置大模型密钥时，使用同一组工具执行固定计划；离线可演示、可自动化测试，不会白屏。
- **测试**：60 项自动化测试通过（原有 51 项 + 智能体 9 项）。

## 快速运行

建议 Python 3.12 或 3.13，使用独立环境。本次实际测试为 Python 3.13.9；依赖版本在 `app/requirements.txt`。

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install torch==2.12.0+cpu torchvision==0.27.0 --index-url https://download.pytorch.org/whl/cpu
.\.venv\Scripts\python.exe -m pip install -r app/requirements.txt --extra-index-url https://download.pytorch.org/whl/cpu
.\.venv\Scripts\python.exe tools/verify_package.py
.\.venv\Scripts\python.exe -m uvicorn app.api.main:app --host 127.0.0.1 --port 8000
```

浏览器访问：

- 表单版：`http://127.0.0.1:8000/`
- 智能体对话版：`http://127.0.0.1:8000/agent`
- 接口文档：`http://127.0.0.1:8000/docs`

已有环境可执行“启动本地演示.ps1”。首次安装依赖需要联网，模型推理不自动下载文件。

## 配置大模型

默认使用 DeepSeek 的 OpenAI 兼容接口。启动服务前设置环境变量：

```powershell
$env:TIANZHEN_LLM_API_KEY="你的密钥"
# 如果本机已经设置 DEEPSEEK_API_KEY，也可以直接复用，无需重复设置
$env:TIANZHEN_LLM_BASE_URL="https://api.deepseek.com/v1"
$env:TIANZHEN_LLM_MODEL="deepseek-chat"
.\.venv\Scripts\python.exe -m uvicorn app.api.main:app --host 127.0.0.1 --port 8000
```

也支持通义千问、智谱等 OpenAI 兼容接口：把 `TIANZHEN_LLM_BASE_URL`、`TIANZHEN_LLM_API_KEY`、`TIANZHEN_LLM_MODEL` 换成对应平台的值即可。密钥只从环境变量读取，不写入代码、响应或日志。

不配置密钥时，系统自动进入**本地规划模式**：同一组工具按固定顺序执行，适合离线演示和评审。设置 `TIANZHEN_LLM_DISABLE=1` 可以强制关闭大模型模式。

## 智能体工具

| 工具 | 作用 | 安全约束 |
|---|---|---|
| `get_leaf_diagnosis` | 读取本次会话叶片照片的视觉诊断结果 | 概率不是确诊；健康照片不生成用药 |
| `search_disease` | 把口语症状映射到知识库候选病害 | 检索分不是概率；候选接近时追问 |
| `get_candidate_records` | 读取某作物某病害的药剂记录 | 只能从这些记录中选药；待核验单独标注 |
| `validate_prescription` | 逐条检查身份、剂量、间隔期、次数等 | `blocked` 不得推荐；`needs_review` 必须标注 |
| `get_spray_window` | 按药剂计算未来施药窗口 | 始终标记模拟天气，不是当地预报 |
| `ask_user` | 信息不足或图文冲突时追问 | 调用后本轮结束，不猜测 |
| `get_kb_status` | 读取知识库覆盖范围和核验状态 | 不把标准比对说成登记核验 |

## 运行模式

- **大模型规划模式**：配置密钥后，模型决定调用哪些工具、是否追问、如何组织解释；工具结果是事实来源。
- **本地规划模式**：未配置密钥或接口失败时，按“检索 → 候选 → 校验 → 窗口”执行固定计划；前端会显示“本地规划模式”。

两种模式共用同一套工具、规则引擎和安全边界；区别只在“谁来决定调用顺序”。

## 本版实跑结果

| 项目 | 结果 |
|---|---|
| 原图数量 | 5452 |
| 去除精确重复 | 14 |
| 保留图片 | 5438 |
| 训练 / 验证 / 测试 | 3262 / 1088 / 1088 |
| 固定测试集准确率 | 96.88% |
| 验证集确定的阈值 | 0.941003 |
| 测试集拒识率 | 6.53% |
| 接受样本准确率 | 98.82% |
| 固定标签功能基准 | 36/36 裁决一致 |
| 自动化测试 | 60 项全部通过 |

视觉指标来自受控公开叶片数据，阈值不使用测试集选择。精确去重不能排除所有近重复或来源相关性。功能基准使用开发者构造的虚构记录，不是专家标注的真实农业处方。不得外推为真实田间安全率或真实大模型错误率。

## 数据事实与使用边界

知识库 40 条记录中，6 条为团队比对 GB/T 8321 系列标准，34 条仍为待核验种子资料；40 条尚无具体产品登记证号。标准比对不能等同于全量现行登记核验。程序在当前竞赛模式始终返回 `ready_for_field_use=false`。

本次未开展专家独立核验、真实访谈、田间试用、公网 4G、微信真机或 Docker 构建验收。不得将这些事项标记为已完成。模拟天气和经验规则也需在实际应用前另行验证。

实际用药以具体产品标签、现行登记信息和当地植保指导为准。

## 复现实验

```powershell
python -m pip install -r app/requirements-dev.txt
python -m pytest -q
python -m app.experiment_e2
python tools/prepare_data.py
python -m app.train_diagnosis
python -m app.analyze
```

本地已有原图可以用 `python -m app.train_diagnosis --data-dir <raw/color目录>`。数据准备脚本不会自动删除或覆盖非空未知目录。训练时读取失败会报错，不截断标签来对齐特征。

`app/artifacts` 包括分类头、骨干权重、`dataset_manifest.json`、`test_predictions.json`、`diagnosis_metrics.json` 和 `experiment_e2.json`。原始图片未随包提供；固定样本清单保留每张图片的相对路径、SHA-256、标签与划分。`tools/prepare_weights.py` 是显式联网补权重工具，正常推理无需执行。

## 提交材料

比赛材料位于：

- `materials/智能体版-提交材料/`：团队分工说明、AI 工具与开发说明、原创承诺书填写说明、提交清单、作品说明、报名简介。
- `presentation/田诊卫士-智能体版-答辩.pptx`：比赛答辩稿（15 页以内）。
- `materials/田诊卫士-智能体版-功能演示.mp4`：2 分钟内功能演示。
- `delivery/`：按报名群格式改名后即可压缩发送的提交包（本地目录，已通过 `.gitignore` 排除，不在公开仓库中）。
- `GITHUB-发布说明.md`：创建公开仓库并把链接填回 `06-作品访问方式.txt` 的步骤。
- `reports/screenshots/agent-*.png`：本次实际浏览器截图。
- `reports/`：智能体测试报告、运行验证和本版截图。

旧版本材料保存在本地 `archive/旧版技术附录/`，已通过 `.gitignore` 排除，不进入公开仓库；正式提交时请使用“智能体版”材料。公开仓库保留代码、测试、知识库、模型权重和实验产物。

## 目录结构

```text
app/
  api/main.py            # FastAPI：表单接口 + 智能体接口
  core/
    agent.py             # 智能体运行时、工具调用、回退规划、会话管理
    constraint_engine.py # 确定性规则引擎
    diagnosis.py         # 视觉诊断
    pipeline.py          # 生成—校验—溯源闭环
    retrieval.py         # 病害/药剂检索
    spray_window.py      # 施药窗口
  data/                  # 知识库 JSON
  web/
    index.html           # 表单版
    agent.html           # 对话式智能体版
tests/                   # 60 项自动化测试
materials/               # 比赛材料与演示视频
presentation/            # PPT / PDF
reports/                 # 测试、截图、运行验证
tools/                   # 数据准备、打包、校验脚本
```

## 引用

- Howard A 等，Searching for MobileNetV3，ICCV，2019。
- Hughes D P、Salathé M，An open access repository of images on plant health，2015；PlantVillage-Dataset 公开仓库。
- GB/T 8321.9—2009、GB/T 8321.10—2018，团队已比对的依据范围见各记录 `verified_basis`。
- OpenAI-compatible Chat Completions / tool calling 接口规范；本版默认使用 DeepSeek，可替换为其他国内合规平台。
