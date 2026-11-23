#!/usr/bin/env python3
"""Careful first GPU check (AMD ROCm through PyTorch's "cuda" API).

Usage (from ~/my-steam-deck-gets-me): timeout 120 envs/gpu/bin/python lab/gpu_check.py
Optional: HSA_CU_MASK=0:0-3 limits us to compute units 0-3 of the Deck's 8 (a hard cap for us).
Steps get bigger one by one and each prints before it starts, so a hang shows where it happened.
"""

import time

import torch


def step(name):
    print(f"-> {name}", flush=True)


step("is the GPU visible")
print("   available:", torch.cuda.is_available())
if not torch.cuda.is_available():
    raise SystemExit("no GPU for PyTorch")
props = torch.cuda.get_device_properties(0)
print(f"   name: {props.name}  arch: {getattr(props, 'gcnArchName', '?')}  "
      f"compute units: {props.multi_processor_count}  memory: {props.total_memory / 2**30:.1f} GiB")

step("tiny add on the GPU")
x = torch.ones(4, device="cuda")
print("   result:", (x + x).tolist())

for dtype in (torch.float32, torch.float16):
    step(f"matrix multiply 2048x2048 {dtype}")
    a = torch.randn(2048, 2048, device="cuda", dtype=dtype)
    b = torch.randn(2048, 2048, device="cuda", dtype=dtype)
    ref = (a.float().cpu() @ b.float().cpu())
    c = a @ b
    torch.cuda.synchronize()
    err = (c.float().cpu() - ref).abs().max().item() / ref.abs().max().item()
    start = time.perf_counter()
    for _ in range(20):
        c = a @ b
    torch.cuda.synchronize()
    spent = (time.perf_counter() - start) / 20
    print(f"   {2 * 2048**3 / spent / 1e12:.2f} TFLOPS, relative error {err:.1e}")

step("done: GPU works")
