#!/bin/bash
# lark_push.sh · 飞书/微信推送(无 LLM 依赖,直接 webhook)
# 用法: echo '{"msg":"P0 告警 · ...","level":"warn"}' | ./lark_push.sh
# 配置: ~/.bidmaster/lark_config.json { "webhook": "https://open.feishu.cn/...","at_mobiles":["138..."]}

set -e
CONFIG="${BIDMASTER_HOME:-${HOME}/.bidmaster}/lark_config.json"

if [ ! -f "$CONFIG" ]; then
  echo "{\"ok\":false,\"err\":\"lark_config.json 不存在,跳过推送 · 创建模板: $(cat <<'TPL'
{
  "webhook": "https://open.feishu.cn/open-apis/bot/v2/hook/XXXX",
  "at_mobiles": ["13800000000"]
}
TPL
)\"}"
  exit 0  # 不阻塞主流程
fi

PAYLOAD=$(cat)

# 用 python 读 config + 构造飞书消息体
python3 <<EOF
import json, sys, urllib.request

try:
    config = json.load(open("$CONFIG"))
except Exception as e:
    print(json.dumps({"ok": False, "err": f"config 解析失败: {e}"}))
    sys.exit(0)

try:
    payload = json.loads('''$PAYLOAD''')
except Exception as e:
    print(json.dumps({"ok": False, "err": f"payload 解析失败: {e}"}))
    sys.exit(0)

level = payload.get("level", "info")
title = payload.get("msg", payload.get("title", "通知"))
code = payload.get("code", "")
detail = payload.get("detail", "")
at_mobiles = config.get("at_mobiles", [])

# 飞书富文本消息
content_lines = [[{"tag": "text", "text": f"{title}"}]]
if code:
    content_lines.append([{"tag": "text", "text": f" · {code}"}])
if detail:
    content_lines.append([{"tag": "text", "text": f"\n{detail}"}])
if level == "warn":
    content_lines.append([{"tag": "text", "text": "\n🚨 P0 告警,需立即处理"}])

body = {
    "msg_type": "post",
    "content": {
        "post": {
            "zh_cn": {
                "title": "投标看板 · 通知",
                "content": content_lines
            }
        }
    }
}
if at_mobiles:
    body["at"] = {"at_mobiles": at_mobiles}

try:
    req = urllib.request.Request(config["webhook"], data=json.dumps(body).encode(),
                                  headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=10) as r:
        result = json.loads(r.read().decode())
    print(json.dumps({"ok": True, "module": "lark_push", "result": result}, ensure_ascii=False))
except Exception as e:
    print(json.dumps({"ok": False, "err": f"推送失败: {e}"}))
EOF
