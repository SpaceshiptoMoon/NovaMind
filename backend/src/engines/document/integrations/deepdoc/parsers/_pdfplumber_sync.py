"""pdfplumber 全局互斥锁（单一实例）。

pdfminer 非线程安全：上游 RAGFlow 在 sys.modules 里挂全局 Lock 串行化所有
pdfplumber 访问（vendor pdf_parser.py LOCK_KEY_pdfplumber）。独立成微模块是
因为 pdf.py 与 pdf_plain.py 互相存在 import 关系，锁放任一文件都会造成
循环 import 或锁分裂（两把锁互不互斥等于没锁）。
"""
from __future__ import annotations

import threading

_pdfplumber_lock = threading.Lock()
