"""Offline, read-only recovery of Discord JSON from desktop cache fragments.

This is a bounded fragment carver, not a complete Chromium/LevelDB reader.
No network, credential lookup, client injection, or original-file writes.
"""
from __future__ import annotations

import argparse
import collections
import ctypes
import hashlib
import json
import os
from pathlib import Path
import re
import sys
from datetime import datetime, timedelta, timezone
import zlib

LIMIT = 64 * 1024 * 1024
JSON_LIMIT = 2 * 1024 * 1024
ID = re.compile(r"[0-9]{12,24}\Z")
NOTICE = ("仅包含本地缓存可恢复的消息，完整性无法确认。缓存可能过期、被淘汰、"
          "压缩或分块；没有读到消息不代表该时段没有聊天。未解析媒体正文，未联网补齐。")


def iso(value: str) -> datetime:
    dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if dt.tzinfo is None:
        raise ValueError("时间必须包含时区，例如 2026-09-21T09:00:00+08:00")
    return dt.astimezone(timezone.utc)


def valid_id(value) -> bool:
    return isinstance(value, str) and ID.fullmatch(value) is not None


def read_shared(path: Path) -> bytes:
    """Windows Chromium allows reads if FILE_SHARE_DELETE is also requested."""
    if os.name != "nt":
        with path.open("rb") as stream:
            return stream.read(LIMIT + 1)
    from ctypes import wintypes as w
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.CreateFileW.argtypes = [w.LPCWSTR, w.DWORD, w.DWORD, w.LPVOID,
                                  w.DWORD, w.DWORD, w.HANDLE]
    kernel.CreateFileW.restype = w.HANDLE
    kernel.ReadFile.argtypes = [w.HANDLE, w.LPVOID, w.DWORD,
                               ctypes.POINTER(w.DWORD), w.LPVOID]
    kernel.CloseHandle.argtypes = [w.HANDLE]
    handle = kernel.CreateFileW(str(path), 0x80000000, 7, None, 3, 0, None)
    if handle == w.HANDLE(-1).value:
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        chunks, total = [], 0
        while total <= LIMIT:
            size = min(1024 * 1024, LIMIT + 1 - total)
            if not size:
                break
            buffer = ctypes.create_string_buffer(size)
            count = w.DWORD()
            if not kernel.ReadFile(handle, buffer, size, ctypes.byref(count), None):
                raise ctypes.WinError(ctypes.get_last_error())
            if not count.value:
                break
            chunks.append(buffer.raw[:count.value])
            total += count.value
        return b"".join(chunks)
    finally:
        kernel.CloseHandle(handle)


def objects(data: bytes):
    """Recover valid UTF-8 JSON objects; retain offsets into the source payload."""
    text = data.decode("utf-8", errors="surrogateescape")
    decoder = json.JSONDecoder()
    end = 0
    for start in re.finditer(r'\{\s*"', text):
        if start.start() < end:
            continue
        try:
            value, length = decoder.raw_decode(text[start.start():start.start() + JSON_LIMIT])
            raw = text[start.start():start.start() + length]
            raw.encode("utf-8")  # Reject fragments containing undecodable bytes.
        except (ValueError, UnicodeError, RecursionError):
            continue
        end = start.start() + length
        offset = len(text[:start.start()].encode("utf-8", errors="surrogateescape"))
        yield value, offset


def payloads(data: bytes, counters: collections.Counter):
    yield data, "plain", 0
    for match in re.finditer(b"\x1f\x8b\x08", data):
        try:
            decoder = zlib.decompressobj(31)
            unpacked = decoder.decompress(data[match.start():], LIMIT + 1)
            if not decoder.eof or len(unpacked) > LIMIT:
                counters["gzip_incomplete_or_oversize"] += 1
                continue
        except zlib.error:
            counters["gzip_invalid"] += 1
            continue
        counters["gzip_decoded"] += 1
        yield unpacked, "gzip", match.start()


def walk(value):
    pending = [value]
    while pending:
        item = pending.pop()
        if isinstance(item, dict):
            yield item
            pending.extend(v for v in item.values() if isinstance(v, (dict, list)))
        elif isinstance(item, list):
            pending.extend(item)


