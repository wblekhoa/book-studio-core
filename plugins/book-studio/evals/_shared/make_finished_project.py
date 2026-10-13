"""Create ./project as a finished Book Studio project from ./synthetic.epub using the bundled runner."""
import json
import subprocess
import sys
from pathlib import Path

runner = Path(sys.argv[1]) / "scripts" / "bookstudio.py"


def cli(*args):
    result = subprocess.run([sys.executable, str(runner), *args, "--json"], capture_output=True, text=True)
    return result.returncode, json.loads(result.stdout or "{}")


Path("answers.json").write_text(json.dumps({
    "target_language": "vi", "output_mode": "target_only", "audience": "general readers",
    "translation_approach": "faithful", "market_context_policy": "labeled_selective", "layout_policy": "preserve",
}))
assert cli("start", "project", "--source", "synthetic.epub", "--answers", "answers.json")[0] == 0
assert cli("pilot", "approve", "project")[0] == 0


def translate(number=0):
    while True:
        code, packet = cli("next", "project")
        if code != 0:
            return packet.get("code")
        rows = [{"block_index": b["block_index"], "source_sha256": b["source_sha256"], "translation": f"Bản dịch {b['block_index']}"}
                for b in packet["blocks"] if b.get("translate", True)]
        response = Path(f"response-{number}.json")
        number += 1
        response.write_text(json.dumps({"schema_version": 1, "packet_id": packet["packet_id"],
                                        "source_document": packet["source_document"], "translations": rows}, ensure_ascii=False))
        assert cli("apply", "project", str(response))[0] == 0


translate()
assert cli("pilot", "accept", "project", "--confirm")[0] == 0
translate(100)
assert cli("finish", "project")[0] == 0
