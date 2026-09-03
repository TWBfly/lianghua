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
    """Generates an infinite stream of novel factor hypotheses via genetic parameter mutation."""
    m_win = 10 + (idx * 3) % 50
    e_fast = 5 + (idx * 2) % 20
    e_slow = e_fast + 10 + (idx * 5) % 40
    vol_win = 10 + (idx * 4) % 30

    types = ["MOM_SNR", "BRK_VOL", "VWAP_REV", "ORTHO_COMP"]
    chosen = types[idx % len(types)]

    if chosen == "MOM_SNR":
        return {
            "id": f"FAC_DYN_MSNR_{idx}_{m_win}",
            "name": f"自适应多尺度动量信噪比变体 #{idx} (M={m_win})",
            "family": "动量家族 (Momentum)",
            "hypothesis": f"基于动态遗传参数 {m_win} 周期的信噪比加权动量，捕捉不同时间尺度的趋势启动点。",
            "formula": f"EfficiencyRatio[{m_win}] * NormalizedMomentum[{m_win}]",
            "calc": (lambda win: lambda df: (
                ((df["close"] - df["close"].shift(win)).abs() / (df["close"].diff().abs().rolling(win).sum() + 1e-6)) *
                ((df["close"] - df["close"].shift(win)) / (
                    pd.concat([df["high"] - df["low"], (df["high"] - df["close"].shift(1)).abs(), (df["low"] - df["close"].shift(1)).abs()], axis=1).max(axis=1).rolling(win).mean() + 1e-6
                ))
            ))(m_win),
            "direction": 1,
        }
    elif chosen == "BRK_VOL":
        return {
            "id": f"FAC_DYN_BVOL_{idx}_{vol_win}",
            "name": f"动态波动率通道扩张突破变体 #{idx} (V={vol_win})",
            "family": "通道突破 (Breakout)",
            "hypothesis": f"在 {vol_win} 周期波动率通道上轨发生突变时介入，动态自适应商品微观波动周期。",
            "formula": f"(Close - MaxHigh[{vol_win}]) / (ATR[{vol_win}] * 1.5 + 1e-6)",
            "calc": (lambda win: lambda df: (
                (df["close"] - df["high"].shift(1).rolling(win).max()) / (
                    pd.concat([df["high"] - df["low"], (df["high"] - df["close"].shift(1)).abs(), (df["low"] - df["close"].shift(1)).abs()], axis=1).max(axis=1).rolling(win).mean() * 1.5 + 1e-6
                )
            ))(vol_win),
            "direction": 1,
        }
    elif chosen == "VWAP_REV":
        return {
            "id": f"FAC_DYN_VREV_{idx}_{vol_win}",
            "name": f"成交量加权筹码偏离反转变体 #{idx} (W={vol_win})",
            "family": "均值回归 (Mean Reversion)",
            "hypothesis": f"价格在 {vol_win} 周期严重脱离成交量加权均价，产生过冲修正动力。",
            "formula": f"-(Close - RollingVWAP[{vol_win}]) / ATR[{vol_win}]",
            "calc": (lambda win: lambda df: -(df["close"] - (df["close"] * df["volume"]).rolling(win).sum() / (df["volume"].rolling(win).sum() + 1e-6)) / (
                pd.concat([df["high"] - df["low"], (df["high"] - df["close"].shift(1)).abs(), (df["low"] - df["close"].shift(1)).abs()], axis=1).max(axis=1).rolling(win).mean() + 1e-6
            ))(vol_win),
            "direction": 1,
        }
    else:
        return {
            "id": f"FAC_COMP_DYN_{idx}_{e_fast}_{e_slow}",
            "name": f"正交双均线量价复合变体 #{idx} ({e_fast}/{e_slow})",
            "family": "正交复合 Alpha (Orthogonal)",
            "hypothesis": f"将 {e_fast}/{e_slow} EMA 动量差与微观成交量主动性正交相乘，实现全天候跨品种稳健收益。",
            "formula": f"((EMA[{e_fast}] - EMA[{e_slow}]) / ATR[{e_slow}]) * Log(Volume / SMA(Volume, {e_fast}) + 1.0)",
            "calc": (lambda f, s: lambda df: (
                (df["close"].ewm(span=f).mean() - df["close"].ewm(span=s).mean()) / (
                    pd.concat([df["high"] - df["low"], (df["high"] - df["close"].shift(1)).abs(), (df["low"] - df["close"].shift(1)).abs()], axis=1).max(axis=1).rolling(s).mean() + 1e-6
                ) * np.log((df["volume"] / (df["volume"].rolling(f).mean() + 1e-6)).clip(lower=0.5, upper=4.0) + 1.0)
            ))(e_fast, e_slow),
            "direction": 1,
        }

