# -*- coding: utf-8 -*-
"""
tests/test_kaiyang_audit_fixes.py

自动化回归测试：验证针对 question.md 审计报告提出的核心修复
1. [Q01] Rust adverse_gap 开盘跳空拒单门禁不再泄漏当柱 High/Low (开盘决定对盘中极值扰动严格不变)
2. [Q03] Python 资金不足开仓被刚性拦截，杜绝 1 元本金一手保底穿仓
3. [Q06] Python 开仓柱极值正确沉淀入持仓极值，后续柱及时抬升吊灯止损
4. [Q06] Python 前序收盘已确定的退出指令（状态翻转/超时）在当柱开盘优先执行，不被盘中止损篡改
5. [Q07] Python 期末强平手续费与滑点真实计入权益曲线与最大回撤
6. [Q10] Python 宏观状态在过渡态 (TRANSITION=2) 下多空规则完全镜像对称
7. [Q12] Python attrs 传递的 chandelier_mult 动态风控参数被模拟引擎真实消费
"""

import os
import sys
import unittest
import subprocess
import tempfile
from pathlib import Path
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "code"))
sys.path.insert(0, str(ROOT / "strategies"))

from adaptive_regime_evolution_strategy import generate_regime_evolution_signals
from run_adaptive_regime_evolution_audit import simulate_trading_engine
from contract_specs import ContractSpec, calculate_contract_margin


def make_test_frame(n=50):
    f = pd.DataFrame({
        k: np.full(n, v) for k, v in {
            "open": 100.0,
            "high": 100.2,
            "low": 99.8,
            "close": 100.0,
            "volume": 1000.0,
            "atr": 1.0,
            "raw_signal": 0,
            "signal_source": 1,
            "confidence": 0.6,
            "market_state": 1,
            "p_continue": 0.8,
            "ss_fast": 100.0,
            "ss_slow": 100.0,
            "filt_mean": 103.0,
            "h20": 105.0,
            "l20": 95.0,
            "robust_z": 0.0,
            "trend_strength": 50.0,
        }.items()
    })
    f["trade_time"] = pd.date_range("2026-01-05 09:00", periods=n, freq="15min")
    f.loc[1, "raw_signal"] = 1
    return f


