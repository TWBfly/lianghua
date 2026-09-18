# -*- coding: utf-8 -*-
"""
Continuous Autonomous Alpha Miner (1小时及定时自动研究挖掘引擎)
Based on 《研究策略.md》 first-principles quantitative research architecture:
1. Dynamic Combinatorial & Genetic Factor Generation across 8 Alpha Families
2. Continuous Loop with Heartbeat Status (data/continuous_miner_status.json)
3. De-duplication against SQLite factor_zoo database (never re-researches same formula)
4. Graceful Stop via signal file (data/stop_continuous_miner.signal) or timer expiry
"""

import os
import sys
import time
import json
import sqlite3
import datetime
import argparse
import signal
import fcntl
import threading
import tempfile
import multiprocessing as mp
import cloudpickle
import numpy as np
import pandas as pd
from typing import Dict, List, Any, Optional

# Add project root to sys.path
BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

sys.path.insert(0, os.path.join(BASE_DIR, "code"))
from autonomous_alpha_research_engine import (
    DB_PATH,
    init_db,
    evaluate_and_score_factor,
    save_factor_to_db,
    compute_formula_hash,
    COMMODITY_SPECS,
)

STATUS_FILE = os.path.join(BASE_DIR, "data", "continuous_miner_status.json")
STOP_SIGNAL_FILE = os.path.join(BASE_DIR, "data", "stop_continuous_miner.signal")
LOCK_FILE = os.path.join(BASE_DIR, "data", "continuous_miner.lock")


def acquire_miner_lock() -> Optional[Any]:
    """Atomically acquires exclusive OS lock for the miner process (Q05)."""
    lock_fd = None
    try:
        lock_fd = open(LOCK_FILE, "w")
        fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        lock_fd.write(f"{os.getpid()}\n")
        lock_fd.flush()
        return lock_fd
    except (BlockingIOError, IOError):
        if lock_fd:
            try:
                lock_fd.close()
            except Exception:
                pass
        return None
    except Exception:
        if lock_fd:
            try:
                lock_fd.close()
            except Exception:
                pass
        return None


def release_miner_lock(lock_fd: Optional[Any]):
    """Releases the exclusive OS lock (Q05: permanent lock file, never unlink to avoid inode race)."""
    if lock_fd:
        try:
            fcntl.flock(lock_fd, fcntl.LOCK_UN)
            lock_fd.close()
        except Exception:
            pass


def _worker_eval_process(pickled_factor: bytes, queue: Any):
    """Isolated subprocess worker function to evaluate factor (Q03/Q06)."""
    tmp_path = None
    try:
        if hasattr(os, "setpgrp"):
            os.setpgrp()
        factor = cloudpickle.loads(pickled_factor)
        from autonomous_alpha_research_engine import evaluate_and_score_factor
        res = evaluate_and_score_factor(factor)
        
        # Q03: Write full evaluation result to temp file to eliminate OS pipe buffer exhaustion deadlock
        fd, tmp_path = tempfile.mkstemp(prefix="alpha_eval_", suffix=".pkl")
        with os.fdopen(fd, "wb") as f:
            cloudpickle.dump(res, f)
        
        queue.put(("OK", tmp_path))
    except Exception as e:
        if tmp_path and os.path.exists(tmp_path):
            try:
                os.remove(tmp_path)
            except Exception:
                pass
        queue.put(("ERR", str(e)))


def run_eval_with_hard_timeout(target_factor: Dict[str, Any], timeout_seconds: float = 45.0) -> Dict[str, Any]:
    """Runs factor evaluation inside an isolated subprocess with OS hard kill on timeout (Q03/Q06)."""
    ctx = mp.get_context("spawn")  # ponytail: fork deadlocks with heartbeat thread; spawn is safe because args are already cloudpickle bytes
    q = ctx.Queue()
    p = ctx.Process(target=_worker_eval_process, args=(cloudpickle.dumps(target_factor), q))
    p.start()
    p.join(timeout=timeout_seconds)

    if p.is_alive():
        # Q06: Terminate process group to prevent orphan processes
        try:
            if hasattr(os, "killpg"):
                os.killpg(p.pid, signal.SIGTERM)
            else:
                p.terminate()
        except Exception:
            p.terminate()
        p.join(timeout=1.0)
        if p.is_alive():
            try:
                if hasattr(os, "killpg"):
                    os.killpg(p.pid, signal.SIGKILL)
                else:
                    p.kill()
            except Exception:
                p.kill()
            p.join(timeout=1.0)
        raise TimeoutError(f"Factor evaluation timed out (> {timeout_seconds}s)")

    if not q.empty():
        status, data = q.get()
        if status == "OK":
            temp_file_path = data
            try:
                with open(temp_file_path, "rb") as f:
                    res = cloudpickle.load(f)
                return res
            finally:
                if os.path.exists(temp_file_path):
                    try:
                        os.remove(temp_file_path)
                    except Exception:
                        pass
        else:
            raise RuntimeError(data)
    raise RuntimeError("Worker process terminated unexpectedly without returning result")


