"""Export the bridge contract and validate hook output without MQTT or HTTP."""

import argparse
import json
import sys
from pathlib import Path

from pydantic import ValidationError

from app.models import AgentStatus, FIELD_BYTE_LIMITS, MAX_MQTT_PAYLOAD_BYTES


def status_schema() -> dict:
    schema = AgentStatus.model_json_schema()
    schema["$schema"] = "https://json-schema.org/draft/2020-12/schema"
    schema["description"] = (
        "Agent Monitor V1 status. Standard JSON Schema validates structure; "
        "x-maxUtf8Bytes and x-maxMqttPayloadBytes require the bridge validator. "
        "Missing detail defaults to empty text; missing timestamp defaults to server Unix seconds."
    )
    schema["x-maxMqttPayloadBytes"] = MAX_MQTT_PAYLOAD_BYTES
    for name, limit in FIELD_BYTE_LIMITS.items():
        schema["properties"][name]["x-maxUtf8Bytes"] = limit
    for name in ("id", "name", "host"):
        schema["properties"][name]["description"] = "Must contain non-whitespace text."
    return schema


def schema_text() -> str:
    return json.dumps(status_schema(), ensure_ascii=False, indent=2) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    export = commands.add_parser("schema", help="Print schema or check a saved schema")
    export.add_argument("--check", type=Path, help="Fail if this file differs from the model")
    validate = commands.add_parser("validate", help="Validate one status JSON object")
    validate.add_argument("file", help="UTF-8 JSON file, or - for stdin")
    args = parser.parse_args(argv)
    try:
        if args.command == "schema":
            if args.check is not None:
                if json.loads(args.check.read_text(encoding="utf-8-sig")) != status_schema():
                    print("Schema differs from app.models.AgentStatus", file=sys.stderr)
                    return 1
            else:
                print(schema_text(), end="")
        else:
            raw = sys.stdin.read() if args.file == "-" else Path(args.file).read_text(encoding="utf-8-sig")
            result = AgentStatus.model_validate_json(raw)
            print(result.to_mqtt_payload())
    except (OSError, ValueError, ValidationError):
        # Validation errors may include user data; do not echo hook payloads.
        print("Invalid status JSON or unreadable file; check INTEGRATION.md constraints.", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
