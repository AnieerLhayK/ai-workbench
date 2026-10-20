# e-Chatter：Windows 11 x64

这是可独立构建的受管源码快照。ai-workbench 是唯一开发源；请在那里修复，再手动
晋升新版本，不直接维护此副本。SNAPSHOT.json 记录源码提交、文件哈希、依赖版本、
工程资源来源、验收缺项和同一份 Windows ZIP 的身份。

## 下载使用

解压完整 ZIP，打开 e-Chatter.exe，无需安装 Python 或 Node。自行安装所选 Agent，
在设置中连接自己的 Codex 账号，或 DeepSeek Harness 0.2.1-rc.2 的官方账号／API Key。
未验证的 Harness 版本会停止连接。Codex 需要支持受限 app-server 配置，详见
[应用说明](docs/e-chatter.md)。缺少 Agent 不影响打开界面。

首次启动没有角色，可导入自己的 SKILL.md 角色目录。默认资料库为
%LOCALAPPDATA%/ai-workbench/e-chatter，--data 可指定已有资料库。升级仅替换程序；
保留完整旧程序目录以备回退，回退不会自动降级资料。包内不含个人角色或凭据。

## 独立构建和验证

维护者需 Python 3.13+、Node 22+ 和 npm。创建外部虚拟环境，执行
`python -m pip install ".[dev]"`。在 frontend/e-chatter 执行 `npm ci`、`npm test`、
`npm run build`，再从应用目录执行：

```powershell
python -B -m pytest -q -p no:cacheprovider tests --basetemp <外部测试目录>
python -B scripts/launch_e_chatter.py --demo
python -B scripts/build_e_chatter.py --staging <外部构建目录> --output <外部发行目录>
```

E_CHATTER_RUN_NATIVE=1 启用原生 Qt 测试；E_CHATTER_RUN_DSH=1 启用官方 Harness
连接本机合成端点的三项测试，不能代替真实账号／Key 验收。正式稳定版必须完成
[发行验收](docs/release-verification.md)，缺项时仅交付候选版。

## 稳定版同步

由 ai-workbench 的 scripts/promote_e_chatter.py 对明确提交先预览、后执行；版本不可
覆盖。候选版和稳定版分别登记。两个发行端复用同一 ZIP 和 SHA-256，不分别重建。
此快照不执行远端同步或 Release 发布。
