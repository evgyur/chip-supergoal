import hashlib
import json
import os
import shutil
import subprocess
import tempfile
import textwrap
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SENDER = ROOT / "templates" / "delivery" / "send-review-md-files.sh"
READBACK_VERIFIER = ROOT / "templates" / "delivery" / "verify-startup-delivery-readback.py"
CANONICAL = ["THINKING.md", "ROADMAP.md", "LAUNCH_GOAL.md"]


class StartupPackDelivery(unittest.TestCase):
    def test_exactly_three_files_are_sent_and_launch_is_last(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / ".supergoal"
            (root / "out").mkdir(parents=True)
            (root / "templates" / "delivery").mkdir(parents=True)

            # Canonical chat files plus many package internals that must stay on disk.
            for name in CANONICAL + [
                "RESEARCH.md", "LOOP_DESIGN.md", "STATE.md", "PROTOCOL.md",
                "MANIFEST.json",
            ]:
                (root / name).write_text(f"content for {name}\n", encoding="utf-8")
            (root / "CONTRACT.json").write_text(json.dumps({
                "delivery": {"files": CANONICAL, "telegram_thread": "telegram:test:topic"}
            }), encoding="utf-8")
            shutil.copy2(READBACK_VERIFIER, root / "templates" / "delivery" / READBACK_VERIFIER.name)
            (root / "phases").mkdir()
            (root / "phases" / "phase-01.md").write_text("internal phase\n", encoding="utf-8")
            (root / "out" / "demo.complete-supergoal.tar.gz").write_bytes(b"internal archive")

            log = root / "out" / "send-order.jsonl"
            transport = root / "send.py"
            transport.write_text(textwrap.dedent("""\
                import json, os
                from pathlib import Path
                log = Path(os.environ['SEND_LOG'])
                rows = log.read_text(encoding='utf-8').splitlines() if log.exists() else []
                row = {
                    'label': os.environ['SUPERGOAL_SEND_LABEL'],
                    'caption': os.environ['SUPERGOAL_SEND_CAPTION'],
                    'file': os.environ['SUPERGOAL_SEND_FILE'],
                }
                with log.open('a', encoding='utf-8') as fh:
                    fh.write(json.dumps(row) + '\\n')
                print(json.dumps({'message_id': f'msg-{len(rows) + 1}'}))
            """), encoding="utf-8")

            readback = root / "out" / "readback.json"
            hashes = {name: hashlib.sha256((root / name).read_bytes()).hexdigest() for name in CANONICAL}
            readback.write_text(json.dumps({
                "schema": "chip-supergoal.telegram-readback.v1",
                "target": "telegram:test:topic",
                "sender": {"id": "bot-1", "username": "testbot"},
                "items": [
                    {
                        "order": i,
                        "message_id": f"msg-{i + 1}",
                        "filename": name,
                        "sha256": hashes[name],
                        "bytes": (root / name).stat().st_size,
                        "has_media": True,
                        "media_type": "document",
                        "chat_id": "test",
                        "thread_id": "topic",
                    }
                    for i, name in enumerate(CANONICAL)
                ],
            }), encoding="utf-8")

            env = os.environ.copy()
            env.update({
                "SUPERGOAL_ROOT": str(root),
                "SUPERGOAL_DELIVERY_TARGET": "telegram:test:topic",
                "SUPERGOAL_TRANSPORT_SEND_FILE_CMD": f"python3 {transport}",
                "SUPERGOAL_SEND_INTERVAL_SECONDS": "0",
                "SUPERGOAL_DELIVERY_READBACK_RECEIPT": str(readback),
                "SEND_LOG": str(log),
            })
            result = subprocess.run(
                ["bash", str(SENDER)], cwd=root, env=env, text=True,
                stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            )
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

            rows = [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines()]
            self.assertEqual([row["label"] for row in rows], CANONICAL)
            self.assertEqual(len(rows), 3)
            self.assertIn("reply /goal to this file", rows[-1]["caption"])

            receipt = json.loads((root / "out" / "review-md-files-delivery-receipt.json").read_text(encoding="utf-8"))
            self.assertEqual(receipt["pack_version"], "startup_pack_v4")
            self.assertEqual(receipt["files"], CANONICAL)
            self.assertEqual(receipt["message_ids"], ["msg-1", "msg-2", "msg-3"])
            self.assertEqual(receipt["file_message_ids"], dict(zip(CANONICAL, receipt["message_ids"])))
            self.assertEqual(receipt["launch_message_id"], "msg-3")
            self.assertEqual(set(receipt["hashes"]), set(CANONICAL))
            self.assertTrue(receipt["readback_verified"])
            self.assertEqual([x["filename"] for x in receipt["readback_items"]], CANONICAL)

    def test_missing_one_of_three_blocks_before_any_send(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / ".supergoal"
            (root / "out").mkdir(parents=True)
            (root / "CONTRACT.json").write_text(json.dumps({
                "delivery": {"files": CANONICAL, "telegram_thread": "telegram:test:topic"}
            }), encoding="utf-8")
            (root / "THINKING.md").write_text("thinking\n", encoding="utf-8")
            (root / "LAUNCH_GOAL.md").write_text("launch\n", encoding="utf-8")
            env = os.environ.copy()
            env.update({
                "SUPERGOAL_ROOT": str(root),
                "SUPERGOAL_DELIVERY_TARGET": "telegram:test:topic",
                "SUPERGOAL_TRANSPORT_SEND_FILE_CMD": "exit 99",
            })
            result = subprocess.run(
                ["bash", str(SENDER)], cwd=root, env=env, text=True,
                stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            )
            self.assertEqual(result.returncode, 2)
            self.assertIn("missing canonical startup file", result.stderr)
            self.assertFalse((root / "out" / "review-md-files-delivery-receipt.json").exists())


if __name__ == "__main__":
    unittest.main()