def normalize(raw):
    author = raw.get("author")
    if not (valid_id(raw.get("id")) and valid_id(raw.get("channel_id"))
            and isinstance(author, dict) and valid_id(author.get("id"))
            and isinstance(raw.get("content"), str)):
        return None
    try:
        stamp = iso(raw["timestamp"]).isoformat()
        edited = iso(raw["edited_timestamp"]).isoformat() if raw.get("edited_timestamp") else None
    except (KeyError, ValueError, TypeError, AttributeError):
        return None
    ref = raw.get("message_reference") or {}
    if not isinstance(ref, dict):
        ref = {}
    attachments = raw.get("attachments") or []
    embeds = raw.get("embeds") or []
    if not isinstance(attachments, list) or not isinstance(embeds, list):
        return None
    return {
        "id": raw["id"], "channel_id": raw["channel_id"],
        "guild_id": raw.get("guild_id") if valid_id(raw.get("guild_id")) else None,
        "author": {key: author[key] for key in ("id", "username", "global_name")
                   if isinstance(author.get(key), str)},
        "timestamp": stamp, "edited_timestamp": edited, "content": raw["content"],
        "type": raw.get("type") if isinstance(raw.get("type"), int) else None,
        "reply_to": ref.get("message_id") if valid_id(ref.get("message_id")) else None,
        "reply_channel_id": ref.get("channel_id") if valid_id(ref.get("channel_id")) else None,
        "mentions": [u["id"] for u in (raw.get("mentions") or [])
                     if isinstance(u, dict) and valid_id(u.get("id"))],
        "attachments": [{key: a[key] for key in ("id", "filename", "url", "content_type", "size")
                         if isinstance(a.get(key), (str, int))}
                        for a in attachments if isinstance(a, dict)],
        "embeds": [{key: e[key] for key in ("title", "description", "url")
                    if isinstance(e.get(key), str)} for e in embeds if isinstance(e, dict)],
        "reactions": [{"emoji": ((r.get("emoji") or {}).get("name") or "未知"),
                       "count": r.get("count", 0)}
                      for r in (raw.get("reactions") or [])
                      if isinstance(r, dict) and isinstance(r.get("count"), int)],
    }


def scan(root: Path):
    root = root.resolve(strict=True)
    counters = collections.Counter()
    variants, channels, files = {}, {}, []
    # Explicit scope excludes Local Storage, cookies, account settings and logs.
    for scope in ("Cache", "IndexedDB"):
        for path in sorted((root / scope).rglob("*")):
            if not path.is_file() or path.is_symlink() or not path.resolve().is_relative_to(root):
                continue
            if scope == "IndexedDB" and path.suffix not in (".ldb", ".log"):
                continue
            relative = path.relative_to(root).as_posix()
            meta = {"path": relative}
            files.append(meta)
            try:
                before = path.stat()
                if before.st_size > LIMIT:
                    meta["status"] = "oversize"
                    counters["files_skipped"] += 1
                    continue
                data = read_shared(path)
                after = path.stat()
                if len(data) > LIMIT:
                    meta["status"] = "oversize"
                    counters["files_skipped"] += 1
                    continue
                digest = hashlib.sha256(data).hexdigest()
                changed = (before.st_mtime_ns, before.st_size) != (after.st_mtime_ns, after.st_size)
                meta.update(status="changed_during_read" if changed else "read",
                            sha256=digest, bytes=len(data))
                counters["files_changed_during_read"] += int(changed)
                counters["files_read"] += 1
            except OSError as exc:
                meta.update(status="unreadable", error_code=getattr(exc, "winerror", None) or exc.errno)
                counters["files_unreadable"] += 1
                continue
            for body, encoding, compressed_offset in payloads(data, counters):
                if b'"channel_id"' not in body and not (b'"guild_id"' in body and b'"name"' in body):
                    continue
                for value, offset in objects(body):
                    for raw in walk(value):
                        if (valid_id(raw.get("id")) and "channel_id" not in raw
                                and raw.get("type") in (0, 1, 3, 5, 10, 11, 12)
                                and isinstance(raw.get("name"), str)):
                            channels[raw["id"]] = {"name": raw["name"],
                                "guild_id": raw.get("guild_id"), "parent_id": raw.get("parent_id"),
                                "type": raw.get("type"),
                                "message_count": raw.get("message_count") if isinstance(raw.get("message_count"), int) else None,
                                "member_count": raw.get("member_count") if isinstance(raw.get("member_count"), int) else None,
                                "last_message_id": raw.get("last_message_id") if valid_id(raw.get("last_message_id")) else None}
                        message = normalize(raw)
                        if message is None:
                            continue
                        fingerprint = hashlib.sha256(json.dumps(message, sort_keys=True,
                                                               ensure_ascii=False).encode()).hexdigest()
                        key = (message["channel_id"], message["id"])
                        source = {"path": relative, "file_sha256": digest, "encoding": encoding,
                                  "payload_offset": compressed_offset, "json_offset": offset,
                                  "snapshot_changed": changed}
                        versions = variants.setdefault(key, {})
                        if fingerprint not in versions:
                            versions[fingerprint] = {**message, "sources": []}
                        if source not in versions[fingerprint]["sources"]:
                            versions[fingerprint]["sources"].append(source)
    messages = []
    for versions in variants.values():
        ordered = sorted(versions.values(), key=lambda m: (m["edited_timestamp"] or m["timestamp"],
                                                           json.dumps(m, sort_keys=True)))
        chosen = dict(ordered[-1])
        chosen["conflicting_versions"] = ordered[:-1]
        messages.append(chosen)
    counters["recovered_messages"] = len(messages)
    counters["messages_with_variants"] = sum(bool(m["conflicting_versions"]) for m in messages)
    return messages, channels, {"counters": dict(counters), "files": files}


