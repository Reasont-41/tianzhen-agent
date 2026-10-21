# GitHub 发布说明

比赛要求本地部署作品提供 GitHub 开源项目链接，仓库中需包含部署方法和项目全部代码、数据文件。下面是建议流程。

## 一、发布前检查

- [ ] 确认团队同意开源；代码、知识库和实验产物可以公开。
- [ ] 检查所有文件中是否有姓名、手机号、身份证号、学号、指导教师等个人信息。
- [ ] 检查是否有 API Key、Cookie、Token。本项目只从环境变量读取密钥，代码中不应出现。
- [ ] 确认 `archive/旧版技术附录/` 不进入公开仓库（已在 `.gitignore` 中排除）。
- [ ] 确认 `delivery/` 不进入公开仓库（提交包体积较大，已在 `.gitignore` 中排除）。
- [ ] 确认 `app/artifacts/mobilenet_v3_small-047dcff4.pth`（约 9.9 MB）和 `dataset_manifest.json`（约 1.3 MB）可以公开；原始图片不随包提供。
- [ ] 如果知识库中的药剂资料来自第三方，确认公开方式不违反来源条款；当前记录为团队整理的公开农技资料，仍建议在 README 中注明来源和待核验状态。

## 二、创建仓库

在 GitHub 上创建一个空仓库（不要勾选自动生成 README、.gitignore 或 License），记下仓库地址，例如：

```text
https://github.com/你的账号/tianzhen-agent
```

## 三、本地初始化并推送

在项目根目录执行（Windows PowerShell / Git Bash 均可）：

```bash
git init
git add .
git commit -m "田诊卫士智能体版：大模型规划 + 规则引擎否决"
git branch -M main
git remote add origin https://github.com/你的账号/tianzhen-agent.git
git push -u origin main
```

如果默认分支不是 `main`，按 GitHub 页面提示调整。

## 四、检查仓库

1. 在无痕浏览器打开仓库，确认 README 能正常显示、图片能加载。
2. 确认以下文件在仓库中：
   - `README.md`
   - `app/`（含 `core/agent.py`、`api/main.py`、`web/agent.html`、`data/`、`artifacts/`）
   - `tests/`（60 项测试）
   - `tools/`（构建与校验脚本）
   - `benchmarks/`
   - `Dockerfile`、`docker-compose.yml`
   - `app/requirements.txt`、`app/requirements-dev.txt`
3. 确认以下目录不在仓库中：
   - `.build/`
   - `.venv/`
   - `__pycache__/`
   - `.pytest_cache/`
   - `data_raw/`
   - `archive/`
   - `delivery/`
4. 如果 GitHub 提示大文件，检查是否有超过 100 MB 的文件；本项目不应有。模型权重约 9.9 MB，可直接提交。

## 五、把链接填回提交材料

1. 打开 `materials/智能体版-提交材料/06-作品访问方式.txt`，把 `【待填写：https://github.com/...】` 替换为真实链接。
2. 确认 README 中的启动命令在干净环境中可执行。
3. 如果仓库使用 Release 提供模型权重，把下载说明补充到 `06-作品访问方式.txt`。
4. 重新生成提交 PDF（如果链接也出现在 PDF 中）：
   ```powershell
   python tools/build_submission_docs.py
   ```

## 六、可选：公网体验链接

如果能把服务部署到公网，建议提供：

- 体验链接
- 测试账号（如需要）
- 可复现的启动命令
- 数据与安全边界说明

但注意：

- 不要把 API Key 写进前端或仓库；用服务端环境变量。
- 公网部署前确认没有开放不必要的端口和调试接口。
- 如果使用第三方大模型 API，遵守平台条款，不上传个人敏感信息。
- 目前项目未完成 Docker/公网/微信真机验收，材料中不要标记为已完成。

## 七、常见问题

**Q：模型权重太大，GitHub 拒绝推送？**
A：本项目权重约 9.9 MB，不应超限。如果未来换更大模型，改用 Release 或 Git LFS，并在 README 中写清楚下载步骤。

**Q：原始叶片图片要不要上传？**
A：不必须。PlantVillage 是公开数据集，README 已给出来源和准备脚本；仓库保留 `dataset_manifest.json`（路径、SHA-256、标签、划分）即可。如果评委要求全部数据，再补充下载说明或 Release。

**Q：API Key 会不会被提交？**
A：不会。代码只从 `TIANZHEN_LLM_API_KEY` 或 `DEEPSEEK_API_KEY` 环境变量读取；提交前仍建议全局搜索 `sk-`、`api_key`、`token` 再确认。
