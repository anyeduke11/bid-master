#!/usr/bin/env python3
"""contract_util.py · 产物契约校验器（P0-0 · stdlib 实现，无外部依赖）

schema 子集（contracts/artifact/*.schema.json）：
  { "required": ["f1", ...],
    "properties": { "f1": {"type": "string|number|boolean|array|object",
                            "pattern": "<regex>", "enum": [...], "minItems": N},
                     ... },
    "patterns": {"<校验名>": "<regex 应用于整文档 json 串>"} }
校验规则：required 全在；存在则类型匹配；pattern 对字符串值 fullmatch；minItems 对数组。
返回 errors 列表（空=通过）。
"""
import json
import re
from pathlib import Path

CONTRACTS = Path(__file__).resolve().parent.parent / "contracts" / "artifact"

_TYPES = {"string": str, "number": (int, float), "boolean": bool, "array": list, "object": dict}


def validate(doc, schema: dict) -> list:
    errors = []
    if not isinstance(doc, dict):
        return ["顶层必须是 object"]
    for key in schema.get("required", []):
        if key not in doc:
            errors.append(f"缺必填字段: {key}")
    for key, spec in (schema.get("properties") or {}).items():
        if key not in doc:
            continue
        val = doc[key]
        t = spec.get("type")
        if t and t in _TYPES:
            if t == "number" and isinstance(val, bool):
                errors.append(f"{key}: 应为 number，实为 boolean")
                continue
            if not isinstance(val, _TYPES[t]):
                errors.append(f"{key}: 类型应为 {t}，实为 {type(val).__name__}")
                continue
        if "enum" in spec and val not in spec["enum"]:
            errors.append(f"{key}: {val!r} 不在枚举 {spec['enum']}")
        if "pattern" in spec and isinstance(val, str) and not re.fullmatch(spec["pattern"], val):
            errors.append(f"{key}: 不匹配模式 {spec['pattern']}")
        if t == "array" and "minItems" in spec and len(val) < spec["minItems"]:
            errors.append(f"{key}: 数组长度 {len(val)} < minItems {spec['minItems']}")
        if t == "array" and "items" in spec:
            ispec = spec["items"]
            for i, v in enumerate(val):
                if "pattern" in ispec and isinstance(v, str) and not re.fullmatch(ispec["pattern"], v):
                    errors.append(f"{key}[{i}]: {v[:30]!r} 不匹配 {ispec['pattern']}")
    for name, pat in (schema.get("patterns") or {}).items():
        if not re.search(pat, json.dumps(doc, ensure_ascii=False)):
            errors.append(f"全文模式未命中：{name}（{pat}）")
    return errors


def load_schema(kind: str) -> dict:
    p = CONTRACTS / f"{kind}.schema.json"
    if not p.exists():
        raise FileNotFoundError(f"契约不存在: {p}")
    return json.loads(p.read_text(encoding="utf-8"))


def validate_kind(kind: str, doc) -> list:
    return validate(doc, load_schema(kind))