def select(messages, channel, start, end):
    channel_ids = {channel} if isinstance(channel, str) else set(channel)
    return sorted((m for m in messages if m["channel_id"] in channel_ids
                   and start <= iso(m["timestamp"]) < end), key=lambda m: (m["timestamp"], m["id"]))


def dump(path, value):
    Path(path).write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(os.environ.get("APPDATA", ".")) / "discord")
    parser.add_argument("--list-channels", action="store_true")
    parser.add_argument("--channel", action="append", help="频道 ID、完整频道名或 discord.com/channels/... 链接；可重复")
    parser.add_argument("--name", help="报告显示名称，不用作匹配条件")
    parser.add_argument("--include-threads", action="store_true", help="包含缓存元数据能证明从属关系的子线程")
    parser.add_argument("--hours", type=int, choices=(24, 48, 72), default=None)
    parser.add_argument("--start")
    parser.add_argument("--end")
    parser.add_argument("--out", type=Path)
    args = parser.parse_args()
    if bool(args.start) != bool(args.end):
        parser.error("--start 和 --end 必须一起提供")
    if args.start and args.hours is not None:
        parser.error("--hours 与指定起止时间互斥")
    try:
        end = iso(args.end) if args.end else datetime.now(timezone.utc)
        start = iso(args.start) if args.start else end - timedelta(hours=args.hours or 24)
    except ValueError as exc:
        parser.error(str(exc))
    if start >= end:
        parser.error("开始时间必须早于结束时间")
    requested = args.channel or []
    if not args.list_channels and (not requested or not args.out):
        parser.error("请提供 --channel 和 --out，或先运行 --list-channels")
    if args.out and args.out.resolve().is_relative_to(args.root.resolve()):
        parser.error("输出目录不能位于 Discord 数据目录中")
    messages, names, audit = scan(args.root)
    if args.list_channels:
        rows = []
        for cid in sorted({m["channel_id"] for m in messages}):
            times = sorted(m["timestamp"] for m in messages if m["channel_id"] == cid)
            rows.append({"channel_id": cid, **names.get(cid, {"name": None}), "cached_count": len(times),
                         "first": times[0], "last": times[-1]})
        print(json.dumps({"notice": NOTICE, "channels": rows, "counters": audit["counters"]}, ensure_ascii=False, indent=2))
        return
    roots = []
    for value in requested:
        match = re.fullmatch(r"https://(?:www\.)?discord.com/channels/(?:@me|\d+)/(\d+)(?:/\d+)?/?", value)
        channel = match[1] if match else value
        if not valid_id(channel):
            candidates = [cid for cid, meta in names.items() if meta["name"] == channel]
            if len(candidates) != 1:
                parser.error("完整频道名匹配不唯一或未缓存，请提供频道链接。候选 ID：" + ", ".join(candidates))
            channel = candidates[0]
        roots.append(channel)
    channel_ids = set(roots)
    if args.include_threads:
        while True:
            children = {cid for cid, meta in names.items() if meta.get("parent_id") in channel_ids}
            if children <= channel_ids:
                break
            channel_ids.update(children)
    selected = select(messages, channel_ids, start, end)
    ids = {m["id"] for m in selected}
    for m in selected:
        m["reply_in_selection"] = m["reply_to"] in ids if m["reply_to"] else None
    if args.out.exists() and any(args.out.iterdir()):
        parser.error("每次运行须使用新的空输出目录，避免覆盖旧报告")
    args.out.mkdir(parents=True, exist_ok=True)
    display_names = [names.get(cid, {}).get("name") or cid for cid in roots]
    document = {"schema_version": 1, "source": "discord_desktop_cache", "complete": False,
                "notice": NOTICE, "generated_at": datetime.now(timezone.utc).isoformat(),
                "channel_id": roots[0] if len(roots) == 1 else None,
                "channel_ids": roots, "channel_name": args.name or " + ".join(display_names),
                "selected_channel_ids": sorted(channel_ids), "threads_requested": args.include_threads,
                "channel_metadata": {cid: names.get(cid, {}) for cid in sorted(channel_ids)},
                "thread_coverage": "只含已缓存且能确认 parent_id 的子线程；未缓存的帖子无法枚举",
                "period": {"start_inclusive": start.isoformat(), "end_exclusive": end.isoformat()},
                "messages": selected}
    dump(args.out / "messages.json", document)
    dump(args.out / "verification.json", {**audit, "complete": False, "notice": NOTICE,
                                         "selected_count": len(selected), "channel_ids": roots,
                                         "period": document["period"]})
    text = "\n\n".join(f'[{m["id"]}] {m["timestamp"]} {m["author"].get("global_name") or m["author"].get("username") or m["author"]["id"]}\n{m["content"]}' for m in selected)
    (args.out / "messages.txt").write_text(NOTICE + "\n\n" + text, encoding="utf-8")
    print(json.dumps({"selected_count": len(selected), "complete": False,
                      "out": str(args.out.resolve()), "next": "阅读 messages.json，编写带消息 ID 的 report.json，然后运行 render_report.py。"}, ensure_ascii=False))


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError) as error:
        print(f"读取失败：{error}", file=sys.stderr)
        sys.exit(1)