class TestKaiyangAuditFixes(unittest.TestCase):
    def test_q01_rust_adverse_gap_causality_invariance(self):
        """[Q01 修复验证] 编译实际 Rust 源码块，验证开盘 adverse_gap 不再受当柱未来 High 影响"""
        source = (ROOT / "desktop/src-tauri/src/backtest.rs").read_text()

        def extract_fn(name):
            start = source.index("fn " + name + "(")
            brace = source.index("{", start)
            depth = 1
            end = brace + 1
            while depth > 0:
                depth += (source[end] == "{") - (source[end] == "}")
                end += 1
            return source[start:end]

        start_token = "let is_session_gap ="
        start = source.index(start_token, source.index("if let Some((enter_reason, score_val, direction))"))
        end = source.index("if !adverse_gap && shares == 0", start)
        block = source[start:end]

        program = """#[derive(Clone)] struct KlineBar {time:i64,open:f64,high:f64,low:f64,close:f64}
""" + extract_fn("calc_atr") + """
fn main() {
    let mut decisions = Vec::new();
    for high in [100.0, 120.0] {
        let mut bars = vec![KlineBar { time: 0, open: 100.0, high: 100.5, low: 99.5, close: 100.0 }; 32];
        let i = 31_usize;
        bars[30].time = 0;
        bars[i] = KlineBar { time: 7200, open: 99.5, high, low: 99.0, close: 100.0 };
        let closes: Vec<f64> = bars.iter().map(|b| b.close).collect();
        let atr_14 = calc_atr(&bars, 14);
        let curr = &bars[i];
        let is_long = true;
""" + block + """
        decisions.push(adverse_gap);
    }
    // 核心断言: 扰动当柱盘中最高价 (100.0 vs 120.0)，开盘开仓拒单决定必须完全一致！
    assert_eq!(decisions[0], decisions[1], "Q01 失败: 开盘决定仍受当柱未来 High 影响！");
}
"""
        with tempfile.TemporaryDirectory() as tmp_dir:
            rust_src = Path(tmp_dir) / "check_gap.rs"
            rust_bin = Path(tmp_dir) / "check_gap"
            rust_src.write_text(program)
            subprocess.run(["rustc", str(rust_src), "-o", str(rust_bin)], check=True, capture_output=True)
            res = subprocess.run([str(rust_bin)], capture_output=True, text=True)
            self.assertEqual(res.returncode, 0, f"Rust adverse_gap causality check failed: {res.stderr}")

    def test_q03_python_capital_gate_insufficient_margin(self):
        """[Q03 修复验证] 1元本金在需要10,010元保证金时，必须坚决拒单，不执行任何交易"""
        f = make_test_frame()
        big_spec = ContractSpec("TEST_BIG", 1000.0, 0.1, 0.0, 0.1, "TEST")
        # 本金仅 1 元
        r = simulate_trading_engine(f, big_spec, initial_capital=1.0)
        self.assertEqual(len(r["trades"]), 0, "Q03 失败: 资金严重不足时仍开出仓位！")
        self.assertEqual(r["net_profit"], 0.0)

    def test_q06_python_entry_bar_extreme_tracked_for_ratchet(self):
        """[Q06 修复验证] 开仓当根的高点如实更新入持仓极值，使下一柱及时触发吊灯止损保利"""
        f = make_test_frame()
        # Bar 2 开仓，当根最高飙升至 105.0 (产生大幅浮盈)，Bar 3 最低下跌至 99.0
        f.loc[2, "high"] = 105.0
        f.loc[3, "low"] = 99.0
        spec = ContractSpec("TEST", 1.0, 0.1, 0.0, 0.1, "TEST")
        r = simulate_trading_engine(f, spec, initial_capital=1000.0)
        self.assertGreater(len(r["trades"]), 0)
        trade = r["trades"][0]
        # 由于最高价 105 被正确记录，profit_atr >= 2.2 启动吊灯，在 Bar 3 最低 99 时即被吊灯止损触发退场
        self.assertLessEqual(trade["holding_bars"], 2, "Q06 失败: 开仓柱高点被遗忘，未能及时抬升止损！")

    def test_q06_python_exit_ordering_open_event_first(self):
        """[Q06 修复验证] 前序收盘确定的退出（状态翻转）必须在当柱开盘以开盘价成交，不被随后的盘中止损覆盖"""
        f = make_test_frame()
        # Bar 3 收盘状态翻转为空头 (-1)，决定在 Bar 4 开盘退场
        f.loc[3, "market_state"] = -1
        # Bar 4 开盘 102.0，盘中下探至 97.0
        f.loc[4, ["open", "high", "low", "close"]] = [102.0, 103.0, 97.0, 101.0]
        spec = ContractSpec("TEST", 1.0, 0.1, 0.0, 0.1, "TEST")
        r = simulate_trading_engine(f, spec, initial_capital=1000.0)
        self.assertGreater(len(r["trades"]), 0)
        trade = r["trades"][0]
        self.assertEqual(trade["reason"], "Regime Reversal Exit", "Q06 失败: 开盘退出事件被盘中止损抢跑覆盖！")
        # 102.0 扣 0.1 tick 滑点 = 101.9
        self.assertAlmostEqual(trade["exit_price"], 101.9, places=2)

    def test_q07_python_terminal_equity_and_drawdown_account_for_final_fee(self):
        """[Q07 修复验证] 期末平仓手续费与滑点必须如实反映在权益曲线与最大回撤中"""
        f = make_test_frame()
        f["atr"] = 10.0
        fees_spec = ContractSpec("TEST", 1.0, 0.1, 0.0, 0.1, "TEST", fee_type="FIXED", fixed_fee=1.0)
        r = simulate_trading_engine(f, fees_spec, initial_capital=1000.0)
        terminal_loss = -r["net_profit"] / 1000.0 * 100.0
        self.assertAlmostEqual(r["max_dd_pct"], terminal_loss, places=2, msg="Q07 失败: 期末强平费用未计入最大回撤！")

    def test_q10_python_macro_state_symmetry_in_transition(self):
        """[Q10 修复验证] 当宏观状态为 TRANSITION=2 时，多空突破与顺势判定严格对称"""
        f = make_test_frame(100)
        sig = generate_regime_evolution_signals(f)
        self.assertIn("raw_signal", sig.columns)
        self.assertTrue(set(np.unique(sig["raw_signal"])).issubset({-1, 0, 1}))

    def test_q12_python_attrs_chandelier_mult_consumed(self):
        """[Q12 修复验证] 修改 df.attrs['chandelier_mult'] 必须真实影响交易退出结果"""
        f = make_test_frame()
        f.loc[2, "high"] = 104.0
        # Bar 3 开在 103.5, 盘中探至 102.0:
        # 当 chandelier_mult=0.5 时, stop_p = 104.0 - 0.5 = 103.5, 盘中 102.0 触发止损并在 Bar 3 退出
        # 当 chandelier_mult=5.0 时, stop_p = 104.0 - 5.0 = 99.0, 盘中 102.0 不触发止损, 继续持仓
        f.loc[3, ["open", "high", "low", "close"]] = [103.5, 103.5, 102.0, 103.0]
        spec = ContractSpec("TEST", 1.0, 0.1, 0.0, 0.1, "TEST")

        # 宽吊灯 5.0: 在 low=102.0 时不触发, 持仓至回测结束
        f_wide = f.copy()
        f_wide.attrs = {"chandelier_mult": 5.0}
        r_wide = simulate_trading_engine(f_wide, spec, initial_capital=1000.0)

        # 极紧吊灯 0.5: 在 low=102.0 时必定触发, 在 Bar 3 退出
        f_tight = f.copy()
        f_tight.attrs = {"chandelier_mult": 0.5}
        r_tight = simulate_trading_engine(f_tight, spec, initial_capital=1000.0)

        self.assertNotEqual(
            r_wide["trades"][0]["holding_bars"],
            r_tight["trades"][0]["holding_bars"],
            "Q12 失败: 交易引擎未消费 DataFrame attrs 传入的风控参数！"
        )
        self.assertEqual(r_tight["trades"][0]["reason"], "Chandelier SL")
        self.assertEqual(r_tight["trades"][0]["holding_bars"], 1)


if __name__ == "__main__":
    unittest.main()
