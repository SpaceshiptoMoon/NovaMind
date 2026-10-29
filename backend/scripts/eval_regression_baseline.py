"""检索质量回归基线：对固定测试集跑评测并对比历史基线，指标劣化超阈值即非零退出。

用法（backend/ 下）：
    # 跑评测并写入基线（首次）
    .venv/Scripts/python scripts/eval_regression_baseline.py --baseline --name e2e评测集-1029

    # 回归对比（默认阈值：overall 降 0.5 / hit_rate 降 0.1 即失败）
    .venv/Scripts/python scripts/eval_regression_baseline.py --name e2e评测集-1029

依赖：后端服务已在本机运行（默认 http://127.0.0.1:8100），用户具备可写空间成员身份。
基线文件：backend/tests/engines/eval/eval_regression_baseline.json（入库，可 diff）。
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

BASE = "http://127.0.0.1:8100/api/v1"
SPACE_ID = 38
KB_ID = 106
BASELINE_PATH = Path(__file__).resolve().parent.parent / "tests/engines/eval/eval_regression_baseline.json"
# 劣化容忍阈值：overall（LLM 评分 0-10）与 hit_rate（0-1）分别设防
OVERALL_TOLERANCE = 0.5
HIT_RATE_TOLERANCE = 0.1


async def _api(method: str, path: str, token: str, payload: dict | None = None):
    import aiohttp

    async with aiohttp.ClientSession() as s:
        async with s.request(method, BASE + path, headers={
            "Authorization": f"Bearer {token}", "Content-Type": "application/json",
        }, json=payload) as r:
            return r.status, await r.json()


async def _login() -> str:
    import aiohttp
    env = Path(__file__).resolve().parent.parent.parent / ".env"
    pw = env.read_text(encoding="utf-8").split("ADMIN_PASSWORD=")[1].split("\n")[0].strip()
    async with aiohttp.ClientSession() as s:
        async with s.post(BASE + "/user/users/login",
                          json={"username": "admin", "password": pw}) as r:
            return (await r.json())["access_token"]


async def run(token: str, test_set_name: str) -> dict:
    """跑一轮完整评测：找测试集 → 建任务 → 轮询 → 取报告 summary。"""
    code, lst = await _api("GET", f"/spaces/{SPACE_ID}/knowledge-bases/{KB_ID}/evaluation/test-sets", token)
    sets = [it for it in lst.get("items", []) if it.get("name") == test_set_name]
    if not sets:
        print(f"FAIL: 测试集 {test_set_name} 不存在，请先创建", file=sys.stderr)
        sys.exit(2)
    ts_id = sets[0]["id"]

    code, resp = await _api("POST", f"/spaces/{SPACE_ID}/knowledge-bases/{KB_ID}/evaluation/tasks", token,
                            {"test_set_id": ts_id, "name": f"回归基线-{test_set_name}"})
    if code not in (200, 201, 202):
        print(f"FAIL: 建评测任务失败 {resp}", file=sys.stderr)
        sys.exit(2)
    task_id = resp["task_id"]
    print(f"评测任务 {task_id} 已创建，轮询中…")

    while True:
        await asyncio.sleep(10)
        code, d = await _api("GET", f"/spaces/{SPACE_ID}/knowledge-bases/{KB_ID}/evaluation/tasks/{task_id}", token)
        if d.get("status") in ("completed", "failed", "error"):
            if d.get("status") != "completed":
                print(f"FAIL: 评测任务失败 {d.get('error_message')}", file=sys.stderr)
                sys.exit(2)
            break
    code, report = await _api("GET", f"/spaces/{SPACE_ID}/knowledge-bases/{KB_ID}/evaluation/tasks/{task_id}/report", token)
    summary = report.get("summary") or {}
    return {
        "task_id": task_id,
        "total_cases": summary.get("total_cases"),
        "hit_rate": (summary.get("retrieval") or {}).get("hit_rate"),
        "mrr": (summary.get("retrieval") or {}).get("mrr"),
        "overall": (summary.get("generation") or {}).get("overall"),
        "faithfulness": (summary.get("generation") or {}).get("faithfulness"),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--name", default="e2e评测集-1029", help="测试集名称")
    parser.add_argument("--baseline", action="store_true", help="把本轮结果写入基线（首次/刷新）")
    parser.add_argument("--space", type=int, default=SPACE_ID)
    parser.add_argument("--kb", type=int, default=KB_ID)
    args = parser.parse_args()

    metrics = asyncio.run(run(asyncio.run(_login()), args.name))
    print("本轮指标:", json.dumps(metrics, ensure_ascii=False))

    if args.baseline:
        BASELINE_PATH.parent.mkdir(parents=True, exist_ok=True)
        BASELINE_PATH.write_text(
            json.dumps(metrics, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"基线已写入 {BASELINE_PATH}")
        return

    if not BASELINE_PATH.exists():
        print("FAIL: 基线文件不存在（先跑 --baseline）", file=sys.stderr)
        sys.exit(2)
    base = json.loads(BASELINE_PATH.read_text(encoding="utf-8"))
    failures = []
    if (base.get("overall") is not None) and (metrics.get("overall") is not None):
        if metrics["overall"] < base["overall"] - OVERALL_TOLERANCE:
            failures.append(f"overall {metrics['overall']} < 基线 {base['overall']} - {OVERALL_TOLERANCE}")
    if (base.get("hit_rate") is not None) and (metrics.get("hit_rate") is not None):
        if metrics["hit_rate"] < base["hit_rate"] - HIT_RATE_TOLERANCE:
            failures.append(f"hit_rate {metrics['hit_rate']} < 基线 {base['hit_rate']} - {HIT_RATE_TOLERANCE}")
    if failures:
        print("REGRESSION:", "; ".join(failures), file=sys.stderr)
        sys.exit(1)
    print("PASS: 指标未劣化（相对基线）")


if __name__ == "__main__":
    main()
