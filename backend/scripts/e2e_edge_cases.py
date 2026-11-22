"""NovaMind 极端边界 E2E 测试（真机 backend=stream）。"""
import json
import sys
import time
import urllib.error
import urllib.request
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

BASE = "http://localhost:8100/api/v1"
PW = ""
for line in Path("..").joinpath(".env").read_text(encoding="utf-8").splitlines():
    if line.startswith("ADMIN_PASSWORD="):
        PW = line.split("=", 1)[1].strip()
        break

TOKEN = ""
PASS = []
FAIL = []

def _hdr(ct=None):
    h = {"Authorization": f"Bearer {TOKEN}"}
    if ct:
        h["Content-Type"] = ct
    return h

def _api(method, path, body=None, ct="application/json"):
    data = json.dumps(body).encode("utf-8") if body else None
    req = urllib.request.Request(f"{BASE}{path}", data=data, headers=_hdr(ct), method=method)
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read())
        except Exception:
            return e.code, {}

def check(name, cond, detail=""):
    tag = "✅" if cond else "❌"
    print(f"  {tag} {name}  {detail}")
    (PASS if cond else FAIL).append(f"{name}: {detail}")

def upload(sid, kid, filename, content, ct="text/markdown"):
    boundary = "----EB"
    body = (
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="files"; filename="{filename}"\r\n'
        f"Content-Type: {ct}\r\n\r\n"
        f"{content}\r\n"
        f"--{boundary}--\r\n"
    ).encode()
    hdr = _hdr(f"multipart/form-data; boundary={boundary}")
    req = urllib.request.Request(
        f"{BASE}/spaces/{sid}/knowledge-bases/{kid}/documents",
        data=body, headers=hdr, method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            d = json.loads(r.read())
            return d.get("document_id")
    except urllib.error.HTTPError as e:
        print(f"  upload error {e.code}: {e.read()[:100] if hasattr(e, 'read') else ''}")
        return None

def wait_done(sid, kid, doc_id, timeout=120):
    for _ in range(timeout // 5):
        _, d = _api("GET", f"/spaces/{sid}/knowledge-bases/{kid}/documents/{doc_id}")
        st = d.get("status")
        if st in (2, "COMPLETED", "completed"):
            return "completed"
        if st in (3, "FAILED", "failed"):
            return "failed"
        time.sleep(5)
    return "timeout"

def search(sid, kid, query, mode="content_hybrid", top_k=5):
    _, d = _api("POST", f"/spaces/{sid}/knowledge-bases/{kid}/search",
                {"query": query, "search_mode": mode, "top_k": top_k})
    return d.get("results") or []


def main():
    global TOKEN

    # 登录
    _, login = _api("POST", "/user/users/login", {"username": "admin", "password": PW})
    TOKEN = login.get("access_token", "")
    if not TOKEN:
        print("登录失败")
        sys.exit(1)

    suffix = uuid.uuid4().hex[:8]
    _, sp = _api("POST", "/spaces", {"name": f"edge_{suffix}"})
    sid = sp.get("id")
    _, kbd = _api("POST", f"/spaces/{sid}/knowledge-bases", {"name": f"edge_kb_{suffix}"})
    kid = kbd.get("id")
    print(f"测试空间: sid={sid} kid={kid}\n")

    # ===== 场景 1: 空文件上传 =====
    print("--- 场景 1: 空文件 ---")
    did = upload(sid, kid, "empty.md", "")
    check("空文件上传不崩溃", did is not None, f"doc_id={did}")

    # ===== 场景 2: 单字符 =====
    print("--- 场景 2: 单字符 ---")
    did = upload(sid, kid, "single.md", "A")
    check("单字符上传", did is not None, f"doc_id={did}")

    # ===== 场景 3: 超长单行 100KB =====
    print("--- 场景 3: 超长单行 100KB ---")
    long_line = "超长测试" * 25000
    did = upload(sid, kid, "longline.md", long_line)
    check("超长单行上传", did is not None, f"len={len(long_line)}")

    # ===== 场景 4: Unicode/特殊字符 =====
    print("--- 场景 4: Unicode ---")
    uc = "中文🚀测试\ndata 💥\ttab\x00\x01emoji 🎌🎉\n\x7f\x1b[31m红色"
    did = upload(sid, kid, "unicode.md", uc)
    check("Unicode 上传", did is not None, f"doc_id={did}")

    # ===== 场景 5: 并发上传 10 =====
    print("--- 场景 5: 并发上传 10 文档 ---")
    with ThreadPoolExecutor(max_workers=10) as pool:
        futures = [pool.submit(upload, sid, kid, f"cc_{i}.md", f"并发文档 {i}") for i in range(10)]
        results = [f.result() for f in futures]
    check("并发上传 10 文档", all(r is not None for r in results), f"成功 {sum(1 for r in results if r)}/10")

    # ===== 场景 6: 重复触发解析 =====
    print("--- 场景 6: 重复触发 ---")
    dup_id = upload(sid, kid, "dup.md", "重复触发测试")
    c1, _ = _api("POST", f"/spaces/{sid}/knowledge-bases/{kid}/documents/process",
                 {"document_ids": [dup_id]})
    c2, _ = _api("POST", f"/spaces/{sid}/knowledge-bases/{kid}/documents/process",
                 {"document_ids": [dup_id]})
    check("重复触发有防护", c2 in (200, 202, 409, 422), f"第一次={c1} 第二次={c2}")

    # ===== 场景 7: 触发后取消 =====
    print("--- 场景 7: 触发后取消 ---")
    cid = upload(sid, kid, "cancel.md", "取消测试")
    _api("POST", f"/spaces/{sid}/knowledge-bases/{kid}/documents/process",
         {"document_ids": [cid]})
    code, _ = _api("POST", f"/spaces/{sid}/knowledge-bases/{kid}/documents/{cid}/cancel")
    time.sleep(3)
    _, d = _api("GET", f"/spaces/{sid}/knowledge-bases/{kid}/documents/{cid}")
    st = d.get("status")
    check("取消后状态", st in (4, "CANCELLED", "cancelled"), f"status={st}")

    # ===== 场景 8: 删除处理中文档 =====
    print("--- 场景 8: 删除处理中文档 ---")
    del_id = upload(sid, kid, "delete_during.md", "处理中删除")
    _api("POST", f"/spaces/{sid}/knowledge-bases/{kid}/documents/process",
         {"document_ids": [del_id]})
    time.sleep(2)
    code, _ = _api("DELETE", f"/spaces/{sid}/knowledge-bases/{kid}/documents/{del_id}")
    check("删除处理中文档", code in (200, 204), f"HTTP {code}")

    # ===== 场景 9: 大批量 20 文档 =====
    print("--- 场景 9: 大批量 20 文档 ---")
    batch_ids = []
    for i in range(20):
        bid = upload(sid, kid, f"batch_{i}.md", f"批量 {i} 号文档。Redis Stream 测试。")
        batch_ids.append(bid)
    check("上传 20 文档", all(b is not None for b in batch_ids))

    _, trig = _api("POST", f"/spaces/{sid}/knowledge-bases/{kid}/documents/process",
                   {"document_ids": batch_ids})
    check("批量触发", trig.get("success", 0) == 20 or trig.get("total", 0) == 20,
          f"result={json.dumps(trig)[:100]}")

    # ===== 场景 10: 特殊字符检索 =====
    print("--- 场景 10: 特殊字符检索 ---")
    r1 = search(sid, kid, "Redis <script>alert(1)</script> 'OR 1=1--")
    check("注入式检索不崩溃", isinstance(r1, list), f"{len(r1)} 条")
    r2 = search(sid, kid, "🚀🎉🎌")
    check("emoji 检索不崩溃", isinstance(r2, list), f"{len(r2)} 条")

    # 汇总
    print(f"\n{'='*60}")
    print(f"通过: {len(PASS)}  失败: {len(FAIL)}")
    if FAIL:
        for f in FAIL:
            print(f"  ❌ {f}")
    print(f"{'='*60}")
    sys.exit(1 if FAIL else 0)


if __name__ == "__main__":
    main()
