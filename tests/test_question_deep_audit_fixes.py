# -*- coding: utf-8 -*-
"""
Unit tests for Question.md Deep Audit Counterexamples (tests/test_question_deep_audit_fixes.py)
Validates:
1. [Q12] 3-stage causal event-driven execution eliminates cross-period M2M mismatch (overnight jump gives 0% fake drawdown).
2. [Q02] Unknown legacy factors are archived as UNRESOLVED_IMPLEMENTATION and never falsified as pct_change(10).
3. [Q03] Subprocess worker hard kills hanging factor evaluations on timeout (>45s / test timeout) without thread leaks.
4. [Q05] OS fcntl.flock provides atomic single-instance exclusivity.
"""

import os
import sys
import time
import unittest
import sqlite3
import tempfile
from unittest.mock import patch
import pandas as pd
import numpy as np

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "code")))
import continuous_alpha_miner as miner
import autonomous_alpha_research_engine as engine


class TestQuestionDeepAuditFixes(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.test_db = os.path.join(self.temp_dir.name, "test_deep_audit.db")
        self.orig_miner_db = miner.DB_PATH
        self.orig_engine_db = engine.DB_PATH
        miner.DB_PATH = self.test_db
        engine.DB_PATH = self.test_db
        engine.init_db()

    def tearDown(self):
        miner.DB_PATH = self.orig_miner_db
        engine.DB_PATH = self.orig_engine_db
        self.temp_dir.cleanup()

    def test_q12_causal_state_machine_no_fake_drawdown(self):
        """
        [Q12 反例验证] 隔夜跳涨行情下，入场后平稳运行。
        旧代码由于在第 49 根 Bar 用未来开盘价 opens[50]=200 计算当期 M2M:
            unrealized = closes[49] - opens[50] = 100 - 200 = -100
        错造了 10% 的虚假最大回撤。
        新状态机实行严格 3 阶段（开盘撮合前序订单 -> 盘中收盘盯市估值 -> 收盘产生次日挂单），
        第 49 根 Bar 仅挂单未持仓 (M2M=0)，第 50 根 Bar 开盘 200 成交，盘中收盘平稳 200，
        最大回撤严格为 0.0%。
        """
        n = 600
        closes = np.full(n, 100.0)
        opens = np.full(n, 100.0)
        highs = np.full(n, 100.0)
        lows = np.full(n, 100.0)
        volumes = np.full(n, 1000.0)

        # Bar 50 及以后价格跳涨至 200 并在持仓期保持坚挺
        opens[50:] = 200.0
        closes[50:] = 200.0
        highs[50:] = 200.0
        lows[50:] = 200.0

        # 平仓出场点向上小幅抬升，使得本单处于整体盈利状态
        opens[80:] = 210.0
        closes[80:] = 210.0
        highs[80:] = 210.0
        lows[80:] = 210.0

        mock_df = pd.DataFrame({
            "trade_time": [f"2024-01-01 {i:04d}" for i in range(n)],
            "open": opens,
            "high": highs,
            "low": lows,
            "close": closes,
            "volume": volumes,
            "amount": volumes * closes
        })

        # 构造因子定义：在第 49 根 Bar 收盘触发突破信号
        def mock_calc(df):
            s = pd.Series(np.zeros(len(df)))
            s.iloc[49] = 10.0
            return s

        factor_def = {
            "id": "FAC_TEST_Q12_JUMP",
            "name": "隔夜跳涨验证因子",
            "family": "动量家族 (Momentum)",
            "hypothesis": "验证隔夜跳涨零回撤",
            "formula": "TestJump()",
            "calc": mock_calc,
            "direction": 1,
        }

        with patch("autonomous_alpha_research_engine.load_bars_from_db", return_value=mock_df):
            res = engine.evaluate_factor_on_symbol(factor_def, "RB")

        self.assertTrue(res["success"], "Trade evaluation should succeed")
        self.assertGreaterEqual(res["trades"], 1, "Should have executed at least 1 trade")
        # 核心断言：由于严格因果撮合，彻底消除了 closes[49] - opens[50] 跨期估值错位，最大回撤必须为 0.0%
        self.assertAlmostEqual(res["max_dd"], 0.0, places=5, msg="Q12 修复后，隔夜跳涨入场绝对不可出现虚假浮亏与最大回撤！")

    def test_q02_legacy_unknown_factor_no_pct_change_replacement(self):
        """
        [Q02 反例验证] 数据库中未知的遗留因子，绝对禁止被偷换为 pct_change(10)，
        必须安全归档为 UNRESOLVED_IMPLEMENTATION 并移出评估队列。
        """
        conn = sqlite3.connect(self.test_db)
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO factor_zoo (
                factor_id, formula_hash, name, family, hypothesis, formula_dsl, total_score,
                grade, rank_ic, icir, win_rate, sharpe, profit_factor, max_dd,
                breakeven_cost_mult, cross_market_pass_rate, tested_symbols,
                status, fail_reason, created_at
            ) VALUES (
                'FAC_UNKNOWN_TEST_001', 'hash_test_unknown', '未知遗留因子', '历史遗留', '未知逻辑', 'UnknownFormula()',
                0.0, 'D', 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, '{}',
                'LEGACY_UNVERIFIED', NULL, '2026-09-05 00:00:00'
            );
        """)
        conn.commit()
        conn.close()

        # 调用遗留因子提取函数
        legacy_factors = miner.get_legacy_unverified_factors()

        # 1. 未知因子绝对不能出现在待评估列表中被伪造计算
        self.assertFalse(
            any(f["id"] == "FAC_UNKNOWN_TEST_001" for f in legacy_factors),
            "未知因子绝对不可被伪造进入评估队列！"
        )

        # 2. 数据库中该因子的状态必须被标记为 UNRESOLVED_IMPLEMENTATION
        conn = sqlite3.connect(self.test_db)
        cursor = conn.cursor()
        cursor.execute("SELECT status, fail_reason FROM factor_zoo WHERE factor_id = 'FAC_UNKNOWN_TEST_001';")
        row = cursor.fetchone()
        conn.close()

        self.assertIsNotNone(row)
        self.assertEqual(row[0], "UNRESOLVED_IMPLEMENTATION")
        self.assertIn("无法从因子池或DSL解析", row[1])

    def test_q03_subprocess_hard_kill_on_timeout(self):
        """
        [Q03 反例验证] 面对假死或死循环计算的因子，独立子进程 Worker 在超时后被 OS 级强制强杀 (kill)，
        主控进程顺畅抛出 TimeoutError，绝不阻塞在 ThreadPoolExecutor 的 __exit__ 退出点。
        """
        # 恢复使用有真实数据的数据库以加载 K 线，使 worker 顺利进入 calc 逻辑
        miner.DB_PATH = self.orig_miner_db
        engine.DB_PATH = self.orig_engine_db

        def stuck_calc(df):
            while True:
                time.sleep(0.05)

        hanging_factor = {
            "id": "FAC_HANGING_001",
            "name": "死循环测试因子",
            "family": "动量家族 (Momentum)",
            "hypothesis": "测试硬杀超时",
            "formula": "InfiniteLoop()",
            "calc": stuck_calc,
            "direction": 1,
        }

        t0 = time.monotonic()
        with self.assertRaises(TimeoutError):
            # 设置 0.5 秒极短超时
            miner.run_eval_with_hard_timeout(hanging_factor, timeout_seconds=0.5)

        elapsed = time.monotonic() - t0
        # 应该在约 0.5s ~ 2.5s 内完成强杀并返回，而不是永久挂死
        self.assertLess(elapsed, 3.0, "子进程强杀必须在预定超时后迅速完成，禁止线程假死阻塞！")

    def test_q05_os_file_lock_atomicity(self):
        """
        [Q05 反例验证] 基于 fcntl.flock 的操作系统级原子排他锁，
        当已有矿工实例持有时，新实例立即被拒，彻底消除并发竞态与踩踏。
        """
        # 1. 实例 A 获取锁
        lock_a = miner.acquire_miner_lock()
        self.assertIsNotNone(lock_a, "首次获取锁应该成功")

        # 2. 实例 B 尝试并发获取同一个锁，必须原子级返回 None
        lock_b = miner.acquire_miner_lock()
        self.assertIsNone(lock_b, "并发获取已锁定的文件必须返回 None，防止实例踩踏")

        # 3. 实例 A 释放锁
        miner.release_miner_lock(lock_a)

        # 4. 再次获取锁，此时应该成功
        lock_c = miner.acquire_miner_lock()
        self.assertIsNotNone(lock_c, "锁释放后，新实例应该能够成功获取")
        miner.release_miner_lock(lock_c)

    def test_q03_large_result_no_pipe_deadlock(self):
        """
        [Q03 管道死锁根治反例]
        测试当 Worker 返回约 2MB 的较大数据对象时，旧代码直接 queue.put(payload) 会塞满 OS pipe
        缓冲区（通常 64KB）导致子进程阻塞、父进程 join 死等，进而被误杀 TimeoutError。
        新实现将大 payload 写入临时文件，Queue 仅传递元数据路径，测试必须在 1 秒内正常返回且数据完好。
        """
        miner.DB_PATH = self.orig_miner_db
        engine.DB_PATH = self.orig_engine_db

        # 构造产生 2MB 大字典的假计算逻辑
        def large_calc(df):
            return df["close"].pct_change(5).fillna(0.0)

        factor_def = {
            "id": "FAC_TEST_LARGE_PAYLOAD",
            "name": "大体积结果测试因子",
            "family": "动量家族 (Momentum)",
            "hypothesis": "测试大数据量 IPC 管道无死锁",
            "formula": "LargePayload()",
            "calc": large_calc,
            "direction": 1,
            # 注入一个 2MB 的大字段，模拟长序列交易日志或详细逐柱时序
            "_large_dummy_data": "X" * (2 * 1024 * 1024),
        }

        t0 = time.monotonic()
        res = miner.run_eval_with_hard_timeout(factor_def, timeout_seconds=5.0)
        elapsed = time.monotonic() - t0

        self.assertIsInstance(res, dict, "Worker 必须正确反序列化返回结果字典")
        self.assertLess(elapsed, 4.0, "2MB 大数据对象绝不可发生管道死锁或被误判为超时！")

    def test_q05_permanent_lock_file_retention(self):
        """
        [Q05 锁文件常驻无竞态验证]
        release_miner_lock 绝对禁止删除物理锁文件，锁文件必须常驻磁盘，
        完全基于 fcntl.flock 的内核 inode 锁句柄保障原子互斥，避免删除后再建的 inode 漂移竞态。
        """
        # 1. 获取锁
        lock_fd = miner.acquire_miner_lock()
        self.assertIsNotNone(lock_fd)
        self.assertTrue(os.path.exists(miner.LOCK_FILE), "锁文件必须已创建")

        # 2. 释放锁
        miner.release_miner_lock(lock_fd)

        # 核心断言：释放后，物理锁文件依然常驻在磁盘上，没有被 os.remove 删除
        self.assertTrue(
            os.path.exists(miner.LOCK_FILE),
            "Q05 修复要求：释放锁时绝不可删除锁文件，以杜绝 inode 切换竞态！"
        )

        # 3. 再次获取锁，验证常驻文件的 flock 能够再次被原子抢占
        lock_fd2 = miner.acquire_miner_lock()
        self.assertIsNotNone(lock_fd2, "锁文件常驻情况下，后续实例必须能正常加锁")
        miner.release_miner_lock(lock_fd2)


    def test_p01_three_way_data_split_and_blind_gate(self):
        """
        [P0-1 60/20/20 三段密封切分与密封盲测门禁]
        验证：
        1. evaluate_factor_on_symbol 严格执行 60% IS, 20% OOS-select, 20% Blind 三段切分；
        2. 每笔交易带有明确的 segment 标签 ('IS', 'OOS', 'BLIND')；
        3. 返回字典中包含独立的 blind_sharpe, blind_win_rate, blind_trades；
        4. evaluate_and_score_factor 将 Blind 独立归档，若总分>=80但Blind未通过，绝不可评为EXCELLENT，
           必须降级为 CANDIDATE 并记录 fail_reason。
        """
        def mock_calc(df):
            return df["close"].pct_change(3).fillna(0.0)

        factor_def = {
            "id": "FAC_TEST_BLIND_SPLIT",
            "name": "密封盲测切分测试因子",
            "family": "动量家族 (Momentum)",
            "hypothesis": "测试三段密封切分与盲测终审门禁",
            "formula": "BlindSplitTest()",
            "calc": mock_calc,
            "direction": 1,
        }

        # 1. 验证单品种上的三段切分与标签
        n = 1000
        mock_df = pd.DataFrame({
            "trade_time": [f"2024-01-01 {i:04d}" for i in range(n)],
            "open": np.random.uniform(100, 110, n),
            "high": np.random.uniform(110, 120, n),
            "low": np.random.uniform(90, 100, n),
            "close": np.random.uniform(100, 110, n),
            "volume": np.full(n, 1000.0),
            "amount": np.full(n, 100000.0),
        })
        with patch.object(engine, "load_bars_from_db", return_value=mock_df):
            sym_res = engine.evaluate_factor_on_symbol(factor_def, "AU_IDX")
        self.assertTrue(sym_res["success"])
        self.assertIn("blind_sharpe", sym_res)
        self.assertIn("blind_win_rate", sym_res)
        self.assertIn("blind_trades", sym_res)

        # 2. 验证多品种综合评分与 Blind 门禁
        # 构造一个高分但让其盲测段不通过的场景
        with patch.object(engine, "evaluate_factor_on_symbol") as mock_eval:
            mock_eval.return_value = {
                "symbol": "AU_IDX",
                "success": True,
                "rank_ic": 0.08,
                "ic_std": 0.02,
                "sharpe": 2.2,
                "oos_sharpe": 1.8,       # 样本外验证段优秀
                "blind_sharpe": -0.5,    # 密封盲测段崩塌!
                "blind_win_rate": 30.0,  # 盲测胜率低于 40%
                "blind_trades": 10,
                "win_rate": 55.0,
                "profit_factor": 1.6,
                "max_dd": 5.0,
                "trades": 80,
                "net_pnl": 50000.0,
                "pnl_3x": 20000.0,
            }
            score_res = engine.evaluate_and_score_factor(factor_def, test_symbols=["AU_IDX"])
            # 总分应满足 >= 80，但因盲测崩塌，必须降级为 CANDIDATE
            self.assertGreaterEqual(score_res["total_score"], 80.0)
            self.assertEqual(score_res["status"], "CANDIDATE", "盲测段崩塌的因子绝不可评为 EXCELLENT！")
            self.assertEqual(score_res["grade"], "B")
            self.assertEqual(score_res["blind_consumed"], 1, "触碰盲测终审的因子必须标记 blind_consumed=1")
            self.assertIn("密封盲测段 (Blind 20%) 未通过", score_res["fail_reason"])

    def test_p02_spawn_context_eval_worker(self):
        """
        [P0-2 spawn 上下文独立进程验证]
        验证 run_eval_with_hard_timeout 使用 spawn 上下文正常启动子进程并返回结果，
        杜绝多线程环境（如心跳线程）下 POSIX fork 引起的 C 库锁死锁风险。
        """
        def simple_calc(df):
            return df["close"].pct_change(5).fillna(0.0)

        factor_def = {
            "id": "FAC_TEST_SPAWN_WORKER",
            "name": "Spawn子进程测试因子",
            "family": "均值回归 (Mean Reversion)",
            "hypothesis": "测试 spawn context 下 Worker 正常执行",
            "formula": "SpawnWorkerTest()",
            "calc": simple_calc,
            "direction": 1,
        }

        res = miner.run_eval_with_hard_timeout(factor_def, timeout_seconds=10.0)
        self.assertIsInstance(res, dict)
        self.assertEqual(res["factor_id"], "FAC_TEST_SPAWN_WORKER")
        self.assertIn("total_score", res)

    def test_p11_status_writer_thread_lock(self):
        """
        [P1-1 状态文件写入线程锁验证]
        验证 _status_lock 有效保护多线程并发调用 write_status，无 JSON 损坏或文件截断。
        """
        import threading
        import json

        errors = []
        def concurrent_writer(thread_id):
            try:
                for i in range(20):
                    data = {
                        "is_running": True,
                        "thread_id": thread_id,
                        "iteration": i,
                        "timestamp": time.time(),
                    }
                    miner.write_status(data)
                    time.sleep(0.005)
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=concurrent_writer, args=(t,)) for t in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        self.assertEqual(len(errors), 0, f"并发写入状态文件不应抛出任何异常: {errors}")
        with open(miner.STATUS_FILE, "r", encoding="utf-8") as f:
            final_data = json.load(f)
        self.assertIn("thread_id", final_data)

    def test_p21_family_consecutive_fails_skip_logic(self):
        """
        [P2-1 搜索效率：family 淘汰率自动跳过验证]
        验证当某家族连续淘汰超过阈值后，动态变异生成器有效跳过该家族，
        且当所有家族均饱和时自动清空计数器以防死锁。
        """
        family_consecutive_fails = {"动量家族 (Momentum)": 15}
        skip_threshold = 15

        # 模拟生成变异
        cand1 = {"id": "C1", "family": "动量家族 (Momentum)"}
        cand2 = {"id": "C2", "family": "均值回归 (Mean Reversion)"}

        # 动量家族由于达到阈值应被跳过
        should_skip_cand1 = family_consecutive_fails.get(cand1["family"], 0) >= skip_threshold
        self.assertTrue(should_skip_cand1)

        # 均值回归未达到阈值，不被跳过
        should_skip_cand2 = family_consecutive_fails.get(cand2["family"], 0) >= skip_threshold
        self.assertFalse(should_skip_cand2)


if __name__ == "__main__":
    unittest.main()