class MinerHeartbeatThread(threading.Thread):
    """Independent low-overhead heartbeat thread using monotonic clock (Q04)."""
    def __init__(self, status_data_ref: Dict[str, Any], start_mono: float, duration_seconds: int):
        super().__init__(daemon=True)
        self.status_data = status_data_ref
        self.start_mono = start_mono
        self.duration_seconds = duration_seconds
        self.stopped = threading.Event()

    def run(self):
        while not self.stopped.wait(1.0):
            elapsed = time.monotonic() - self.start_mono
            remaining = max(0.0, self.duration_seconds - elapsed)
            self.status_data["elapsed_seconds"] = int(elapsed)
            self.status_data["remaining_seconds"] = int(remaining)
            self.status_data["updated_at"] = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            write_status(self.status_data)

    def stop(self):
        self.stopped.set()

def generate_combinatorial_candidate_pool() -> List[Dict[str, Any]]:
    """
    Generates a large pool of 100+ economically sound, diverse candidate factors across:
    1. Multi-horizon momentum & slope
    2. Donchian & Keltner Breakouts
    3. Kaufman Efficiency & Path SNR
    4. Volatility dynamics (Parkinson / Garman-Klass / Squeeze)
    5. Intraday CLV & Volume Shock
    6. Orthogonal Composites & Voting systems
    """
    pool: List[Dict[str, Any]] = []

    # --- 1. Momentum Horizons ---
    for w in [5, 8, 12, 16, 24, 32, 48, 64]:
        fid = f"FAC_MOM_W{w}"
        pool.append({
            "id": fid,
            "name": f"{w}周期波动率归一化动量 (Normalized Momentum {w})",
            "family": "动量家族 (Momentum)",
            "hypothesis": f"机构在 {w} 周期中形成持续性持仓位移，经过真实波幅 ATR 归一化后具备正向统计溢价。",
            "formula": f"(Close[t] - Close[t-{w}]) / ATR[{w}]",
            "calc": (lambda win: lambda df: (df["close"] - df["close"].shift(win)) / (
                pd.concat([df["high"] - df["low"], (df["high"] - df["close"].shift(1)).abs(), (df["low"] - df["close"].shift(1)).abs()], axis=1).max(axis=1).rolling(win).mean() + 1e-6
            ))(w),
            "direction": 1,
        })

    # --- 2. EMA Spread Acceleration ---
    for (f, s) in [(5, 15), (8, 24), (10, 30), (12, 36), (15, 45), (20, 60)]:
        fid = f"FAC_EMA_DIFF_{f}_{s}"
        pool.append({
            "id": fid,
            "name": f"双均线偏离扩散率 ({f}/{s} EMA Spread)",
            "family": "动量家族 (Momentum)",
            "hypothesis": f"短周期 {f} EMA 穿越长周期 {s} EMA 形成扩散能量差，提前识别单边波段爆发斜率。",
            "formula": f"(EMA[{f}] - EMA[{s}]) / ATR[{s}]",
            "calc": (lambda fast, slow: lambda df: (df["close"].ewm(span=fast).mean() - df["close"].ewm(span=slow).mean()) / (
                pd.concat([df["high"] - df["low"], (df["high"] - df["close"].shift(1)).abs(), (df["low"] - df["close"].shift(1)).abs()], axis=1).max(axis=1).rolling(slow).mean() + 1e-6
            ))(f, s),
            "direction": 1,
        })

    # --- 3. Donchian Channel Expansion ---
    for w in [15, 25, 35, 45, 55, 70]:
        fid = f"FAC_BRK_DON_{w}"
        pool.append({
            "id": fid,
            "name": f"{w}周期唐奇安通道极值突破 (Donchian Breakout {w})",
            "family": "通道突破 (Breakout)",
            "hypothesis": f"突破过去 {w} 根 Bar 极值高点意味着存量流动性被扫清，边际买盘形成新估值共识。",
            "formula": f"(Close - MaxHigh[{w}]) / ATR[{w}]",
            "calc": (lambda win: lambda df: (df["close"] - df["high"].shift(1).rolling(win).max()) / (
                pd.concat([df["high"] - df["low"], (df["high"] - df["close"].shift(1)).abs(), (df["low"] - df["close"].shift(1)).abs()], axis=1).max(axis=1).rolling(win).mean() + 1e-6
            ))(w),
            "direction": 1,
        })

    # --- 4. Kaufman Path Efficiency & SNR ---
    for w in [10, 14, 18, 22, 28, 36, 48]:
        fid = f"FAC_SNR_ER_{w}"
        pool.append({
            "id": fid,
            "name": f"{w}周期路径信噪比纯度 (Path SNR Efficiency {w})",
            "family": "趋势质量 (Trend Quality)",
            "hypothesis": f"价格在 {w} 周期内的净位移除以总路径长度，信噪比高于阈值过滤假突破与高频锯齿。",
            "formula": f"(|Close - Close[{w}]| / Sum(|Diff|, {w})) * Sign(Close - Close[{w}])",
            "calc": (lambda win: lambda df: ((df["close"] - df["close"].shift(win)).abs() / (df["close"].diff().abs().rolling(win).sum() + 1e-6)) * np.sign(df["close"] - df["close"].shift(win)))(w),
            "direction": 1,
        })

    # --- 5. Bollinger Band Squeeze & Volatility Expansion ---
    for w in [15, 20, 30, 40]:
        for q in [0.15, 0.25]:
            fid = f"FAC_VOL_SQZ_{w}_Q{int(q*100)}"
            pool.append({
                "id": fid,
                "name": f"{w}周期布林极度窄幅收敛挤压 (Bandwidth Squeeze {w}/Q{int(q*100)})",
                "family": "波动率动力学 (Volatility)",
                "hypothesis": f"波动率在 {w} 周期带宽收缩至前序分布 {int(q*100)}% 极低分位，标志能量蓄积完成后的方向性爆破。",
                "formula": f"(Bandwidth[{w}] <= Quantile({q})) * Sign(Close - SMA[{w}])",
                "calc": (lambda win, q_val: lambda df: (
                    ((df["close"].rolling(win).std() * 4.0 / (df["close"].rolling(win).mean() + 1e-6)) <=
                     (df["close"].rolling(win).std() * 4.0 / (df["close"].rolling(win).mean() + 1e-6)).rolling(win * 3).quantile(q_val)).astype(float) *
                    np.sign(df["close"] - df["close"].rolling(win).mean())
                ))(w, q),
                "direction": 1,
            })

    # --- 6. Volume Pulse & Micro-Flow Imbalance ---
    for w in [10, 15, 20, 30]:
        fid = f"FAC_VLM_CLV_{w}"
        pool.append({
            "id": fid,
            "name": f"{w}周期微观收盘位置放量共振 (Volume-CLV Resonance {w})",
            "family": "量价共振 (Price-Volume)",
            "hypothesis": f"在收盘贴近最高价 (CLV接近1) 时爆发成交量冲击，表明买方主动吃单吞噬卖单流动性深度。",
            "formula": f"CLV * Log(Volume / SMA(Volume, {w}) + 1.0)",
            "calc": (lambda win: lambda df: (
                (((df["close"] - df["low"]) - (df["high"] - df["close"])) / (df["high"] - df["low"] + 1e-6)) *
                np.log((df["volume"] / (df["volume"].rolling(win).mean() + 1e-6)).clip(lower=0.5, upper=4.0) + 1.0)
            ))(w),
            "direction": 1,
        })

    # --- 7. Orthogonal Tri-Component High-Score Composites ---
    for (mw, bw, vw) in [(15, 20, 20), (20, 25, 20), (24, 30, 25), (30, 40, 30)]:
        fid = f"FAC_ORTHO_TRI_{mw}_{bw}"
        pool.append({
            "id": fid,
            "name": f"正交趋势-信噪比-动能三元共振系统 (Ortho Tri-System {mw}/{bw})",
            "family": "正交复合 Alpha (Orthogonal)",
            "hypothesis": f"将趋势效率比 ER({mw})、通道突破({bw}) 与成交量脉冲({vw}) 几何正交相乘，兼顾胜率与盈亏比。",
            "formula": f"BreakoutStrength[{bw}] * EfficiencyRatio[{mw}] * (Volume / SMA(Vol, {vw}))",
            "calc": (lambda m, b, v: lambda df: (
                ((df["close"] - df["high"].shift(1).rolling(b).max()) / (
                    pd.concat([df["high"] - df["low"], (df["high"] - df["close"].shift(1)).abs(), (df["low"] - df["close"].shift(1)).abs()], axis=1).max(axis=1).rolling(b).mean() + 1e-6
                )) *
                ((df["close"] - df["close"].shift(m)).abs() / (df["close"].diff().abs().rolling(m).sum() + 1e-6)).clip(lower=0.0, upper=1.0) *
                (df["volume"] / (df["volume"].rolling(v).mean() + 1e-6)).clip(lower=0.5, upper=3.5)
            ))(mw, bw, vw),
            "direction": 1,
        })

    
    # --- 8. Z-Score Mean Reversion Variations ---
    for w in [15, 20, 30, 45]:
        fid = f"FAC_MR_Z_{w}"
        pool.append({
            "id": fid,
            "name": f"{w}周期残差Z-Score极值均值反转 (Z-Score Reversion {w})",
            "family": "均值回归 (Mean Reversion)",
            "hypothesis": f"价格在 {w} 周期远离中枢均线超过 2 个标准差，短期过度抛压或踩踏带来均值修复。",
            "formula": f"-(Close - SMA[{w}]) / (Std[{w}] + 1e-6)",
            "calc": (lambda win: lambda df: -(df["close"] - df["close"].rolling(win).mean()) / (df["close"].rolling(win).std() + 1e-6))(w),
            "direction": 1,
        })

    # --- 9. Multi-Window Parkinson High-Low Volatility Breakout ---
    for w in [10, 20, 30]:
        fid = f"FAC_VOL_PARK_{w}"
        pool.append({
            "id": fid,
            "name": f"{w}周期日内极差波动率突破 (Parkinson Extreme Vol {w})",
            "family": "波动率动力学 (Volatility)",
            "hypothesis": f"基于对数高低极差的高频波动率较传统收盘价波动更敏感，突破均值预示趋势展开。",
            "formula": f"(ParkinsonVol[{w}] / RollingMean(ParkinsonVol, {w*2})) * Sign(Close - Open)",
            "calc": (lambda win: lambda df: (
                (vol := np.sqrt(np.log(df["high"] / (df["low"] + 1e-6))**2 / (4.0 * np.log(2.0)))) /
                (vol.rolling(win).mean() / vol.rolling(win * 2).mean() + 1e-6)
            ) * np.sign(df["close"] - df["open"]))(w),
            "direction": 1,
        })

    # --- 10. Multi-Horizon Chandelier Trailing Adaptive System ---
    for (hw, mult) in [(18, 2.5), (22, 3.0), (30, 3.5)]:
        fid = f"FAC_CHANDELIER_{hw}_{int(mult*10)}"
        pool.append({
            "id": fid,
            "name": f"{hw}周期动态吊灯自适应追踪 ({hw} Chandelier x{mult})",
            "family": "趋势追踪体系 (Trend Following)",
            "hypothesis": f"基于自适应通道锁定多头趋势，动态追踪止损截断左尾风险。",
            "formula": f"TrendDirection * (1.0 - (Highest[{hw}] - Close) / ({mult} * ATR[{hw}] + 1e-6))",
            "calc": (lambda w_val, m_val: lambda df: (
                np.sign(df["close"] - df["close"].rolling(w_val).mean()) *
                (1.0 - ((df["high"].rolling(w_val).max() - df["close"]) / (
                    pd.concat([df["high"] - df["low"], (df["high"] - df["close"].shift(1)).abs(), (df["low"] - df["close"].shift(1)).abs()], axis=1).max(axis=1).rolling(w_val).mean() * m_val + 1e-6
                )).clip(lower=0.0, upper=1.5))
            ))(hw, mult),
            "direction": 1,
        })

    # --- 11. High-Order Orthogonal Composite Alphas ---
    from autonomous_alpha_research_engine import ALPHA_FAMILIES
    for f in ALPHA_FAMILIES:
        if "COMP" in f["id"] and not any(p["id"] == f["id"] for p in pool):
            pool.append(f)

    return pool

