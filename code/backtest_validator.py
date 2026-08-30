"""
code/backtest_validator.py — 回测报告统计可靠性验证器

所有审计脚本 import 此模块，确保报告不再出现"3笔交易100%胜率"的小样本幻觉。

硬门禁规则：
1. 单子策略（品种+周期）交易 < 30 笔 → 标为 UNRELIABLE，不计入组合统计
2. 数据时间跨度 < 24 个月 → 标为 DATA_SHORT，发出警告
3. Wilson Score 95% CI 区间宽度 > 30% → 标为 WIDE_CI，胜率结论不可信
4. 组合汇总只展示 RELIABLE 子策略的真实表现
"""

from __future__ import annotations

import math
from datetime import datetime
from typing import Any, Dict, List, Tuple

# ponytail: 这三个阈值是全部"可靠性"逻辑的锚点，改这里就改全局
MIN_TRADES_RELIABLE = 30       # 单子策略最低交易笔数
MIN_DATA_MONTHS = 24           # 最低数据覆盖月数
MAX_WILSON_CI_WIDTH = 0.35     # Wilson CI 区间宽度上限 (30笔样本对应 ~0.35 宽度)

# 可靠性等级
GRADE_A = "A_RELIABLE"         # >= 30 笔, CI 宽度 <= 35%
GRADE_B = "B_MARGINAL"         # 20-29 笔, 勉强参考
GRADE_F = "F_UNRELIABLE"       # < 20 笔, 不可信


def wilson_score_interval(wins: int, total: int, z: float = 1.95996) -> Tuple[float, float]:
    """Wilson Score 95% 置信区间"""
    if total == 0:
        return 0.0, 0.0
    p = wins / total
    denom = 1 + z**2 / total
    center = (p + z**2 / (2 * total)) / denom
    spread = (z * math.sqrt(p * (1 - p) / total + z**2 / (4 * total**2))) / denom
    return max(0.0, center - spread), min(1.0, center + spread)


def grade_reliability(trade_count: int, ci_low: float, ci_high: float) -> str:
    """根据交易笔数和 Wilson CI 宽度给出可靠性等级"""
    ci_width = ci_high - ci_low
    if trade_count >= MIN_TRADES_RELIABLE and ci_width <= MAX_WILSON_CI_WIDTH:
        return GRADE_A
    if trade_count >= 20:
        return GRADE_B
    return GRADE_F


def check_data_coverage(start_time: str, end_time: str) -> Dict[str, Any]:
    """检查数据时间跨度是否足够"""
    try:
        t0 = datetime.fromisoformat(start_time)
        t1 = datetime.fromisoformat(end_time)
        months = (t1.year - t0.year) * 12 + (t1.month - t0.month)
    except (ValueError, TypeError):
        months = 0
    return {
        "data_months": months,
        "data_sufficient": months >= MIN_DATA_MONTHS,
        "data_start": start_time,
        "data_end": end_time,
    }


def stamp_symbol_report(summary: Dict[str, Any], data_start: str = "", data_end: str = "") -> Dict[str, Any]:
    """给单个子策略报告盖上可靠性印章"""
    tc = summary.get("trade_count", 0)
    wr = summary.get("win_rate", 0.0)
    wins = int(round(wr * tc))

    ci_low, ci_high = wilson_score_interval(wins, tc)
    grade = grade_reliability(tc, ci_low, ci_high)
    coverage = check_data_coverage(data_start, data_end) if data_start else {}

    summary["wilson_95_ci"] = [round(ci_low, 4), round(ci_high, 4)]
    summary["ci_width"] = round(ci_high - ci_low, 4)
    summary["reliability_grade"] = grade
    if coverage:
        summary["data_coverage"] = coverage
    return summary


def validate_report(symbol_reports: List[Dict[str, Any]], data_ranges: Dict[str, Dict] = None) -> Dict[str, Any]:
    """
    验证整份报告，返回增强后的报告元数据。

    data_ranges: {(symbol, timeframe): {"start": str, "end": str}} 数据覆盖信息
    """
    if data_ranges is None:
        data_ranges = {}

    reliable = []
    marginal = []
    unreliable = []

    for sr in symbol_reports:
        key = (sr.get("symbol", ""), sr.get("timeframe", ""))
        dr = data_ranges.get(key, {})
        stamp_symbol_report(sr, dr.get("start", ""), dr.get("end", ""))

        grade = sr["reliability_grade"]
        if grade == GRADE_A:
            reliable.append(sr)
        elif grade == GRADE_B:
            marginal.append(sr)
        else:
            unreliable.append(sr)

    # 只用 RELIABLE 子策略算组合真实表现
    rel_trades = sum(s["trade_count"] for s in reliable)
    rel_pnl = sum(s.get("net_pnl", 0) for s in reliable)

    # 全部子策略的原始数字（含不可靠的）
    all_trades = sum(s["trade_count"] for s in symbol_reports)
    all_pnl = sum(s.get("net_pnl", 0) for s in symbol_reports)

    # 数据覆盖不足的品种
    short_data = [
        f"{sr['symbol']}_{sr['timeframe']}"
        for sr in symbol_reports
        if sr.get("data_coverage", {}).get("data_sufficient") is False
    ]

    return {
        "reliability_summary": {
            "reliable_count": len(reliable),
            "marginal_count": len(marginal),
            "unreliable_count": len(unreliable),
            "reliable_trades": rel_trades,
            "reliable_net_pnl": round(rel_pnl, 2),
            "raw_total_trades": all_trades,
            "raw_total_net_pnl": round(all_pnl, 2),
            "short_data_symbols": short_data,
            "verdict": _overall_verdict(reliable, marginal, unreliable, rel_pnl),
        },
    }


def _overall_verdict(reliable, marginal, unreliable, rel_pnl) -> str:
    if not reliable:
        return "⛔ 无任何子策略达到统计可靠标准(30笔+)，报告结论完全不可信"
    pct = len(reliable) / (len(reliable) + len(marginal) + len(unreliable))
    if pct < 0.3:
        return f"⚠️ 仅 {len(reliable)} 个子策略可靠(占比 {pct*100:.0f}%)，结论参考价值有限"
    tag = "盈利" if rel_pnl > 0 else "亏损"
    return f"✅ {len(reliable)} 个可靠子策略 | 可靠组合净利: {rel_pnl:+,.2f} RMB ({tag})"


def format_reliability_banner(validation: Dict[str, Any]) -> str:
    """打印人类可读的可靠性横幅"""
    rs = validation["reliability_summary"]
    lines = [
        "=" * 80,
        "📊 【统计可靠性审计】",
        "=" * 80,
        f"  ✅ 可靠 (A, ≥30笔):     {rs['reliable_count']} 个子策略, {rs['reliable_trades']} 笔交易, 净利 {rs['reliable_net_pnl']:+,.2f} RMB",
        f"  ⚠️  边际 (B, 20-29笔):   {rs['marginal_count']} 个子策略",
        f"  ❌ 不可靠 (F, <20笔):    {rs['unreliable_count']} 个子策略 (已从组合统计中剔除)",
        f"  📈 原始全量:             {rs['raw_total_trades']} 笔交易, 净利 {rs['raw_total_net_pnl']:+,.2f} RMB",
    ]
    if rs["short_data_symbols"]:
        lines.append(f"  ⏱️  数据不足(<{MIN_DATA_MONTHS}月): {', '.join(rs['short_data_symbols'])}")
    lines.append(f"  🏁 总结论: {rs['verdict']}")
    lines.append("=" * 80)
    return "\n".join(lines)