def write_status(data: Dict[str, Any]):
    """Atomically writes miner status JSON file."""
    try:
        temp_file = STATUS_FILE + ".tmp"
        with open(temp_file, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        os.replace(temp_file, STATUS_FILE)
    except Exception as e:
        print(f"Warning: Failed to write status file: {e}", file=sys.stderr)

def get_existing_formula_hashes() -> set:
    """Returns all unique formula_hashes currently in the SQLite database."""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("SELECT DISTINCT formula_hash FROM factor_zoo WHERE formula_hash IS NOT NULL;")
    rows = cursor.fetchall()
    conn.close()
    return set(r[0] for r in rows)

def run_continuous_miner(duration_seconds: int = 3600, interval_seconds: float = 2.0):
    """
    Main continuous mining loop running for specified duration (default 1 hour = 3600s).
    Guaranteed zero duplication via formula SHA-256 hash tracking.
    """
    init_db()
    if os.path.exists(STOP_SIGNAL_FILE):
        try:
            os.remove(STOP_SIGNAL_FILE)
        except Exception:
            pass

    start_time = time.time()
    pid = os.getpid()
    print(f"🚀 Continuous Alpha Miner started (PID={pid}) for {duration_seconds}s (1小时自动挖掘模式)...")

    pool = generate_combinatorial_candidate_pool()
    existing_hashes = get_existing_formula_hashes()
    untested_candidates = [
        f for f in pool 
        if compute_formula_hash(f.get("formula", "")) not in existing_hashes
    ]

    print(f"  -> Candidate factor space: {len(pool)} total, {len(untested_candidates)} untested unique formulas, {len(existing_hashes)} in DB.")

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
        "updated_at": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    }
    write_status(status_data)

    # Register graceful signal handlers
    def handle_signal(sig, frame):
        print("\n🛑 Stop signal received. Gracefully shutting down...")
        status_data["is_running"] = False
        write_status(status_data)
        sys.exit(0)

    signal.signal(signal.SIGINT, handle_signal)
    signal.signal(signal.SIGTERM, handle_signal)

    idx = 0
    mutation_seed = 0
    while True:
        elapsed = time.time() - start_time
        remaining = max(0, duration_seconds - elapsed)

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

        # Check if we have untested candidates left in the primary pool
        target_factor = None
        while idx < len(untested_candidates):
            cand = untested_candidates[idx]
            idx += 1
            cand_hash = compute_formula_hash(cand.get("formula", ""))
            if cand_hash not in existing_hashes:
                target_factor = cand
                break

        if target_factor is None:
            # Predefined pool evaluated, continuously search novel dynamic mutations
            attempts = 0
            while attempts < 200:
                mutation_seed += 1
                cand = generate_dynamic_mutation(mutation_seed)
                cand_hash = compute_formula_hash(cand.get("formula", ""))
                if cand_hash not in existing_hashes:
                    target_factor = cand
                    break
                attempts += 1

        if target_factor is None:
            print("  -> All mutation combinations for current parameter space evaluated. Pausing...")
            time.sleep(interval_seconds * 2)
            continue

        fid = target_factor["id"]
        fname = target_factor["name"]
        f_hash = compute_formula_hash(target_factor.get("formula", ""))
        print(f"[{evaluated_count + 1}] Evaluating Factor: {fid} | {fname} (hash: {f_hash[:8]})...")

        try:
            record = evaluate_and_score_factor(target_factor)
            save_factor_to_db(record)
            existing_hashes.add(f_hash)
            evaluated_count += 1
            latest_record = record

            badge = "👑 EXCELLENT" if record["status"] == "EXCELLENT" else ("🔬 CANDIDATE" if record["status"] == "CANDIDATE" else "🪦 GRAVEYARD")
            print(f"  -> Result: [{record['grade']} {record['total_score']}分] {badge} | PassRate={record['cross_market_pass_rate']}%")

            existing_hashes.add(f_hash)

            # Update status file
            status_data.update({
                "is_running": True,
                "elapsed_seconds": int(elapsed),
                "remaining_seconds": int(remaining),
                "total_evaluated_this_run": evaluated_count,
                "total_in_zoo": len(existing_hashes),
                "latest_factor_id": record["factor_id"],
                "latest_factor_name": record["name"],
                "latest_factor_score": record["total_score"],
                "latest_factor_status": record["status"],
                "latest_fail_reason": record["fail_reason"],
                "updated_at": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            })
            write_status(status_data)

        except Exception as e:
            print(f"  ❌ Error evaluating {fid}: {e}", file=sys.stderr)

        time.sleep(interval_seconds)

    # Finalize
    status_data["is_running"] = False
    status_data["elapsed_seconds"] = int(time.time() - start_time)
    status_data["remaining_seconds"] = 0
    status_data["updated_at"] = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    write_status(status_data)
    print(f"✅ Continuous Alpha Miner finished. Total new factors evaluated: {evaluated_count}.")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Continuous Autonomous Alpha Miner")
    parser.add_argument("--duration", type=int, default=3600, help="Duration in seconds to run (default: 3600 = 1 hour)")
    parser.add_argument("--interval", type=float, default=2.0, help="Interval between factor evaluations (default: 2.0s)")
    args = parser.parse_args()

    run_continuous_miner(duration_seconds=args.duration, interval_seconds=args.interval)
