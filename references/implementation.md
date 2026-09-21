# 实现、来源与兼容范围

## 研究记录（2026-09-21）

- 参考流程：[Tina2088/wecom-group-report](https://github.com/Tina2088/wecom-group-report)，本机原项目提交 `f01fc5ab3197ffe48d5db0e8ac1c63a4ed73cf92`。只参考消息导出→Codex 总结→离线报告流程；没有复制微信解密、内存扫描或报告代码。
- 缓存可行性研究：[openclaw/discrawl](https://github.com/openclaw/discrawl/tree/ff4c068e49710772abd323b44398f6cb4eaad5b5)，MIT，固定研究提交 `ff4c068e49710772abd323b44398f6cb4eaad5b5`。检查 `internal/discorddesktop/scan.go`、`payload.go`、`snapshot.go` 与 `docs/commands/wiretap.md`：具有真实的本地 JSON/gzip 扫描实现，明确不保证完整记录。没有安装或运行该项目，也未逐行复制其代码；本项目使用 Python 独立实现窄范围读取器。
- Discord 消息字段：[官方 Message 文档](https://docs.discord.com/developers/resources/message)。保留实际字段，不凭昵称合并用户。
- 普通账号自动 API 调用的边界：[Discord selfbot 说明](https://support.discord.com/hc/en-us/articles/115002192352-Automated-User-Accounts-Self-Bots)。本项目不需要用户 Token 或 Bot。
- [Discord 数据包](https://support.discord.com/hc/en-us/articles/360004957991-Your-Discord-Data-Package) 主要提供本人发送的消息，不能替代完整群聊讨论，故未采用为默认输入。

## 本机已确认

- Windows 11，系统版本 `10.0.26340`。
- Discord Stable 路径 `app-1.0.9258/Discord.exe`，保持运行时可读 HTTP cache。
- Python 3.13.3、Pillow 12.1.1，Windows 微软雅黑字体可用。
- 磁盘结构是 Chromium `Cache/Cache_Data/data_0...data_3` 与 `f_*` 文件；正文存在于部分 gzip 数据片段。
- Windows CreateFileW 以 GENERIC_READ + FILE_SHARE_READ/WRITE/DELETE 打开，解决 Python 普通文件打开遇到的共享锁；没有写客户端文件。
- 原始字节只保存在内存，计算 SHA256、记录读取前后大小/修改时间。没有密钥、解密库或临时明文数据库，因而不需要虚构解密/WAL 清理流程。

## 能力边界

1. 这是有限的 JSON/gzip 片段恢复器，不是完整 Chromium Cache、LevelDB/SSTable 解析器。Brotli/zstd、跨块碎片、Snappy、缺失或截断的 gzip、未落盘的内存消息可能无法恢复。
2. 只检查单个配置目录的 Cache/IndexedDB，排除 Cookie/Local Storage 等凭证位置。缓存可能含同机曾登录的历史账户残留；脚本不能独立验证登录账户。必须结合当前客户端与目标频道核对，不自动扫描其他配置目录。
3. 为定位消息，必须扫描候选缓存文件，再按指定频道与时间筛选；只有所选消息进入 messages.json。不能做到不读候选文件的其他字节；若对此有严格要求，应使用经授权的预导出数据。
4. 单文件上限 64 MiB，单 JSON 片段上限 2 MiB；跳过和压缩失败会计数。未使用备份卷、权限提升或绕过文件权限。
5. 当前消息 ID 去重，保留不同正文/元信息版本；优先明确较晚的 edited_timestamp。同时间戳的冲突无法确定真伪，保留供核对，不能当作编辑历史的完整还原。
6. 论坛只有实际缓存的 thread parent_id 才能证明归属。只有首帖不能宣称读完回复；未缓存的帖子不能自动枚举。
7. 正常 UI 打开和滚动频道可能由 Discord 联网下载更多数据，并改变未读状态。读取器本身无网络调用；报告应说明本次是否进行了 UI 加载。
8. 不下载附件。卡片是消息内可读标题/描述/链接，不代表已核实外部文章。图片/视频/音频不做视觉或听觉推断。
9. 人工总结由当前 Codex 会话完成，无独立无人值守总结命令。单独运行 Python 只能导出/渲染，不能生成语义总结。

## 故障排查

- 0 条：检查是否选中论坛父频道；尝试 `--include-threads`。正常打开目标帖子、等待正文出现，再重试新目录；仍为 0 时保留诊断，不宣称没有聊天。
- 频道名找不到：使用“复制频道链接”。不要使用头像 CDN 地址；链接目标必须是 `discord.com/channels/...`。
- 同名：改用稳定 ID；不模糊选第一个。
- 字体错误：`--font` 指定支持中文的本机 TTF/TTC。
- 读锁/变化：看 verification 文件；可让客户端完成加载后重试。运行中的缓存无法保证事务一致。
- PNG 多张：高度默认最多 10000 px，编号续接；不静默裁剪。可 `--max-height` 调整。
- 真正全量历史/所有新帖：当前缓存方式无法保证；必须另行选择被授权的数据源或正常 UI 加载并标明覆盖范围。
