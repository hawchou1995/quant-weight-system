#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""_tz_device_auth_0916.py —— 同舟 MCP OAuth 设备码重新授权（token 过期后使用）

背景：2026-09-16 的 access_token（30min 寿命）已过期，且 refresh_token 被服务端判定
      "device session is no longer active"（设备会话已失效），无法再续期 → 必须重新授权。

用法：
    python _tz_device_auth_0916.py            # 打印 user_code + URL，然后阻塞轮询（默认 600s）
    python _tz_device_auth_0916.py --poll 540

成功即把新 token 写回 tongzhou_oauth.json（含 token_obtained_at，供 connector 自动续期）。
禁止在本文件/日志中输出 access_token 明文。
"""
import argparse
import json
import pathlib
import sys
import time
import urllib.error as ue
import urllib.parse as up
import urllib.request as ur

ROOT = pathlib.Path("D:/Documents/Workbuddy/股票基金/quant-weight-system/backtest")
OAUTH_JSON = ROOT / "tongzhou_oauth.json"
GATEWAY = "https://mcp-gateway.textmind-gz.com"
MCP_URL = f"{GATEWAY}/mcp/tongzhou-research"
SCOPE = "research:read"


def _post(url, data, timeout=25):
    req = ur.Request(url, data=up.urlencode(data).encode(),
                     headers={"Content-Type": "application/x-www-form-urlencoded",
                              "Accept": "application/json"})
    return json.loads(ur.urlopen(req, timeout=timeout).read())


def cfg_load():
    return json.loads(OAUTH_JSON.read_text(encoding="utf-8"))


def cfg_save_tok(cfg, tok):
    cfg["token"] = tok
    cfg["token_obtained_at"] = time.time()
    OAUTH_JSON.write_text(json.dumps(cfg, ensure_ascii=False, indent=1), encoding="utf-8")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--poll", type=int, default=600, help="轮询总时长（秒），默认 600")
    a = ap.parse_args()

    cfg = cfg_load()
    cid = (cfg.get("client_device") or cfg.get("client") or {}).get("client_id")
    print(f"[client_id] {cid}", flush=True)

    d = _post(f"{GATEWAY}/oauth/device_authorization",
              {"client_id": cid, "resource": MCP_URL, "scope": SCOPE})
    print("\n" + "=" * 62)
    print(f"  用户码 USER CODE : {d['user_code']}")
    print(f"  授权链接         : {d['verification_uri_complete']}")
    print(f"  （手动入口       : {d['verification_uri']}  → 输入上面的码）")
    print(f"  有效期           : {d['expires_in']} 秒")
    print("=" * 62 + "\n", flush=True)

    interval = max(int(d.get("interval") or 5), 3)
    end = time.time() + min(a.poll, int(d.get("expires_in") or 600))
    last = ""
    while time.time() < end:
        try:
            nt = _post(f"{GATEWAY}/oauth/token",
                       {"grant_type": "urn:ietf:params:oauth:grant-type:device_code",
                        "device_code": d["device_code"], "client_id": cid, "resource": MCP_URL})
            if nt.get("access_token"):
                cfg_save_tok(cfg, nt)
                print(f"[OK] 授权成功 expires_in={nt.get('expires_in')} "
                      f"refresh_token={'有' if nt.get('refresh_token') else '无'} → 已写回 tongzhou_oauth.json",
                      flush=True)
                return 0
        except ue.HTTPError as e:
            try:
                j = json.loads(e.read().decode())
            except Exception:
                j = {"error": str(e)}
            err = j.get("error", "")
            if err in ("authorization_pending", "slow_down"):
                if err != last:
                    print(f"[wait] device_code={d['device_code'][:16]}… {err} 等待你在浏览器里点确认", flush=True)
                    last = err
                if err == "slow_down":
                    interval += 2
            elif err == "expired_token":
                print("[FAIL] device_code 已过期，请重跑本脚本拿新码", flush=True)
                return 1
            elif err == "access_denied":
                print("[FAIL] 用户拒绝授权", flush=True)
                return 1
            else:
                print(f"[FAIL] {err}: {j.get('error_description','')[:200]}", flush=True)
                return 1
        except Exception as e:
            print(f"[warn] {type(e).__name__} {str(e)[:120]}", flush=True)
        time.sleep(interval)
    print("[FAIL] 轮询超时未完成授权", flush=True)
    return 1


if __name__ == "__main__":
    sys.exit(main())
