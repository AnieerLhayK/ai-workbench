# ai-workbench

主要帮助个人工作的辅助工具与成果集合。能力有限，不保证其他机器上的普适可用性。
0.2 版提供 **muti-ai** 原生 Qt 窗口：两个独立的 Commander/Hermes 真实控制开关，
以及显式开启的模拟演示。Workspace 保持源码权威。

本公开仓库使用独立投影历史。自有内容采用 [MIT](LICENSE)，依赖保留各自许可。
Issues 开放反馈，不承诺通用支持；外部 PR 先迁回 Workspace 审阅，再由登记发布器
重新生成同步。本次不提供安装包。

配套的 [Frame-for-AI-workspace](https://github.com/AnieerLhayK/Frame-for-AI-workspace)
展示这些工具背后的工作区组织与维护方法，可用来参考自己的 Agent 辅助工作区建设。

[English](README.md)

## 使用

本机桌面入口为 **muti-ai**。同一可滚动窗口依次显示 ChatGPT、Claude、Codex、
Hermes、OpenCode 折叠分类。展开 ChatGPT 查看 Remote Desktop Commander，
展开 Hermes 查看 Hermes Bot；空分类显示“暂无启动器”。允许同时展开多个分类。
首次展开 ChatGPT、Hermes，之后记住上次选择；收起的标题继续显示状态和错误提示。
分类标题支持 Tab 聚焦和 Enter、Space 操作，折叠不会控制服务。打开窗口读取当前状态，
关闭窗口保留服务及已提交的操作；重复打开唤回现有窗口。
设置按钮选择深色或浅色模式并记住选择，不提供主题切换快捷键。

每行显示已停止、启动中、运行中、停止中、失败或状态未确认。
等待时只禁用该行开关。进程仍在但连接异常时保持开启，并显示连接提示。
仅检测到 npx 安装进程不代表 Commander 已可用；账户授权由用户在供应方浏览器中完成。
启动失败会显示安全的原因类别和退出码。验证码过期时使用重新开启后打开的新页面；
未知错误不会被直接认定为授权失败，原始账户输出不会写入状态或日志。
存在 HTTP(S) 代理环境变量时，Commander 子进程会启用现代 Node 的环境代理支持，
保留显式 Node 代理设置；不修改全局环境或 Hermes 配置。

## 快速开始：模拟模式

使用 Python 3.13+ 与 **PySide6 6.9.2**，依照宿主存储规范在独立环境中安装依赖：

```powershell
python -m pip install '.[dev]'
python -B scripts/launch.py --demo
```

模拟模式无需供应方账户，不启动真实服务。真实控制需要 Windows、已有 Node/npm
与 Hermes 环境；Commander 按需通过 npx 下载 `@latest`，工作台不安装 Hermes。

把[占位配置示例](examples/config.example.json)复制到克隆目录外，将每项替换为本机
绝对路径。数据与凭据均留在外部目录。`pythonw` 必须能使用 PySide6；Hermes 路径
指向其已有运行环境与 profile。在本目录运行：

```powershell
./scripts/Start-Workbench.ps1 -Config <external-config.json> -PythonExe python
./scripts/Start-Workbench.ps1 -Demo -PythonExe python
```

其他 shell 可设置 PYTHONPATH=src，再运行 `python -B -m ai_workbench --demo`。
真实模式必须提供外部本机配置和已有服务环境，配置缺失不会静默切换模拟。
部署、进程识别和停止语义见[本机控制说明](docs/local-controls.md)。

隐藏桌面入口由 [Install-Local.ps1](scripts/Install-Local.ps1)接收明确的数据、桌面目录
与运行环境路径创建；已有目标会被拒绝，不安装依赖。快捷方式指向源码，因此部署后
保留克隆目录的原路径。Commander 使用[官方浏览器授权流程](https://github.com/wonderwhy-er/DesktopCommanderMCP/blob/main/src/remote-device/README.md)。
在聊天客户端启用或选择 Desktop Commander Remote，并授权同一设备；聊天客户端
可用性和供应方权限需分别满足。Hermes 授权沿用现有配置。工作台不读取、复制或重置凭据。

## 维护与验证

入口：[AGENTS.md](AGENTS.md)、[维护契约](shared/maintenance.md)、
[开发工作流](skills/ai-workbench-maintainer/references/development.md)。
使用 pytest 与 QtTest，临时输出必须使用宿主批准的 staging 路径：

```powershell
python -B -m pytest -q -p no:cacheprovider --basetemp <approved-staging-tests> tests
```

GUI 验证检查原生窗口、两个主题、最小尺寸与显示缩放，浏览器检查不适用。
交付证据应区分模拟测试、真实进程启停和客户端端到端连接。

## 本地投影

[内容契约](projection-contract.json)与[生成检查器](scripts/projection.py)
只导出源码、测试、自有资源和可移植维护文档；排除宿主台账、本机配置、
凭据、运行日志及旧入口归档。

```powershell
python -B scripts/projection.py export --destination <empty-staging-directory>
python -B scripts/projection.py check --destination <preview-directory>
```

`PROJECTION_SOURCE.json` 只记录包、相对源码位置和 Workspace 提交，不含私人仓库
地址或机器路径。本地预览可使用 null 提交；公开导出必须标明审阅后的来源提交。
在安装或测试产生构建文件之前，检查新克隆的公开边界：

```powershell
python -B scripts/projection.py check --destination . --require-revision
```

Windows CI 使用 Python 3.13、PySide6 6.9.2 和 Qt offscreen 执行边界检查与模拟测试，
不持有供应方凭据，不启动真实服务。

已有预览通过检查且清单相同时，可用 `export --refresh` 更新。导出目录独立运行
显式模拟模式和测试。分类在可移植 Catalog Module 中登记，不在运行时发现宿主平台。
新增启动器、安装包与 Pi 接入留待后续。当前没有 Pi 应用；实际加入后，会在对应应用
文档与本 README 注明上游仓库、用途和适用依赖许可。
