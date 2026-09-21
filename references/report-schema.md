# report.json 格式

这是 Codex 会话阅读导出消息后撰写的结构化总结；脚本只验证和渲染。

```json
{
  "title": "频道中文阅读报告",
  "overview": "简短概览，说明讨论重点与证据边界。",
  "overview_message_ids": ["实际消息ID"],
  "reviewed_message_ids": ["全部已读消息ID，不能省略"],
  "priority_items": [{
    "text": "用户最值得先看的信息。",
    "importance": 85,
    "relevance": "与用户关注方向的关系",
    "heat": "可核对的回复、参与者或反应数据；没有就写无可用数据",
    "reason": "为什么值得占用阅读时间",
    "message_ids": ["实际消息ID"]
  }],
  "topics": [{"text": "话题与结论，区分观点和事实。", "message_ids": ["实际消息ID"]}],
  "todos": [{"text": "待办事项", "owner": "未明确", "due": "未明确", "status": "未明确", "message_ids": ["实际消息ID"]}],
  "confirmed": [],
  "unresolved": [],
  "other": [],
  "filtered": {"count": 1, "message_ids": ["低价值消息ID"], "reasons": ["纯图片且未解析正文"]},
  "limitations": ["本地缓存不代表完整历史。"]
}
```

`priority_items` 必须按 importance 从高到低排列。热度只是排序信号，不能覆盖信息价值：高反应的空图片不能自动排在有实际结论的低热内容前面。`confirmed/unresolved/other` 的每一项与 topics 相同，包含 text 和非空 message_ids。所有消息仍须出现在 reviewed_message_ids；filtered 只表示不进入重点阅读，不表示没有读过。
没有证据支持的栏目使用空数组；渲染器显示“本次可用记录中未明确”。零消息时只写读取范围说明，不编造概览和引用。

`messages.json` 保留原消息 ID、频道 ID、作者 ID/昵称、UTC 时间、文本、附件元信息、卡片文字、mention ID、reply_to、冲突版本和文件 SHA256/片段偏移。`json_offset` 相对于对应解压载荷；嵌套对象共享外层 JSON 片段起点。`payload_offset` 是原文件内 gzip 起点，普通 JSON 为 0。未复制整份缓存至报告。

`verification.json` 记录文件读取状态、错误码、变化检测和恢复计数。它证明读取过程，不能证明 Discord 服务端消息完整。运行时文件没有变化也不等于多个缓存文件构成事务级快照。
