"""pdfplumber 全局互斥锁（单一实例）。
pdfminer 非线程安全；独立微模块是因 pdf.py/pdf_plain.py 互有 import，锁放任一文件会循环 import 或锁分裂（两把锁等于没锁）。
"""
from __future__ import annotations

import threading

_pdfplumber_lock = threading.Lock()
