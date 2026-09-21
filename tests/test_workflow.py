import gzip
import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from read_cache import iso, objects, scan, select, NOTICE
from render_report import validate, render_html, render_png, report_lines

CHANNEL = "100000000000000001"


def message(mid="100000000000000011", time="2026-09-21T08:00:00+08:00", content="这是虚构测试：建议周三完成。"):
    return {"id": mid, "channel_id": CHANNEL, "timestamp": time,
            "author": {"id": "100000000000000021", "username": "测试成员甲"},
            "content": content, "attachments": [], "embeds": [], "mentions": []}


def sample_report(ids):
    return {"title": "虚构示例：项目讨论", "overview": "成员提出完成时间建议，尚未形成决定。",
            "overview_message_ids": ids, "reviewed_message_ids": ids,
            "priority_items": ([{"text": "有人建议周三完成；这是建议，不代表已执行。", "importance": 72,
                                  "relevance": "与项目进度直接相关", "heat": "1 条消息，无可用反应数据",
                                  "reason": "包含可执行时间建议", "message_ids": ids}] if ids else []),
            "topics": ([{"text": "有人建议周三完成；这是建议，不代表已执行。", "message_ids": ids}] if ids else []),
            "todos": [], "confirmed": [], "unresolved": [], "other": [],
            "filtered": {"count": 0, "message_ids": [], "reasons": []},
            "limitations": ["这是虚构测试，不能证明真实读取成功。"]}


class WorkflowTests(unittest.TestCase):
    def fixture(self, temp, values):
        cache = Path(temp) / "Cache" / "Cache_Data"
        cache.mkdir(parents=True)
        (cache / "data_2").write_bytes(b"binary prefix" + gzip.compress(json.dumps(values, ensure_ascii=False).encode()) + b"suffix")
        return Path(temp)

    def test_gzip_chinese_and_dedup(self):
        with tempfile.TemporaryDirectory() as temp:
            root = self.fixture(temp, [message(), message()])
            messages, _, audit = scan(root)
            self.assertEqual(len(messages), 1)
            self.assertIn("虚构测试", messages[0]["content"])
            self.assertEqual(audit["counters"]["gzip_decoded"], 1)
            self.assertEqual(len(messages[0]["sources"][0]["file_sha256"]), 64)
            self.assertEqual(messages[0]["reactions"], [])

    def test_time_boundaries_and_timezone(self):
        with tempfile.TemporaryDirectory() as temp:
            root = self.fixture(temp, [message(), message("100000000000000012", "2026-09-22T08:00:00+08:00")])
            messages, _, _ = scan(root)
            chosen = select(messages, CHANNEL, iso("2026-09-21T00:00:00Z"), iso("2026-09-22T00:00:00Z"))
            self.assertEqual([m["id"] for m in chosen], ["100000000000000011"])
            self.assertEqual(select(messages, "999999999999999999", iso("2026-09-21T00:00:00Z"), iso("2026-09-22T00:00:00Z")), [])
            self.assertEqual(len(select(messages, {CHANNEL, "999999999999999999"},
                                        iso("2026-09-21T00:00:00Z"), iso("2026-09-22T00:00:00Z"))), 1)
            with self.assertRaises(ValueError):
                iso("2026-09-21T00:00:00")

    def test_edited_versions_preserved(self):
        original = message()
        edited = {**original, "content": "改为周四", "edited_timestamp": "2026-09-21T01:00:00Z"}
        with tempfile.TemporaryDirectory() as temp:
            messages, _, _ = scan(self.fixture(temp, [edited, original]))
            self.assertEqual(messages[0]["content"], "改为周四")
            self.assertEqual(messages[0]["conflicting_versions"][0]["content"], original["content"])

    def test_ignores_credentials_and_corrupt_data(self):
        with tempfile.TemporaryDirectory() as temp:
            root = self.fixture(temp, [{"token": "synthetic-secret-not-a-real-token"}])
            secrets = root / "Local Storage"
            secrets.mkdir()
            (secrets / "fake.log").write_text(json.dumps(message()), encoding="utf-8")
            (root / "Cache" / "bad").write_bytes(b'\x1f\x8b\x08broken {"id":')
            messages, _, audit = scan(root)
            self.assertEqual(messages, [])
            self.assertTrue(all(not f["path"].startswith("Local Storage") for f in audit["files"]))

    def test_json_fragment_recovery(self):
        values = list(objects(b'{broken \x00 {"hello":"world"}\x00'))
        self.assertEqual(values[0][0], {"hello": "world"})

    def test_reference_validation_and_html_escape(self):
        with tempfile.TemporaryDirectory() as temp:
            messages, _, _ = scan(self.fixture(temp, [message(content='<script>alert("x")</script>')]))
            data = {"messages": messages, "channel_id": CHANNEL, "channel_name": "<测试频道>",
                    "notice": NOTICE, "period": {"start_inclusive": "2026-09-21T00:00:00Z", "end_exclusive": "2026-09-22T00:00:00Z"}}
            report = sample_report([messages[0]["id"]])
            validate(data, report)
            page = render_html(data, report)
            self.assertNotIn('<script>', page)
            self.assertIn('&lt;script&gt;', page)
            self.assertIn('<details>', page)
            self.assertNotIn('<details open', page)
            report["topics"][0]["message_ids"] = ["nonexistent"]
            with self.assertRaises(ValueError):
                validate(data, report)

    def test_priority_must_be_sorted_and_filtered_count_must_match(self):
        with tempfile.TemporaryDirectory() as temp:
            messages, _, _ = scan(self.fixture(temp, [message()]))
            data = {"messages": messages, "channel_id": CHANNEL, "channel_name": "测试频道",
                    "notice": NOTICE, "period": {"start_inclusive": "2026-09-21T00:00:00Z", "end_exclusive": "2026-09-22T00:00:00Z"}}
            report = sample_report([messages[0]["id"]])
            report["priority_items"].append({**report["priority_items"][0], "importance": 90})
            with self.assertRaises(ValueError):
                validate(data, report)
            report = sample_report([messages[0]["id"]])
            report["filtered"] = {"count": 1, "message_ids": [], "reasons": ["低价值"]}
            with self.assertRaises(ValueError):
                validate(data, report)
            report = sample_report([])
            with self.assertRaises(ValueError):
                validate(data, report)

    def test_png_split_without_truncation(self):
        font = Path("C:/Windows/Fonts/msyh.ttc")
        if not font.exists():
            self.skipTest("Windows 中文字体不可用")
        from PIL import Image
        with tempfile.TemporaryDirectory() as temp:
            lines = [("body", "中文长图验证，末尾不可被静默截断。" * 15)] * 10
            names = render_png(lines, Path(temp), str(font), max_height=800)
            self.assertGreater(len(names), 1)
            for name in names:
                with Image.open(Path(temp) / name) as png:
                    self.assertLessEqual(png.height, 800)
                    self.assertEqual(png.width, 1200)


if __name__ == "__main__":
    unittest.main()