def generate_dynamic_mutation(idx: int) -> Dict[str, Any]:
    """
    Generates a vast, non-repeating stream of 27,000+ novel factor hypotheses via 
    multi-scale orthogonal primitives and prime parameters (P0 Fix for question.md).
    """
    primes_a = [7, 11, 13, 17, 19, 23, 29, 31, 37, 41, 43, 47, 53, 59, 61, 67, 71, 73, 79, 83, 89, 97]
    primes_b = [3, 5, 7, 11, 13, 17, 19, 23, 29, 31, 37, 41]
    primes_c = [5, 10, 15, 20, 25, 30, 35, 40, 45, 50, 60, 75, 90]

    family_idx = idx % 8
    rem = idx // 8
    p_a = primes_a[rem % len(primes_a)]
    rem = rem // len(primes_a)
    p_b = primes_b[rem % len(primes_b)]
    rem = rem // len(primes_b)
    p_c = primes_c[rem % len(primes_c)]

    if family_idx == 0:
        # MOM_SNR: Multi-scale Momentum × Efficiency Ratio with ATR normalization
        return {
            "id": f"FAC_DYN_MSNR_{idx}_{p_a}_{p_b}",
            "name": f"多尺度动量效率比共振变体 #{idx} (P={p_a}/E={p_b})",
            "family": "动量家族 (Momentum)",
            "hypothesis": f"在 {p_a} 周期动量基础上，使用 {p_b} 周期 Kaufman 效率比作为几何纯度权重进行信噪比放大。",
            "formula": f"EfficiencyRatio[{p_b}] * (Close - Close.shift({p_a})) / (ATR[{p_b}] + 1e-6)",
            "calc": (lambda win_m, win_er: lambda df: (
                ((df["close"] - df["close"].shift(win_er)).abs() / (df["close"].diff().abs().rolling(win_er).sum() + 1e-6)) *
                ((df["close"] - df["close"].shift(win_m)) / (
                    pd.concat([df["high"] - df["low"], (df["high"] - df["close"].shift(1)).abs(), (df["low"] - df["close"].shift(1)).abs()], axis=1).max(axis=1).rolling(win_er).mean() + 1e-6
                ))
            ))(p_a, p_b),
            "direction": 1,
        }
    elif family_idx == 1:
        # BRK_VOL: Volatility Channel Expansion Breakout
        mult = 1.0 + (p_b % 5) * 0.25
        return {
            "id": f"FAC_DYN_BVOL_{idx}_{p_a}_{p_c}",
            "name": f"自适应波动率通道扩张突破变体 #{idx} (W={p_a}/A={p_c})",
            "family": "通道突破 (Breakout)",
            "hypothesis": f"价格在突破过去 {p_a} 周期最高价时，按 {p_c} 周期动态 ATR 的 {mult:.2f} 倍归一化。",
            "formula": f"(Close - MaxHigh[{p_a}]) / (ATR[{p_c}] * {mult:.2f} + 1e-6)",
            "calc": (lambda win_h, win_a, m: lambda df: (
                (df["close"] - df["high"].shift(1).rolling(win_h).max()) / (
                    pd.concat([df["high"] - df["low"], (df["high"] - df["close"].shift(1)).abs(), (df["low"] - df["close"].shift(1)).abs()], axis=1).max(axis=1).rolling(win_a).mean() * m + 1e-6
                )
            ))(p_a, p_c, mult),
            "direction": 1,
        }
    elif family_idx == 2:
        # VWAP_REV: Volume-Weighted Price Discrepancy Reversion
        return {
            "id": f"FAC_DYN_VREV_{idx}_{p_a}_{p_b}",
            "name": f"成交量加权筹码偏离反转变体 #{idx} (V={p_a}/A={p_b})",
            "family": "均值回归 (Mean Reversion)",
            "hypothesis": f"在 {p_a} 周期内价格显著偏离加权均价，以 {p_b} 周期 ATR 进行自适应波动归一化后执行均值回归。",
            "formula": f"-(Close - RollingVWAP[{p_a}]) / (ATR[{p_b}] + 1e-6)",
            "calc": (lambda win_v, win_a: lambda df: (
                -(df["close"] - (df["close"] * df["volume"]).rolling(win_v).sum() / (df["volume"].rolling(win_v).sum() + 1e-6)) / (
                    pd.concat([df["high"] - df["low"], (df["high"] - df["close"].shift(1)).abs(), (df["low"] - df["close"].shift(1)).abs()], axis=1).max(axis=1).rolling(win_a).mean() + 1e-6
                )
            ))(p_a, p_b),
            "direction": 1,
        }
    elif family_idx == 3:
        # ORTHO_COMP: Multi-scale EMA cross × Volume Pulse
        e_fast = p_b + 2
        e_slow = e_fast + p_a
        return {
            "id": f"FAC_COMP_DYN_{idx}_{e_fast}_{e_slow}_{p_c}",
            "name": f"正交均线动量与量能脉冲复合变体 #{idx} ({e_fast}/{e_slow}/V={p_c})",
            "family": "正交复合 Alpha (Orthogonal)",
            "hypothesis": f"快慢均线 ({e_fast}/{e_slow}) 趋势动量与 {p_c} 周期相对成交量脉冲正交相乘，震荡市主动静默。",
            "formula": f"((EMA[{e_fast}] - EMA[{e_slow}]) / ATR[{e_slow}]) * Log(Volume / SMA(Volume, {p_c}) + 1.0)",
            "calc": (lambda f, s, v: lambda df: (
                (df["close"].ewm(span=f).mean() - df["close"].ewm(span=s).mean()) / (
                    pd.concat([df["high"] - df["low"], (df["high"] - df["close"].shift(1)).abs(), (df["low"] - df["close"].shift(1)).abs()], axis=1).max(axis=1).rolling(s).mean() + 1e-6
                ) * np.log((df["volume"] / (df["volume"].rolling(v).mean() + 1e-6)).clip(lower=0.5, upper=4.0) + 1.0)
            ))(e_fast, e_slow, p_c),
            "direction": 1,
        }
    elif family_idx == 4:
        # CLV_PV: Close-Location-Value Money Flow Proxy with volume weighting
        return {
            "id": f"FAC_DYN_CLV_{idx}_{p_a}_{p_b}",
            "name": f"微观订单流筹码吸收变体 #{idx} (C={p_a}/V={p_b})",
            "family": "量价共振 (Price-Volume)",
            "hypothesis": f"结合 {p_a} 周期收盘价微观分位数与 {p_b} 周期成交量比率，测度主力资金盘中微观吸收强度。",
            "formula": f"((2*Close - High - Low) / (High - Low + 1e-6)).rolling({p_a}).mean() * (Volume / SMA(Volume, {p_b}))",
            "calc": (lambda c_win, v_win: lambda df: (
                (((2 * df["close"] - df["high"] - df["low"]) / (df["high"] - df["low"] + 1e-6)).rolling(c_win).mean()) *
                (df["volume"] / (df["volume"].rolling(v_win).mean() + 1e-6)).clip(lower=0.5, upper=3.5)
            ))(p_a, p_b),
            "direction": 1,
        }
    elif family_idx == 5:
        # VOL_EXP: Volatility Expansion Ratio with Directional Impulse
        v_fast = p_b + 2
        v_slow = v_fast + p_a
        return {
            "id": f"FAC_DYN_VEXP_{idx}_{v_fast}_{v_slow}_{p_c}",
            "name": f"波动率挤压扩张动力学变体 #{idx} ({v_fast}/{v_slow}/M={p_c})",
            "family": "波动率动力学 (Volatility)",
            "hypothesis": f"短长周期波动率比率 ({v_fast}/{v_slow}) 发生突变，顺应 {p_c} 周期价格位移方向启动。",
            "formula": f"(ATR[{v_fast}] / (ATR[{v_slow}] + 1e-6)) * Sign(Close - Close.shift({p_c}))",
            "calc": (lambda vf, vs, ms: lambda df: (
                pd.concat([df["high"] - df["low"], (df["high"] - df["close"].shift(1)).abs(), (df["low"] - df["close"].shift(1)).abs()], axis=1).max(axis=1).rolling(vf).mean() /
                (pd.concat([df["high"] - df["low"], (df["high"] - df["close"].shift(1)).abs(), (df["low"] - df["close"].shift(1)).abs()], axis=1).max(axis=1).rolling(vs).mean() + 1e-6)
            ) * np.sign(df["close"] - df["close"].shift(ms).fillna(df["close"]))
            )(v_fast, v_slow, p_c),
            "direction": 1,
        }
    elif family_idx == 6:
        # ACCEL_MOM: Trend Curvature / Acceleration
        return {
            "id": f"FAC_DYN_ACC_{idx}_{p_a}_{p_b}",
            "name": f"多阶趋势加速度与二阶曲率变体 #{idx} (A={p_a}/B={p_b})",
            "family": "趋势质量 (Trend Quality)",
            "hypothesis": f"测算 {p_a} 周期价格二阶差分加速度，在动能曲率发生拐点时提前识别波段主升段。",
            "formula": f"(Close.diff(1).diff({p_a})) / (ATR[{p_b}] + 1e-6)",
            "calc": (lambda w_a, w_b: lambda df: (
                df["close"].diff(1).diff(w_a) / (
                    pd.concat([df["high"] - df["low"], (df["high"] - df["close"].shift(1)).abs(), (df["low"] - df["close"].shift(1)).abs()], axis=1).max(axis=1).rolling(w_b).mean() + 1e-6
                )
            ))(p_a, p_b),
            "direction": 1,
        }
    else:
        # EXH_REV: Shadow Pinbar Reversal
        return {
            "id": f"FAC_DYN_EXH_{idx}_{p_a}_{p_b}",
            "name": f"极值影线博弈力竭反转变体 #{idx} (P={p_a}/A={p_b})",
            "family": "竭尽反转 (Exhaustion)",
            "hypothesis": f"在 {p_a} 周期极值点附近出现长影线，显示买卖对手盘流动性竭尽，触发高确定性反转。",
            "formula": f"((Low - Min(O,C)) - (High - Max(O,C))) / (ATR[{p_b}] + 1e-6)",
            "calc": (lambda w_a, w_b: lambda df: (
                (df["low"] - np.minimum(df["open"], df["close"])) -
                (df["high"] - np.maximum(df["open"], df["close"]))
            ) / (
                pd.concat([df["high"] - df["low"], (df["high"] - df["close"].shift(1)).abs(), (df["low"] - df["close"].shift(1)).abs()], axis=1).max(axis=1).rolling(w_b).mean() + 1e-6
            ))(p_a, p_b),
            "direction": 1,
        }

