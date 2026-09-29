"""app · bid-master 统一服务包（DEV-0042）

导入本包即确保 rules/ 可导入（store/set_stage/ticket 等真实层模块的进程内依赖）。
"""
import sys
from pathlib import Path

_RULES = str(Path(__file__).resolve().parent.parent / "rules")
if _RULES not in sys.path:
    sys.path.insert(0, _RULES)
