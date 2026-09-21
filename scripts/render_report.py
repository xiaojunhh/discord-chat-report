"""Render a Codex-authored report.json; this command does not call a model."""
from __future__ import annotations

import argparse
from collections import Counter
import html
import json
from pathlib import Path
import re
import sys

from PIL import Image, ImageDraw, ImageFont

HEADINGS = {"priority_items": "优先阅读清单", "topics": "主要话题与讨论结论", "todos": "待办事项", "confirmed": "已解决或已确认事项",
            "unresolved": "尚未解决的问题", "other": "其他重要信息"}


def load(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def validate(data, report):
    ids = {m["id"] for m in data["messages"]}
    if set(report.get("reviewed_message_ids", [])) != ids:
        raise ValueError("reviewed_message_ids 必须列出本次导出中的全部消息 ID；先读完再总结")
    for key in ("title", "overview"):
        if not isinstance(report.get(key), str) or not report[key].strip():
            raise ValueError(f"report.json 缺少 {key}")
    overview_refs = report.get("overview_message_ids", [])
    if not isinstance(overview_refs, list) or (ids and not overview_refs) or not set(overview_refs) <= ids:
        raise ValueError("概览必须引用存在的消息 ID；空记录概览不得引述不存在的消息")
    for key in HEADINGS:
        if not isinstance(report.get(key), list):
            raise ValueError(f"report.json 缺少数组 {key}")
        for item in report[key]:
            if not isinstance(item, dict) or not isinstance(item.get("text"), str):
                raise ValueError(f"{key} 项必须包含 text")
            refs = item.get("message_ids")
            if not isinstance(refs, list) or not refs or not all(isinstance(x, str) for x in refs) or not set(refs) <= ids:
                raise ValueError(f"{key} 每项必须引用存在的消息 ID")
            if key == "todos" and not all(isinstance(item.get(k), str) and item[k] for k in ("owner", "due", "status")):
                raise ValueError("待办必须填写 owner/due/status；没有明确证据时写“未明确”")
            if key == "priority_items":
                if not isinstance(item.get("importance"), int) or not 0 <= item["importance"] <= 100:
                    raise ValueError("优先阅读项 importance 必须是 0-100 整数")
                if not all(isinstance(item.get(k), str) and item[k] for k in ("relevance", "heat", "reason")):
                    raise ValueError("优先阅读项必须填写 relevance/heat/reason")
        if key == "priority_items" and report[key] != sorted(report[key], key=lambda x: x["importance"], reverse=True):
            raise ValueError("priority_items 必须按 importance 从高到低排序")
    filtered = report.get("filtered")
    if not isinstance(filtered, dict) or not isinstance(filtered.get("count"), int) or filtered["count"] < 0:
        raise ValueError("filtered 必须包含非负整数 count")
    if filtered["count"] != len(filtered.get("message_ids", [])) or not set(filtered.get("message_ids", [])) <= ids:
        raise ValueError("filtered.count 必须等于有效 message_ids 数量")
    if not isinstance(filtered.get("reasons"), list) or not all(isinstance(x, str) for x in filtered["reasons"]):
        raise ValueError("filtered.reasons 必须是字符串数组")
    if not isinstance(report.get("limitations"), list) or not all(isinstance(x, str) for x in report["limitations"]):
        raise ValueError("limitations 必须是字符串数组")


def item_text(item, todo=False):
    text = item["text"]
    if "importance" in item:
        text = (f'重要度 {item["importance"]}/100\n相关性：{item["relevance"]}\n'
                f'热度：{item["heat"]}\n入选原因：{item["reason"]}\n{text}')
    if todo:
        text += f'\n负责人：{item["owner"]}；时间要求：{item["due"]}；当前状态：{item["status"]}'
    return text


def report_lines(data, report):
    messages = data["messages"]
    period = data["period"]
    authors = len({m["author"]["id"] for m in messages})
    channel_ids = data.get("channel_ids") or [data.get("channel_id")]
    channel_label = "、".join(x for x in channel_ids if x)
    lines = [("title", report["title"]), ("meta", data["channel_name"] + " · " + channel_label),
             ("meta", f'{period["start_inclusive"]} 至 {period["end_exclusive"]}（含起点，不含终点）'),
             ("meta", f'{len(messages)} 条可恢复消息 · {authors} 位发言人 · 完整性无法确认'),
             ("notice", data["notice"]), ("heading", "概览"), ("body", report["overview"])]
    if report["overview_message_ids"]:
        lines.append(("source", "来源：" + "、".join(report["overview_message_ids"])))
    for key, title in HEADINGS.items():
        lines.append(("heading", title))
        if not report[key]:
            lines.append(("body", "本次可用记录中未明确。"))
        for item in report[key]:
            lines.extend([("body", item_text(item, key == "todos")),
                          ("source", "来源：" + "、".join(item["message_ids"]))])
    lines.append(("heading", "已过滤的低价值信息"))
    lines.append(("body", f'{report["filtered"]["count"]} 条未进入重点阅读。' +
                  (" 原因：" + "；".join(report["filtered"]["reasons"]) if report["filtered"]["reasons"] else "")))
    lines.append(("heading", "读取范围与限制"))
    for limit in report["limitations"]:
        lines.append(("body", limit))
    lines.append(("meta", "总结由 Codex 会话生成；引用可在同目录离线 HTML 中展开核对。"))
    return lines


def render_html(data, report):
    escape = html.escape
    messages = {m["id"]: m for m in data["messages"]}

    def sources(ids):
        if not ids:
            return ""
        content = []
        for mid in ids:
            m = messages[mid]
            author = m["author"].get("global_name") or m["author"].get("username") or m["author"]["id"]
            markers = []
            if m["reply_to"]:
                markers.append("引用消息 " + m["reply_to"] + ("（不在本次范围）" if not m.get("reply_in_selection") else ""))
            if m["attachments"]:
                markers.append("附件：" + "、".join(a.get("filename", "未命名") for a in m["attachments"]) + "（未解析正文）")
            if m.get("conflicting_versions"):
                markers.append("缓存有多个版本，请核对 messages.json")
            body = m["content"] or "[无文本消息]"
            for embed in m["embeds"]:
                body += "\n[卡片] " + "\n".join(str(embed[k]) for k in ("title", "description", "url") if embed.get(k))
            content.append(f'<article class="source"><strong>{escape(author)}</strong> · {escape(m["timestamp"])}'
                           f'<small>消息 ID：{escape(mid)}</small><pre>{escape(body)}</pre>'
                           f'<small>{escape("；".join(markers))}</small></article>')
        return '<details><summary>核对来源（' + str(len(ids)) + ' 条）</summary>' + ''.join(content) + '</details>'

    period = data["period"]
    channel_ids = data.get("channel_ids") or [data.get("channel_id")]
    channel_label = "、".join(x for x in channel_ids if x)
    stats = f'{len(messages)} 条可恢复消息 · {len({m["author"]["id"] for m in messages.values()})} 位发言人'
    blocks = [f'<header><p class="eyebrow">DISCORD · 本地阅读摘要</p><h1>{escape(report["title"])}</h1>'
              f'<p>{escape(data["channel_name"])} · {escape(channel_label)}</p>'
              f'<p>{escape(period["start_inclusive"])} 至 {escape(period["end_exclusive"])}<br>含起点，不含终点；时间含 UTC 偏移</p>'
              f'<p>{escape(stats)}</p></header><aside>{escape(data["notice"])}</aside>',
              '<section><h2>概览</h2><p class="text">' + escape(report["overview"]) + '</p>' + sources(report["overview_message_ids"]) + '</section>']
    for key, title in HEADINGS.items():
        body = []
        for item in report[key]:
            body.append('<div class="card"><p class="text">' + escape(item_text(item, key == "todos")) + '</p>' + sources(item["message_ids"]) + '</div>')
        blocks.append('<section><h2>' + title + '</h2>' + (''.join(body) or '<p>本次可用记录中未明确。</p>') + '</section>')
    blocks.append('<section><h2>已过滤的低价值信息</h2><p>' +
                  escape(str(report["filtered"]["count"]) + ' 条未进入重点阅读。 ' +
                         '；'.join(report["filtered"]["reasons"])) + '</p></section>')
    blocks.append('<section><h2>读取范围与限制</h2><ul>' + ''.join('<li>' + escape(x) + '</li>' for x in report["limitations"]) + '</ul></section>')
    return '''<!doctype html><html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src 'unsafe-inline'; img-src 'none'; base-uri 'none'; form-action 'none'">
<title>''' + escape(report["title"]) + '''</title><style>
*{box-sizing:border-box}body{margin:0;background:#eef2f7;color:#20314a;font:16px/1.8 system-ui,"Microsoft YaHei",sans-serif}
main{max-width:960px;margin:auto;padding:36px 20px}header{padding:28px 0}h1{font-size:clamp(28px,5vw,44px);line-height:1.35;margin:12px 0}h2{font-size:23px;margin-top:0}
.eyebrow{font-weight:700;letter-spacing:2px;color:#5265c9}header p{color:#586881}section{margin:24px 0;padding:26px;background:white;border-radius:16px}
aside{background:#fff0cd;border-left:4px solid #c78b21;padding:18px;border-radius:6px}.card+.card{border-top:1px solid #e3e8ef;margin-top:18px;padding-top:18px}
.text,pre{white-space:pre-wrap;overflow-wrap:anywhere}details{background:#f3f6fc;padding:12px;border-radius:8px}summary{cursor:pointer;color:#4055b6}
.source{border-top:1px solid #dfe6f1;padding:16px 0}small{display:block;color:#65758e;overflow-wrap:anywhere}pre{font:inherit;margin:10px 0}li{margin:8px 0}
footer{color:#65758e;font-size:14px}@media(max-width:520px){main{padding:18px 12px}section{padding:18px}header{padding:16px 4px}}
</style></head><body><main>''' + ''.join(blocks) + '<footer>本报告未联网核实群内观点。附件不自动加载，原始结构化数据保留在 messages.json。</footer></main></body></html>'


def render_png(lines, out, font_path=None, max_height=10000):
    if max_height < 600:
        raise ValueError("PNG 分页高度至少为 600 像素")
    font_path = font_path or "C:/Windows/Fonts/msyh.ttc"
    if not Path(font_path).is_file():
        raise ValueError("缺少中文字体，请用 --font 指定支持中文的字体文件")
    width, margin = 1200, 64
    sizes = {"title": 46, "heading": 34, "body": 27, "meta": 22, "notice": 25, "source": 20}
    fonts = {key: ImageFont.truetype(str(font_path), size) for key, size in sizes.items()}
    measure = ImageDraw.Draw(Image.new("RGB", (1, 1)))
    wrapped = []
    for kind, text in lines:
        font = fonts[kind]
        for paragraph in text.splitlines() or [""]:
            line = ""
            for char in paragraph:
                if line and measure.textlength(line + char, font=font) > width - margin * 2:
                    wrapped.append((kind, line))
                    line = ""
                line += char
            wrapped.append((kind, line))
        wrapped.append(("space", ""))
    pages, current, height = [], [], margin
    for kind, text in wrapped:
        line_height = 16 if kind == "space" else sizes[kind] + 17
        if height + line_height + margin > max_height:
            pages.append((current, height + margin))
            current, height = [], margin
        current.append((kind, text, height))
        height += line_height
    if current:
        pages.append((current, height + margin))
    names = []
    for number, (page, height) in enumerate(pages, 1):
        canvas = Image.new("RGB", (width, height), "#f5f7fc")
        draw = ImageDraw.Draw(canvas)
        draw.rectangle((0, 0, width, 12), fill="#5368cf")
        for kind, text, y in page:
            if kind == "space":
                continue
            color = "#52617b" if kind in ("meta", "source") else "#243655"
            if kind == "heading":
                color = "#425bc1"
            draw.text((margin, y), text, fill=color, font=fonts[kind])
        draw.text((margin, height - 42), f"{number} / {len(pages)}", fill="#52617b", font=fonts["source"])
        name = "report.png" if number == 1 else f"report-{number:02}.png"
        canvas.save(out / name)
        names.append(name)
    return names


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path)
    parser.add_argument("--font")
    parser.add_argument("--max-height", type=int, default=10000)
    args = parser.parse_args()
    out = args.directory
    data, report = load(out / "messages.json"), load(out / "report.json")
    validate(data, report)
    lines = report_lines(data, report)
    names = render_png(lines, out, args.font, args.max_height)
    if len(names) > 1:
        split_notice = f"内容超过单图高度上限 {args.max_height} 像素，分为 {len(names)} 张；按 report.png、report-02.png 等顺序阅读。"
        report = {**report, "limitations": [*report["limitations"], split_notice]}
        lines = report_lines(data, report)
    markdown = []
    for kind, text in lines:
        prefix = "# " if kind == "title" else "## " if kind == "heading" else "> " if kind == "notice" else ""
        markdown.append(prefix + text)
    (out / "summary.md").write_text("\n\n".join(markdown) + "\n", encoding="utf-8")
    (out / "index.html").write_text(render_html(data, report), encoding="utf-8")
    (out / "render-verification.json").write_text(json.dumps({"messages": len(data["messages"]),
        "authors": len({m["author"]["id"] for m in data["messages"]}),
        "all_message_ids_reviewed": True, "references_exist": True,
        "semantic_support": "需由总结者逐条核对，程序只验证引用 ID 存在",
        "png_files": names, "png_split": len(names) > 1,
        "visual_review": "pending"}, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"directory": str(out.resolve()), "png_files": names}, ensure_ascii=False))


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError, KeyError, TypeError) as error:
        print(f"渲染失败：{error}", file=sys.stderr)
        sys.exit(1)