_status_lock = threading.Lock()  # ponytail: heartbeat thread + main thread both call write_status

def write_status(data: Dict[str, Any]):
    """Atomically writes miner status JSON file."""
    with _status_lock:
        try:
            temp_file = STATUS_FILE + ".tmp"
            with open(temp_file, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            os.replace(temp_file, STATUS_FILE)
        except Exception as e:
            print(f"Warning: Failed to write status file: {e}", file=sys.stderr)

def get_existing_formula_hashes() -> set:
    """Returns all unique formula_hashes currently in the SQLite database that are formally verified."""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("SELECT DISTINCT formula_hash FROM factor_zoo WHERE formula_hash IS NOT NULL AND status != 'LEGACY_UNVERIFIED';")
    rows = cursor.fetchall()
    conn.close()
    return set(r[0] for r in rows)

def get_legacy_unverified_factors() -> List[Dict[str, Any]]:
    """Returns all factors marked as LEGACY_UNVERIFIED in factor_zoo to be prioritized for re-evaluation (Q02)."""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("SELECT factor_id, name, family, hypothesis, formula_dsl FROM factor_zoo WHERE status = 'LEGACY_UNVERIFIED';")
    rows = cursor.fetchall()
    conn.close()

    from autonomous_alpha_research_engine import ALPHA_FAMILIES
    pool = generate_combinatorial_candidate_pool()
    pool_dict = {f["id"]: f for f in pool}
    for f in ALPHA_FAMILIES:
        pool_dict[f["id"]] = f

    legacy_factors = []
    unresolved_ids = []
    for r in rows:
        fid, name, family, hypothesis, formula_dsl = r
        if fid in pool_dict:
            legacy_factors.append(pool_dict[fid])
        else:
            unresolved_ids.append(fid)

    if unresolved_ids:
        # Q02 绝不偷换计算逻辑为 pct_change(10)，安全归档为 UNRESOLVED_IMPLEMENTATION
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute("PRAGMA table_info(factor_zoo);")
        cols = [c[1] for c in cursor.fetchall()]
        if "fail_reason" in cols:
            cursor.executemany(
                "UPDATE factor_zoo SET status = 'UNRESOLVED_IMPLEMENTATION', fail_reason = '无法从因子池或DSL解析有效计算逻辑' WHERE factor_id = ?;",
                [(fid,) for fid in unresolved_ids]
            )
        else:
            cursor.executemany(
                "UPDATE factor_zoo SET status = 'UNRESOLVED_IMPLEMENTATION' WHERE factor_id = ?;",
                [(fid,) for fid in unresolved_ids]
            )
        conn.commit()
        conn.close()
        print(f"⚠️ [Q02] 发现 {len(unresolved_ids)} 个未知实现的遗留因子，已安全标记为 UNRESOLVED_IMPLEMENTATION，禁止伪造计算逻辑。")

    return legacy_factors

def run_continuous_miner(duration_seconds: int = 3600, interval_seconds: float = 2.0):
    """
    Main continuous mining loop running for specified duration (default 1 hour = 3600s).
    Guaranteed zero duplication via formula SHA-256 hash tracking.
    """
    init_db()

    # Q05: 原子文件排他锁，防止多实例并发踩踏
    lock_fd = acquire_miner_lock()
    if lock_fd is None:
        print("❌ Another continuous miner instance is already running (OS lock held). Aborting startup.")
        return

    if os.path.exists(STOP_SIGNAL_FILE):
        try:
            os.remove(STOP_SIGNAL_FILE)
        except Exception:
            pass

    start_mono = time.monotonic()
    start_time = time.time()
    pid = os.getpid()
    print(f"🚀 Continuous Alpha Miner started (PID={pid}) for {duration_seconds}s (1小时自动挖掘模式)...")

    pool = generate_combinatorial_candidate_pool()
    existing_hashes = get_existing_formula_hashes()
    legacy_candidates = get_legacy_unverified_factors()
    untested_candidates = [
        f for f in pool 
        if compute_formula_hash(f.get("formula", "")) not in existing_hashes
    ]

    print(f"  -> Candidate factor space: {len(pool)} primary pool, {len(legacy_candidates)} legacy unverified, {len(untested_candidates)} untested in pool, {len(existing_hashes)} verified in DB.")

    evaluated_count = 0
    latest_record = None

    status_data = {
        "is_running": True,
        "pid": pid,
        "start_time": int(start_time),
        "duration_seconds": duration_seconds,
        "elapsed_seconds": 0,
        "remaining_seconds": duration_seconds,
        "total_evaluated_this_run": 0,
        "total_in_zoo": len(existing_hashes),
        "latest_factor_id": None,
        "latest_factor_name": None,
        "latest_factor_score": None,
        "latest_factor_status": None,
        "current_evaluating_factor": None,
        "current_evaluating_name": None,
        "updated_at": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    }
    write_status(status_data)

    # Q04: 启动独立低开销心跳线程与单调时钟
    heartbeat_thread = MinerHeartbeatThread(status_data, start_mono, duration_seconds)
    heartbeat_thread.start()

    # Register graceful signal handlers
    def handle_signal(sig, frame):
        print("\n🛑 Stop signal received. Gracefully shutting down...")
        heartbeat_thread.stop()
        heartbeat_thread.join(timeout=1.0)
        status_data["is_running"] = False
        write_status(status_data)
        release_miner_lock(lock_fd)
        sys.exit(0)

    signal.signal(signal.SIGINT, handle_signal)
    signal.signal(signal.SIGTERM, handle_signal)

    legacy_idx = 0
    idx = 0
    mutation_seed = 0
    # ponytail: family-level adaptive skip for search efficiency (P2-1)
    family_consecutive_fails = {}
    FAMILY_SKIP_THRESHOLD = 15

    try:
        while True:
            elapsed = time.monotonic() - start_mono
            remaining = max(0.0, duration_seconds - elapsed)

            if elapsed >= duration_seconds:
                print(f"⏰ Duration target reached ({duration_seconds}s). 1-hour session completed!")
                break

            if os.path.exists(STOP_SIGNAL_FILE):
                print("🛑 Found stop signal file. Halting continuous research.")
                try:
                    os.remove(STOP_SIGNAL_FILE)
                except Exception:
                    pass
                break

            target_factor = None
            # Priority 1: Legacy unverified factors needing re-audit under strict OOS rules
            while legacy_idx < len(legacy_candidates):
                cand = legacy_candidates[legacy_idx]
                legacy_idx += 1
                cand_hash = compute_formula_hash(cand.get("formula", ""))
                if cand_hash not in existing_hashes:
                    target_factor = cand
                    print(f"  🔄 [Priority Re-Evaluation] Re-auditing legacy factor: {cand['id']}")
                    break

            # Priority 2: Primary predefined candidate pool
            if target_factor is None:
                while idx < len(untested_candidates):
                    cand = untested_candidates[idx]
                    idx += 1
                    cand_hash = compute_formula_hash(cand.get("formula", ""))
                    if cand_hash not in existing_hashes:
                        target_factor = cand
                        break

            # Priority 3: Dynamic high-order orthogonal mutations (27,000+ combinations)
            if target_factor is None:
                attempts = 0
                while attempts < 500:
                    mutation_seed += 1
                    cand = generate_dynamic_mutation(mutation_seed)
                    cand_hash = compute_formula_hash(cand.get("formula", ""))
                    if cand_hash not in existing_hashes:
                        fam = cand.get("family", "")
                        if family_consecutive_fails.get(fam, 0) >= FAMILY_SKIP_THRESHOLD:
                            attempts += 1
                            continue
                        target_factor = cand
                        break
                    attempts += 1

                # If all families saturated, reset fail counters to prevent stalling
                if target_factor is None and family_consecutive_fails:
                    family_consecutive_fails.clear()

            if target_factor is None:
                print("  -> Searching next parameter subspace. Pausing...")
                time.sleep(interval_seconds * 2)
                continue

            fid = target_factor["id"]
            fname = target_factor["name"]
            f_hash = compute_formula_hash(target_factor.get("formula", ""))
            print(f"[{evaluated_count + 1}] Evaluating Factor: {fid} | {fname} (hash: {f_hash[:8]})...")

            status_data["current_evaluating_factor"] = fid
            status_data["current_evaluating_name"] = fname

            task_timeout = min(45.0, max(1.0, duration_seconds - elapsed))
            if duration_seconds - elapsed < 2.0:
                print("⏰ Less than 2s remaining in session budget. Ending cleanly (Q10).")
                break

            try:
                # Q03/Q06/Q10: 独立子进程硬杀超时保障与动态单调截止时间
                record = run_eval_with_hard_timeout(target_factor, timeout_seconds=task_timeout)

                save_factor_to_db(record)
                existing_hashes.add(f_hash)
                evaluated_count += 1
                latest_record = record

                # P2-1: 更新 family 连续淘汰计数
                fam = target_factor.get("family", "")
                if record["status"] == "GRAVEYARD":
                    family_consecutive_fails[fam] = family_consecutive_fails.get(fam, 0) + 1
                else:
                    family_consecutive_fails[fam] = 0

                badge = "👑 EXCELLENT" if record["status"] == "EXCELLENT" else ("🔬 CANDIDATE" if record["status"] == "CANDIDATE" else "🪦 GRAVEYARD")
                print(f"  -> Result: [{record['grade']} {record['total_score']}分] {badge} | PassRate={record['cross_market_pass_rate']}%")

                # Update status file with newly evaluated factor
                status_data.update({
                    "total_evaluated_this_run": evaluated_count,
                    "total_in_zoo": len(existing_hashes),
                    "latest_factor_id": record["factor_id"],
                    "latest_factor_name": record["name"],
                    "latest_factor_score": record["total_score"],
                    "latest_factor_status": record["status"],
                    "latest_fail_reason": record["fail_reason"],
                    "current_evaluating_factor": None,
                    "current_evaluating_name": None,
                })
                write_status(status_data)

            except TimeoutError:
                print(f"  ❌ Single factor evaluation timed out (>45s) for {fid}. Subprocess hard killed. Skipping...", file=sys.stderr)
                existing_hashes.add(f_hash)
                status_data["current_evaluating_factor"] = None
                status_data["current_evaluating_name"] = None
            except Exception as e:
                print(f"  ❌ Error evaluating {fid}: {e}", file=sys.stderr)
                status_data["current_evaluating_factor"] = None
                status_data["current_evaluating_name"] = None

            time.sleep(interval_seconds)

    finally:
        heartbeat_thread.stop()
        heartbeat_thread.join(timeout=1.5)
        # Finalize
        status_data["is_running"] = False
        status_data["elapsed_seconds"] = int(time.monotonic() - start_mono)
        status_data["remaining_seconds"] = 0
        status_data["current_evaluating_factor"] = None
        status_data["current_evaluating_name"] = None
        status_data["updated_at"] = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        write_status(status_data)
        release_miner_lock(lock_fd)
        print(f"✅ Continuous Alpha Miner finished. Total new factors evaluated: {evaluated_count}.")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Continuous Autonomous Alpha Miner")
    parser.add_argument("--duration", type=int, default=3600, help="Duration in seconds to run (default: 3600 = 1 hour)")
    parser.add_argument("--interval", type=float, default=2.0, help="Interval between factor evaluations (default: 2.0s)")
    args = parser.parse_args()

    run_continuous_miner(duration_seconds=args.duration, interval_seconds=args.interval)
