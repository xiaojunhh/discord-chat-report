# discord-chat-report

[English](README_EN.md) | **简体中文**

给普通 Discord 会员使用的本地 Codex skill：读取指定频道/论坛的可恢复缓存消息，由当前 Codex 会话生成中文总结、离线 HTML、PNG 长图与来源数据。

**状态：本地缓存恢复原型。不是完整聊天历史备份工具。** 读取器不调用 Discord API、不需要 Bot/用户 Token；Python 命令本身不具备 AI 总结能力。

## 环境与安装

本机验证环境为 Windows 11 + Discord Stable 1.0.9258 + Python 3.13。其他系统与客户端版本尚未验证。

```powershell
python -m pip install -r scripts/requirements.txt
python -m unittest discover -s tests -v
python scripts/read_cache.py --list-channels
```

把本项目作为 Codex 的技能文件夹使用；在会话中指定本目录的 `SKILL.md`，或按宿主的技能安装方式安装整个文件夹。先在项目内使用即可，不必修改全局设置。

## 用法

```powershell
# 默认24小时，显式可选48/72小时。RUN_NAME 每次换一个新目录。
python scripts/read_cache.py --channel "频道链接或ID" --out reports/RUN_NAME
python scripts/read_cache.py --channel "频道链接或ID" --hours 48 --include-threads --out reports/RUN_NAME_48H

# 固定时间与时区，含起点、不含终点。
python scripts/read_cache.py --channel "频道链接或ID" --start "2026-09-20T09:00:00+08:00" --end "2026-09-21T09:00:00+08:00" --out reports/RUN_NAME_RANGE
```

接下来让 Codex 完整阅读 `messages.json`，按 [report.json 格式](references/report-schema.md) 写总结，再运行：

```powershell
python scripts/render_report.py reports/RUN_NAME
```

直接双击 `index.html` 即可离线查看、展开来源。分享 `report.png`；内容长时同时分享编号续图。真实报告都放在 Git 忽略的 `reports/` 目录中。

论坛需要展开帖子才可能把回复写入缓存。正常客户端加载与磁盘读取是不同步骤；未加载/未缓存的内容不能靠 skill 凭空恢复。

## 输出

`messages.json`、`messages.txt`、`report.json`、`summary.md`、`index.html`、`report.png`，加 `verification.json` 和 `render-verification.json`。HTML 无外部资源、正确转义文本，来源默认折叠。所有重要结论须关联实际消息 ID。

## 发布到 GitHub

建议仓库名 `discord-chat-report`。只提交本项目源码、测试与虚构示例；不要提交上层企业微信项目或真实报告。发布前检查 `git diff --cached --stat` 与完整暂存差异，确认没有聊天正文、密钥或缓存。

```powershell
git init
git add .gitignore SKILL.md README.md README_EN.md LICENSE agents scripts references tests
git diff --cached --stat
git commit -m "Add Discord local cache report skill"
git branch -M main
# 在自己的 GitHub 建同名空仓库后，配置真实远端并推送。
git remote add origin https://github.com/YOUR_ACCOUNT/discord-chat-report.git
git push -u origin main
```

源码和兼容限制详见 [实现记录](references/implementation.md)。本项目不自动公开报告、不发送频道消息。
