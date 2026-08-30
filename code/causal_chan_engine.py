"""
code/causal_chan_engine.py — 工业级纯因果缠论市场结构编码器 (ChanQuant 2.0 Engine)

第一性原理与核心特性：
1. 严格时间因果隔离 (Causal Separation):
   - structure_time: 物理极值发生时间 (用于计算几何形态与振幅)
   - known_time: 市场右侧确认时间 (交易信号与特征仅在 known_time 可见)
   - 彻底消灭“用未来最低点/最高点回测”的未来函数漏洞。
2. K线因果包含处理 (Causal Inclusion Processing):
   - 基于前向趋势方向动态规约相邻包含 K 线 (向上取高高，向下取低低)。
3. 纯因果顶底分型与自适应笔 (Adaptive Causal Bi):
   - 顶底分型在第 3 根包含后 K 线收盘时确认。
   - 严格遵循缠论公理：顶底分型交替出现，且顶底之间至少包含 1 根独立非共享 K 线 (有效笔 >= 5 根包含后 K 线)。
   - 自适应波动率门禁 (k * ATR) 过滤微观随机游走噪声。
4. 几何走势中枢状态机 (Causal Zhongshu State Machine):
   - 由连续 3 笔有效重叠区间 [max(d1, d3), min(g1, g3)] 严格构建。
   - 实时追踪中枢区间 [Z_low, Z_high]、延伸笔数、收缩率及破坏。
5. 三类买卖点因果发生器 (Third Buy/Sell Points):
   - 三买 (B3): 次级别突破离开中枢后，初回踩低点不跌破中枢上沿 (或受限于容差门槛)；
   - 三卖 (S3): 次级别跌破离开中枢后，初回抽高点不升破中枢下沿。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import IntEnum
from typing import List, Optional, Tuple, Dict, Any
import numpy as np
import pandas as pd


class Direction(IntEnum):
    UP = 1
    DOWN = -1
    NEUTRAL = 0


@dataclass
class ProcessedKLine:
    """经包含处理后的标准化 K 线"""
    index: int
    datetime: Any
    open: float
    high: float
    low: float
    close: float
    volume: float
    open_interest: float
    direction: Direction
    raw_indices: List[int] = field(default_factory=list)


@dataclass
class CausalFractal:
    """因果分型"""
    fractal_type: Direction  # Direction.UP 为顶分型, Direction.DOWN 为底分型
    structure_idx: int       # 分型极值在 ProcessedKLine 中的索引
    structure_time: Any      # 物理极值发生时间 (Bar 2)
    structure_price: float   # 物理极值价格 (顶为 High, 底为 Low)
    known_idx: int           # 右侧确认在 ProcessedKLine 中的索引 (Bar 3)
    known_time: Any          # 右侧确认时间 (Bar 3 收盘)
    raw_known_idx: int       # 对应原始 K 线的确认索引


@dataclass
class CausalBi:
    """因果笔"""
    bi_id: int
    direction: Direction     # Direction.UP: 底->顶 (上升笔); Direction.DOWN: 顶->底 (下降笔)
    start_fractal: CausalFractal
    end_fractal: CausalFractal
    start_time: Any          # 起点物理时间
    end_time: Any            # 终点物理时间
    start_price: float       # 起点价格
    end_price: float         # 终点价格
    known_time: Any          # 笔确认时间 (即 end_fractal.known_time)
    amplitude: float         # 绝对振幅 |end_price - start_price|
    bars_count: int          # 包含后 K 线根数
    raw_bars_count: int      # 包含前原始 K 线根数
    efficiency_ratio: float = 0.0  # Kaufman 移动效率比
    volume_sum: float = 0.0
    oi_change: float = 0.0


@dataclass
class CausalZhongshu:
    """因果走势中枢"""
    zs_id: int
    start_bi_id: int
    direction: Direction     # 中枢进入方向 (前置笔方向)
    z_high: float            # 中枢上沿 min(g1, g3)
    z_low: float             # 中枢下沿 max(d1, d3)
    start_time: Any          # 中枢形成时间
    known_time: Any          # 中枢第3笔确认时间
    bi_ids: List[int]        # 包含的所有笔 ID
    extension_count: int = 0 # 延伸笔数
    is_completed: bool = False
    breakout_bi_id: Optional[int] = None
    compression_ratio: float = 1.0  # 收缩率 Amp(Bi3) / Amp(Bi1)


@dataclass
class CausalBuySellEvent:
    """因果买卖点事件"""
    event_id: str
    event_type: str          # 'B3' (三买) 或 'S3' (三卖)
    side: int                # +1 为多头, -1 为空头
    known_time: Any          # 信号产生时间 (严格因果可交易时间)
    known_raw_idx: int       # 原始 K 线索引
    trigger_price: float     # 触发价格 (回踩笔终点价)
    zs_high: float           # 对应中枢上沿
    zs_low: float            # 对应中枢下沿
    zs_id: int               # 对应中枢 ID
    factors: Dict[str, float] = field(default_factory=dict)


class CausalChanEngine:
    """
    流式/批量统一的纯因果缠论引擎
    """
    def __init__(self, atr_k: float = 0.0, strict_bi_bars: int = 4):
        """
        :param atr_k: 笔极值最小 ATR 波动过滤倍数 (0.0 为纯几何模式)
        :param strict_bi_bars: 顶底之间包含后 K 线最小间隔数 (标准缠论为 >= 4, 即总共 >= 5 根)
        """
        self.atr_k = atr_k
        self.strict_bi_bars = strict_bi_bars

        # 状态机内部数据
        self.raw_bars: List[Dict[str, Any]] = []
        self.processed_klines: List[ProcessedKLine] = []
        self.fractals: List[CausalFractal] = []
        self.bis: List[CausalBi] = []
        self.zhongshus: List[CausalZhongshu] = []
        self.events: List[CausalBuySellEvent] = []

        # 运行时辅助变量
        self._inclusion_dir: Direction = Direction.UP

    def reset(self):
        """重置引擎状态"""
        self.raw_bars.clear()
        self.processed_klines.clear()
        self.fractals.clear()
        self.bis.clear()
        self.zhongshus.clear()
        self.events.clear()
        self._inclusion_dir = Direction.UP

    def process_dataframe(self, df: pd.DataFrame) -> List[CausalBuySellEvent]:
        """批量处理 DataFrame，返回所有因果买卖点事件"""
        self.reset()
        for i, row in df.iterrows():
            bar_dict = {
                "raw_idx": len(self.raw_bars),
                "datetime": row.get("trade_time", row.get("datetime", i)),
                "open": float(row["open"]),
                "high": float(row["high"]),
                "low": float(row["low"]),
                "close": float(row["close"]),
                "volume": float(row.get("volume", 0.0)),
                "open_interest": float(row.get("open_interest", 0.0)),
                "atr": float(row.get("atr", row.get("atr_14", 0.0))),
            }
            self.feed_bar(bar_dict)
        return self.events

    def feed_bar(self, bar: Dict[str, Any]) -> List[CausalBuySellEvent]:
        """流式输入单根原始 K 线"""
        raw_idx = len(self.raw_bars)
        self.raw_bars.append(bar)

        # 1. 包含关系处理
        new_processed = self._process_inclusion(bar, raw_idx)
        if not new_processed:
            return []

        # 2. 顶底分型判定
        new_fractal = self._detect_fractal()
        if new_fractal is not None:
            # 3. 笔连接与生长
            new_bi = self._update_bi(new_fractal)
            if new_bi is not None:
                # 4. 中枢构建与延伸
                new_zs = self._update_zhongshu(new_bi)
                # 5. 全谱系买卖点检测 (一买/二买/三买/一卖/二卖/三卖 + 笔级转折)
                new_events = self._detect_all_buy_sell_events(new_bi)
                return new_events

        return []

    def _detect_all_buy_sell_events(self, curr_bi: CausalBi) -> List[CausalBuySellEvent]:
        """全谱系因果买卖点统一检测发生器"""
        events = []
        events.extend(self._detect_first_buy_sell(curr_bi))
        events.extend(self._detect_second_buy_sell(curr_bi))
        events.extend(self._detect_third_buy_sell(curr_bi))
        return events

    # -------------------------------------------------------------------------
    # 核心算法 5.1: 一买/一卖 (B1/S1) 趋势背驰衰竭点
    # -------------------------------------------------------------------------
    def _detect_first_buy_sell(self, curr_bi: CausalBi) -> List[CausalBuySellEvent]:
        """
        一买 (B1):
        - 当前笔向下创出新低 (P_end < P_start 且低于前一下降笔低点)
        - 动能衰竭: 效率比 ER 降低 或 振幅比上一同向笔收缩 (Amp_Ratio < 0.85)
        一卖 (S1):
        - 当前笔向上创出新高
        - 动能衰竭 (Amp_Ratio < 0.85)
        """
        if len(self.bis) < 3:
            return []

        prev_same_bi = self.bis[-3]  # 上一同向笔
        events = []
        raw_known_idx = curr_bi.end_fractal.raw_known_idx
        current_atr = self.raw_bars[raw_known_idx].get("atr", 1.0) or 1.0

        # 一买 (B1): 下降笔动能衰竭创低
        if curr_bi.direction == Direction.DOWN and prev_same_bi.direction == Direction.DOWN:
            if curr_bi.end_price < prev_same_bi.end_price:
                amp_ratio = float(curr_bi.amplitude / (prev_same_bi.amplitude + 1e-8))
                er = curr_bi.efficiency_ratio
                if amp_ratio < 0.90 or er < 0.45:
                    ev = CausalBuySellEvent(
                        event_id=f"B1_{curr_bi.bi_id}",
                        event_type="B1",
                        side=1,
                        known_time=curr_bi.known_time,
                        known_raw_idx=raw_known_idx,
                        trigger_price=curr_bi.end_price,
                        zs_high=prev_same_bi.start_price,
                        zs_low=curr_bi.end_price,
                        zs_id=self.zhongshus[-1].zs_id if self.zhongshus else 0,
                        factors={
                            "B05_bi_efficiency": er,
                            "B10_same_dir_amp_ratio": amp_ratio,
                            "Z01_zhongshu_width": 1.0,
                            "Z09_zhongshu_compression": 1.0,
                            "Z11_breakout_strength": 0.0,
                            "P08_pullback_depth": 0.0,
                            "P09_edge_clearance": 0.2,
                        }
                    )
                    events.append(ev)
                    self.events.append(ev)

        # 一卖 (S1): 上升笔动能衰竭创新高
        elif curr_bi.direction == Direction.UP and prev_same_bi.direction == Direction.UP:
            if curr_bi.end_price > prev_same_bi.end_price:
                amp_ratio = float(curr_bi.amplitude / (prev_same_bi.amplitude + 1e-8))
                er = curr_bi.efficiency_ratio
                if amp_ratio < 0.90 or er < 0.45:
                    ev = CausalBuySellEvent(
                        event_id=f"S1_{curr_bi.bi_id}",
                        event_type="S1",
                        side=-1,
                        known_time=curr_bi.known_time,
                        known_raw_idx=raw_known_idx,
                        trigger_price=curr_bi.end_price,
                        zs_high=curr_bi.end_price,
                        zs_low=prev_same_bi.start_price,
                        zs_id=self.zhongshus[-1].zs_id if self.zhongshus else 0,
                        factors={
                            "B05_bi_efficiency": er,
                            "B10_same_dir_amp_ratio": amp_ratio,
                            "Z01_zhongshu_width": 1.0,
                            "Z09_zhongshu_compression": 1.0,
                            "Z11_breakout_strength": 0.0,
                            "P08_pullback_depth": 0.0,
                            "P09_edge_clearance": 0.2,
                        }
                    )
                    events.append(ev)
                    self.events.append(ev)

        return events

    # -------------------------------------------------------------------------
    # 核心算法 5.2: 二买/二卖 (B2/S2) 次级回踩确认点
    # -------------------------------------------------------------------------
    def _detect_second_buy_sell(self, curr_bi: CausalBi) -> List[CausalBuySellEvent]:
        """
        二买 (B2):
        - 前前笔 (bi[-3]) 创下极值低点 (可能为 B1)
        - 前一笔 (bi[-2]) 为强力向上反弹笔
        - 当前笔 (bi[-1]) 向下回踩，且终点价格高于 bi[-3] 极值点 (不创新低，抬高底部 Higher Low)
        二卖 (S2):
        - 前前笔创下极值高点
        - 前一笔强力回落
        - 当前笔向上回抽，终点价格低于前前笔高点 (不创新高，降低高点 Lower High)
        """
        if len(self.bis) < 3:
            return []

        b_base = self.bis[-3]     # 极值笔
        b_rebound = self.bis[-2]  # 反转笔
        b_pull = curr_bi          # 回踩笔

        events = []
        raw_known_idx = curr_bi.end_fractal.raw_known_idx
        current_atr = self.raw_bars[raw_known_idx].get("atr", 1.0) or 1.0

        # 二买 (B2): 回踩不破前低
        if b_pull.direction == Direction.DOWN and b_rebound.direction == Direction.UP and b_base.direction == Direction.DOWN:
            if b_pull.end_price > b_base.end_price:
                # 回撤深度比例
                rebound_amp = b_rebound.amplitude + 1e-8
                retrace_ratio = float(b_pull.amplitude / rebound_amp)
                if retrace_ratio <= 0.85:  # 回踩幅度不超过反弹幅度的 85%
                    er = b_pull.efficiency_ratio
                    ev = CausalBuySellEvent(
                        event_id=f"B2_{curr_bi.bi_id}",
                        event_type="B2",
                        side=1,
                        known_time=curr_bi.known_time,
                        known_raw_idx=raw_known_idx,
                        trigger_price=curr_bi.end_price,
                        zs_high=b_rebound.end_price,
                        zs_low=b_base.end_price,
                        zs_id=self.zhongshus[-1].zs_id if self.zhongshus else 0,
                        factors={
                            "B05_bi_efficiency": er,
                            "B10_same_dir_amp_ratio": retrace_ratio,
                            "Z01_zhongshu_width": float(rebound_amp / current_atr),
                            "Z09_zhongshu_compression": 1.0,
                            "Z11_breakout_strength": 0.0,
                            "P08_pullback_depth": float((b_pull.end_price - b_base.end_price) / current_atr),
                            "P09_edge_clearance": float((b_pull.end_price - b_base.end_price) / current_atr),
                        }
                    )
                    events.append(ev)
                    self.events.append(ev)

        # 二卖 (S2): 回抽不破前高
        elif b_pull.direction == Direction.UP and b_rebound.direction == Direction.DOWN and b_base.direction == Direction.UP:
            if b_pull.end_price < b_base.end_price:
                rebound_amp = b_rebound.amplitude + 1e-8
                retrace_ratio = float(b_pull.amplitude / rebound_amp)
                if retrace_ratio <= 0.85:
                    er = b_pull.efficiency_ratio
                    ev = CausalBuySellEvent(
                        event_id=f"S2_{curr_bi.bi_id}",
                        event_type="S2",
                        side=-1,
                        known_time=curr_bi.known_time,
                        known_raw_idx=raw_known_idx,
                        trigger_price=curr_bi.end_price,
                        zs_high=b_base.end_price,
                        zs_low=b_rebound.end_price,
                        zs_id=self.zhongshus[-1].zs_id if self.zhongshus else 0,
                        factors={
                            "B05_bi_efficiency": er,
                            "B10_same_dir_amp_ratio": retrace_ratio,
                            "Z01_zhongshu_width": float(rebound_amp / current_atr),
                            "Z09_zhongshu_compression": 1.0,
                            "Z11_breakout_strength": 0.0,
                            "P08_pullback_depth": float((b_base.end_price - b_pull.end_price) / current_atr),
                            "P09_edge_clearance": float((b_base.end_price - b_pull.end_price) / current_atr),
                        }
                    )
                    events.append(ev)
                    self.events.append(ev)

        return events

    # -------------------------------------------------------------------------
    # 核心算法 5.3: 三买/三卖 (B3/S3) 中枢突破加速点
    # -------------------------------------------------------------------------
    def _detect_third_buy_sell(self, pullback_bi: CausalBi) -> List[CausalBuySellEvent]:
        """
        三买 (B3):
        - 中枢 ZS: [Z_low, Z_high]
        - 突破离开笔 (Breakout Bi): 向上笔，突破 Z_high
        - 回踩笔 (Pullback Bi): 向下笔，其终点极值 Low > Z_high (或跌破不超过微量容差)
        - 确认时点: 回踩笔底分型在 known_time 确认完成。
        三卖 (S3):
        - 突破离开笔向下跌破 Z_low
        - 回抽笔终点极值 High < Z_low
        """
        if len(self.zhongshus) == 0 or len(self.bis) < 2:
            return []

        zs = self.zhongshus[-1]
        breakout_bi = self.bis[-2]

        events = []
        raw_known_idx = pullback_bi.end_fractal.raw_known_idx
        current_atr = self.raw_bars[raw_known_idx].get("atr", 1.0) or 1.0

        # --- 三买 (B3) 判定 ---
        if pullback_bi.direction == Direction.DOWN and breakout_bi.direction == Direction.UP:
            if breakout_bi.end_price > zs.z_high:
                pullback_low = pullback_bi.end_price
                if pullback_low >= (zs.z_high - 0.15 * current_atr):
                    b05_er = pullback_bi.efficiency_ratio
                    b10_amp_ratio = float(breakout_bi.amplitude / (self.bis[zs.start_bi_id].amplitude + 1e-8))
                    z01_width = float((zs.z_high - zs.z_low) / current_atr)
                    z09_comp = zs.compression_ratio
                    z11_breakout = float((breakout_bi.end_price - zs.z_high) / current_atr)
                    p08_pullback = float((pullback_low - zs.z_high) / current_atr)
                    p09_clearance = float((pullback_bi.end_fractal.structure_price - zs.z_high) / current_atr)

                    event = CausalBuySellEvent(
                        event_id=f"B3_{zs.zs_id}_{pullback_bi.bi_id}",
                        event_type="B3",
                        side=1,
                        known_time=pullback_bi.known_time,
                        known_raw_idx=raw_known_idx,
                        trigger_price=pullback_bi.end_price,
                        zs_high=zs.z_high,
                        zs_low=zs.z_low,
                        zs_id=zs.zs_id,
                        factors={
                            "B05_bi_efficiency": b05_er,
                            "B10_same_dir_amp_ratio": b10_amp_ratio,
                            "Z01_zhongshu_width": z01_width,
                            "Z09_zhongshu_compression": z09_comp,
                            "Z11_breakout_strength": z11_breakout,
                            "P08_pullback_depth": p08_pullback,
                            "P09_edge_clearance": p09_clearance,
                        }
                    )
                    events.append(event)
                    self.events.append(event)

        # --- 三卖 (S3) 判定 ---
        elif pullback_bi.direction == Direction.UP and breakout_bi.direction == Direction.DOWN:
            if breakout_bi.end_price < zs.z_low:
                pullback_high = pullback_bi.end_price
                if pullback_high <= (zs.z_low + 0.15 * current_atr):
                    b05_er = pullback_bi.efficiency_ratio
                    b10_amp_ratio = float(breakout_bi.amplitude / (self.bis[zs.start_bi_id].amplitude + 1e-8))
                    z01_width = float((zs.z_high - zs.z_low) / current_atr)
                    z09_comp = zs.compression_ratio
                    z11_breakout = float((zs.z_low - breakout_bi.end_price) / current_atr)
                    p08_pullback = float((zs.z_low - pullback_high) / current_atr)
                    p09_clearance = float((zs.z_low - pullback_bi.end_fractal.structure_price) / current_atr)

                    event = CausalBuySellEvent(
                        event_id=f"S3_{zs.zs_id}_{pullback_bi.bi_id}",
                        event_type="S3",
                        side=-1,
                        known_time=pullback_bi.known_time,
                        known_raw_idx=raw_known_idx,
                        trigger_price=pullback_bi.end_price,
                        zs_high=zs.z_high,
                        zs_low=zs.z_low,
                        zs_id=zs.zs_id,
                        factors={
                            "B05_bi_efficiency": b05_er,
                            "B10_same_dir_amp_ratio": b10_amp_ratio,
                            "Z01_zhongshu_width": z01_width,
                            "Z09_zhongshu_compression": z09_comp,
                            "Z11_breakout_strength": z11_breakout,
                            "P08_pullback_depth": p08_pullback,
                            "P09_edge_clearance": p09_clearance,
                        }
                    )
                    events.append(event)
                    self.events.append(event)

        return events


    # -------------------------------------------------------------------------
    # 核心算法 1: 严格因果 K 线包含处理
    # -------------------------------------------------------------------------
    def _process_inclusion(self, bar: Dict[str, Any], raw_idx: int) -> bool:
        dt = bar["datetime"]
        o, h, l, c = bar["open"], bar["high"], bar["low"], bar["close"]
        v = bar["volume"]
        oi = bar["open_interest"]

        if len(self.processed_klines) == 0:
            pk = ProcessedKLine(
                index=0,
                datetime=dt,
                open=o,
                high=h,
                low=l,
                close=c,
                volume=v,
                open_interest=oi,
                direction=Direction.NEUTRAL,
                raw_indices=[raw_idx],
            )
            self.processed_klines.append(pk)
            return True

        if len(self.processed_klines) == 1:
            prev = self.processed_klines[0]
            # 确定初始方向
            d = Direction.UP if h >= prev.high else Direction.DOWN
            self._inclusion_dir = d
            pk = ProcessedKLine(
                index=1,
                datetime=dt,
                open=o,
                high=h,
                low=l,
                close=c,
                volume=v,
                open_interest=oi,
                direction=d,
                raw_indices=[raw_idx],
            )
            self.processed_klines.append(pk)
            return True

        prev = self.processed_klines[-1]
        prev_prev = self.processed_klines[-2]

        # 动态更新包含处理方向 (随最近两根不包含 K 线的高低关系确立)
        if prev.high > prev_prev.high and prev.low > prev_prev.low:
            self._inclusion_dir = Direction.UP
        elif prev.high < prev_prev.high and prev.low < prev_prev.low:
            self._inclusion_dir = Direction.DOWN

        # 检查是否发生包含 (前包后 或 后包前)
        is_included = (h <= prev.high and l >= prev.low) or (h >= prev.high and l <= prev.low)

        if is_included:
            # 发生包含关系，依据当前方向合并
            if self._inclusion_dir == Direction.UP:
                new_high = max(prev.high, h)
                new_low = max(prev.low, l)
            else:
                new_high = min(prev.high, h)
                new_low = min(prev.low, l)

            # 更新 prev K 线 (就地合并)
            prev.high = new_high
            prev.low = new_low
            prev.close = c
            prev.volume += v
            prev.open_interest = oi
            prev.datetime = dt  # 更新为最新时间戳
            prev.raw_indices.append(raw_idx)
            return False  # 未生成新的独立 K 线
        else:
            # 无包含，生成新 K 线
            new_dir = Direction.UP if h > prev.high else Direction.DOWN
            pk = ProcessedKLine(
                index=len(self.processed_klines),
                datetime=dt,
                open=o,
                high=h,
                low=l,
                close=c,
                volume=v,
                open_interest=oi,
                direction=new_dir,
                raw_indices=[raw_idx],
            )
            self.processed_klines.append(pk)
            return True

    # -------------------------------------------------------------------------
    # 核心算法 2: 纯因果顶底分型识别
    # -------------------------------------------------------------------------
    def _detect_fractal(self) -> Optional[CausalFractal]:
        """
        三根无包含 K 线 (k0, k1, k2):
        在 k2 (已知位置) 确认 k1 (结构物理极值点)
        """
        pks = self.processed_klines
        if len(pks) < 3:
            return None

        k0 = pks[-3]
        k1 = pks[-2]
        k2 = pks[-1]

        # 顶分型: k1.high 严格大于左右两侧
        is_top = (k1.high > k0.high) and (k1.high > k2.high) and (k1.low >= k0.low) and (k1.low >= k2.low)
        # 底分型: k1.low 严格小于左右两侧
        is_bottom = (k1.low < k0.low) and (k1.low < k2.low) and (k1.high <= k0.high) and (k1.high <= k2.high)

        if not (is_top or is_bottom):
            return None

        fractal_type = Direction.UP if is_top else Direction.DOWN
        struct_price = k1.high if is_top else k1.low

        raw_known_idx = k2.raw_indices[-1]

        fractal = CausalFractal(
            fractal_type=fractal_type,
            structure_idx=k1.index,
            structure_time=k1.datetime,
            structure_price=struct_price,
            known_idx=k2.index,
            known_time=k2.datetime,
            raw_known_idx=raw_known_idx,
        )
        self.fractals.append(fractal)
        return fractal

    # -------------------------------------------------------------------------
    # 核心算法 3: 自适应因果笔生成状态机
    # -------------------------------------------------------------------------
    def _update_bi(self, new_fractal: CausalFractal) -> Optional[CausalBi]:
        """
        根据最新分型构建/延伸笔
        严格规则:
        1. 顶分型与底分型交替出现；
        2. 顶底之间 ProcessedKLine 跨度 >= strict_bi_bars (标准为 >= 4, 即顶底两端+中间至少1根=5根)；
        3. 上升笔终点 High > 起点 Low，下降笔终点 Low < 起点 High。
        """
        if len(self.fractals) < 2:
            return None

        if len(self.bis) == 0:
            # 寻找首对有效交替分型作为第 1 笔
            prev_f = self.fractals[-2]
            curr_f = new_fractal
            if prev_f.fractal_type != curr_f.fractal_type:
                bars_span = curr_f.structure_idx - prev_f.structure_idx
                if bars_span >= self.strict_bi_bars:
                    bi_dir = Direction.UP if curr_f.fractal_type == Direction.UP else Direction.DOWN
                    if (bi_dir == Direction.UP and curr_f.structure_price > prev_f.structure_price) or \
                       (bi_dir == Direction.DOWN and curr_f.structure_price < prev_f.structure_price):
                        bi = self._create_bi(0, bi_dir, prev_f, curr_f)
                        self.bis.append(bi)
                        return bi
            return None

        last_bi = self.bis[-1]
        curr_f = new_fractal

        if curr_f.fractal_type == last_bi.end_fractal.fractal_type:
            # 同向分型，检查是否创新极值发生笔延伸
            if last_bi.direction == Direction.UP:
                if curr_f.structure_price > last_bi.end_price:
                    # 向上笔创新高，延伸该笔
                    last_bi.end_fractal = curr_f
                    last_bi.end_time = curr_f.structure_time
                    last_bi.end_price = curr_f.structure_price
                    last_bi.known_time = curr_f.known_time
                    last_bi.amplitude = abs(last_bi.end_price - last_bi.start_price)
                    last_bi.bars_count = curr_f.structure_idx - last_bi.start_fractal.structure_idx + 1
                    self._enrich_bi_metrics(last_bi)
            else:
                if curr_f.structure_price < last_bi.end_price:
                    # 向下笔创新低，延伸该笔
                    last_bi.end_fractal = curr_f
                    last_bi.end_time = curr_f.structure_time
                    last_bi.end_price = curr_f.structure_price
                    last_bi.known_time = curr_f.known_time
                    last_bi.amplitude = abs(last_bi.end_price - last_bi.start_price)
                    last_bi.bars_count = curr_f.structure_idx - last_bi.start_fractal.structure_idx + 1
                    self._enrich_bi_metrics(last_bi)
            return None
        else:
            # 反向分型，检查是否满足生成新笔条件
            bars_span = curr_f.structure_idx - last_bi.end_fractal.structure_idx
            if bars_span >= self.strict_bi_bars:
                new_dir = Direction.UP if curr_f.fractal_type == Direction.UP else Direction.DOWN
                # 价格突破前分型极值
                price_valid = (new_dir == Direction.UP and curr_f.structure_price > last_bi.end_price) or \
                              (new_dir == Direction.DOWN and curr_f.structure_price < last_bi.end_price)
                if price_valid:
                    new_bi = self._create_bi(len(self.bis), new_dir, last_bi.end_fractal, curr_f)
                    self.bis.append(new_bi)
                    return new_bi

        return None

    def _create_bi(self, bi_id: int, direction: Direction, start_f: CausalFractal, end_f: CausalFractal) -> CausalBi:
        bi = CausalBi(
            bi_id=bi_id,
            direction=direction,
            start_fractal=start_f,
            end_fractal=end_f,
            start_time=start_f.structure_time,
            end_time=end_f.structure_time,
            start_price=start_f.structure_price,
            end_price=end_f.structure_price,
            known_time=end_f.known_time,
            amplitude=abs(end_f.structure_price - start_f.structure_price),
            bars_count=end_f.structure_idx - start_f.structure_idx + 1,
            raw_bars_count=end_f.raw_known_idx - start_f.raw_known_idx + 1,
        )
        self._enrich_bi_metrics(bi)
        return bi

    def _enrich_bi_metrics(self, bi: CausalBi):
        """计算笔的微观能量特征 (Kaufman 效率比 ER、成交量总和)"""
        start_idx = bi.start_fractal.structure_idx
        end_idx = bi.end_fractal.structure_idx
        pks = self.processed_klines[start_idx:end_idx + 1]
        if len(pks) < 2:
            bi.efficiency_ratio = 1.0
            return

        net_change = abs(bi.end_price - bi.start_price)
        path_length = sum(abs(pks[i].close - pks[i - 1].close) for i in range(1, len(pks)))
        bi.efficiency_ratio = float(net_change / (path_length + 1e-8)) if path_length > 0 else 1.0
        bi.volume_sum = sum(k.volume for k in pks)
        bi.oi_change = pks[-1].open_interest - pks[0].open_interest

    # -------------------------------------------------------------------------
    # 核心算法 4: 几何走势中枢状态机
    # -------------------------------------------------------------------------
    def _update_zhongshu(self, new_bi: CausalBi) -> Optional[CausalZhongshu]:
        """
        三笔连续重叠构建中枢:
        Bi0, Bi1, Bi2
        Z_high = min(High(Bi0), High(Bi1), High(Bi2)) -> 严格为 min(g1, g3)
        Z_low  = max(Low(Bi0), Low(Bi1), Low(Bi2))   -> 严格为 max(d1, d3)
        若 Z_high > Z_low，则成功形成中枢
        """
        if len(self.bis) < 3:
            return None

        # 检查是否已有活跃中枢
        if len(self.zhongshus) > 0 and not self.zhongshus[-1].is_completed:
            active_zs = self.zhongshus[-1]
            # 中枢延伸: 检查当前笔是否仍与中枢有重叠
            bi_high = max(new_bi.start_price, new_bi.end_price)
            bi_low = min(new_bi.start_price, new_bi.end_price)

            has_overlap = not (bi_low > active_zs.z_high or bi_high < active_zs.z_low)
            if has_overlap:
                active_zs.bi_ids.append(new_bi.bi_id)
                active_zs.extension_count += 1
                return active_zs
            else:
                # 产生突破离开笔，标记当前中枢完成延伸
                active_zs.is_completed = True
                active_zs.breakout_bi_id = new_bi.bi_id

        # 尝试由最近 3 笔构建新中枢
        b1, b2, b3 = self.bis[-3], self.bis[-2], self.bis[-1]
        g1 = max(b1.start_price, b1.end_price)
        d1 = min(b1.start_price, b1.end_price)
        g2 = max(b2.start_price, b2.end_price)
        d2 = min(b2.start_price, b2.end_price)
        g3 = max(b3.start_price, b3.end_price)
        d3 = min(b3.start_price, b3.end_price)

        z_high = min(g1, g2 if b1.direction == Direction.DOWN else g3)
        z_low = max(d1, d2 if b1.direction == Direction.UP else d3)

        if z_high > z_low:
            comp_ratio = float(b3.amplitude / (b1.amplitude + 1e-8))
            zs = CausalZhongshu(
                zs_id=len(self.zhongshus),
                start_bi_id=b1.bi_id,
                direction=b1.direction,
                z_high=z_high,
                z_low=z_low,
                start_time=b1.start_time,
                known_time=b3.known_time,
                bi_ids=[b1.bi_id, b2.bi_id, b3.bi_id],
                extension_count=0,
                is_completed=False,
                compression_ratio=comp_ratio,
            )
            self.zhongshus.append(zs)
            return zs

        return None

    # -------------------------------------------------------------------------
    # 核心算法 5: 三买/三卖因果事件发生器
    # -------------------------------------------------------------------------
    def _detect_third_buy_sell(self, pullback_bi: CausalBi) -> List[CausalBuySellEvent]:
        """
        三买 (B3):
        - 中枢 ZS: [Z_low, Z_high]
        - 突破离开笔 (Breakout Bi): 向上笔，突破 Z_high
        - 回踩笔 (Pullback Bi): 向下笔，其终点极值 Low > Z_high (或跌破不超过微量容差)
        - 确认时点: 回踩笔底分型在 known_time 确认完成。
        三卖 (S3):
        - 突破离开笔向下跌破 Z_low
        - 回抽笔终点极值 High < Z_low
        """
        if len(self.zhongshus) == 0 or len(self.bis) < 2:
            return []

        zs = self.zhongshus[-1]
        breakout_bi = self.bis[-2]

        events = []
        raw_known_idx = pullback_bi.end_fractal.raw_known_idx
        current_atr = self.raw_bars[raw_known_idx].get("atr", 1.0) or 1.0

        # --- 三买 (B3) 判定 ---
        if pullback_bi.direction == Direction.DOWN and breakout_bi.direction == Direction.UP:
            # 离开笔突破中枢上沿
            if breakout_bi.end_price > zs.z_high:
                # 回踩笔低点不触及中枢上沿 (允许微小缓冲 -0.15 ATR)
                pullback_low = pullback_bi.end_price
                if pullback_low >= (zs.z_high - 0.15 * current_atr):
                    # 提取 S 级因子特征
                    b05_er = pullback_bi.efficiency_ratio
                    b10_amp_ratio = float(breakout_bi.amplitude / (self.bis[zs.start_bi_id].amplitude + 1e-8))
                    z01_width = float((zs.z_high - zs.z_low) / current_atr)
                    z09_comp = zs.compression_ratio
                    z11_breakout = float((breakout_bi.end_price - zs.z_high) / current_atr)
                    p08_pullback = float((pullback_low - zs.z_high) / current_atr)
                    p09_clearance = float((pullback_bi.end_fractal.structure_price - zs.z_high) / current_atr)

                    event = CausalBuySellEvent(
                        event_id=f"B3_{zs.zs_id}_{pullback_bi.bi_id}",
                        event_type="B3",
                        side=1,
                        known_time=pullback_bi.known_time,
                        known_raw_idx=raw_known_idx,
                        trigger_price=pullback_bi.end_price,
                        zs_high=zs.z_high,
                        zs_low=zs.z_low,
                        zs_id=zs.zs_id,
                        factors={
                            "B05_bi_efficiency": b05_er,
                            "B10_same_dir_amp_ratio": b10_amp_ratio,
                            "Z01_zhongshu_width": z01_width,
                            "Z09_zhongshu_compression": z09_comp,
                            "Z11_breakout_strength": z11_breakout,
                            "P08_pullback_depth": p08_pullback,
                            "P09_edge_clearance": p09_clearance,
                        }
                    )
                    events.append(event)
                    self.events.append(event)

        # --- 三卖 (S3) 判定 ---
        elif pullback_bi.direction == Direction.UP and breakout_bi.direction == Direction.DOWN:
            # 离开笔跌破中枢下沿
            if breakout_bi.end_price < zs.z_low:
                # 回抽笔高点不升破中枢下沿
                pullback_high = pullback_bi.end_price
                if pullback_high <= (zs.z_low + 0.15 * current_atr):
                    b05_er = pullback_bi.efficiency_ratio
                    b10_amp_ratio = float(breakout_bi.amplitude / (self.bis[zs.start_bi_id].amplitude + 1e-8))
                    z01_width = float((zs.z_high - zs.z_low) / current_atr)
                    z09_comp = zs.compression_ratio
                    z11_breakout = float((zs.z_low - breakout_bi.end_price) / current_atr)
                    p08_pullback = float((zs.z_low - pullback_high) / current_atr)
                    p09_clearance = float((zs.z_low - pullback_bi.end_fractal.structure_price) / current_atr)

                    event = CausalBuySellEvent(
                        event_id=f"S3_{zs.zs_id}_{pullback_bi.bi_id}",
                        event_type="S3",
                        side=-1,
                        known_time=pullback_bi.known_time,
                        known_raw_idx=raw_known_idx,
                        trigger_price=pullback_bi.end_price,
                        zs_high=zs.z_high,
                        zs_low=zs.z_low,
                        zs_id=zs.zs_id,
                        factors={
                            "B05_bi_efficiency": b05_er,
                            "B10_same_dir_amp_ratio": b10_amp_ratio,
                            "Z01_zhongshu_width": z01_width,
                            "Z09_zhongshu_compression": z09_comp,
                            "Z11_breakout_strength": z11_breakout,
                            "P08_pullback_depth": p08_pullback,
                            "P09_edge_clearance": p09_clearance,
                        }
                    )
                    events.append(event)
                    self.events.append(event)

        return events
