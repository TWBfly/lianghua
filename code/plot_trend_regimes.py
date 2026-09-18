"""
code/plot_trend_regimes.py — 趋势状态可视化绘制工具

根据用户需求实现：
1. 将趋势状态用线画出来：
   - 上涨趋势 (UPTREND = 1): 红色线 (#ef5350)
   - 下跌趋势 (DOWNTREND = -1): 绿色线 (#26a69a)
   - 横盘趋势 (RANGE = 0): 黄色线 (#fbc02d)
   - 转换状态 (TRANSITION = 2): 灰色虚线 (#9e9e9e)
2. 在趋势状态开始的那根 K 线上进行文字标注：
   - 切换到上涨趋势的开始 K 线：标注显示「多」（红色）
   - 切换到下跌趋势的开始 K 线：标注显示「空」（绿色）
   - 切换到横盘趋势的开始 K 线：标注显示「横盘」（黄色）
3. 生成双重图表：
   - 交互式 Plotly HTML 文件 (支持无缝放大缩小、平移、悬停查看微观指标)
   - 高清 Matplotlib PNG 静态图片 (支持直接查看与导出)
"""

from __future__ import annotations

import os
import sys
import argparse
import sqlite3
from pathlib import Path
from typing import Dict, List, Tuple, Any

import numpy as np
import pandas as pd

# 设置 matplotlib 缓存目录避免每次构建字体缓存
_CACHE_DIR = Path(__file__).resolve().parent.parent / ".cache_mpl"
_CACHE_DIR.mkdir(parents=True, exist_ok=True)
os.environ["MPLCONFIGDIR"] = str(_CACHE_DIR)

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.patches as patches

import plotly.graph_objects as go
from plotly.subplots import make_subplots

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.append(str(PROJECT_ROOT / "code"))
sys.path.append(str(PROJECT_ROOT / "strategies"))

from contract_specs import get_spec
from regime_trend_evolution_engine import CurrentTrendDetector, FutureTrendForecaster

DB_PATH = str(PROJECT_ROOT / "data/ashare_quant.db")
REPORTS_DIR = PROJECT_ROOT / "reports"
REPORTS_DIR.mkdir(parents=True, exist_ok=True)


def load_kline_data(symbol: str = "AG_IDX", timeframe: str = "15m", bars: int = 250) -> pd.DataFrame:
    """从数据库中严格加载指定品种和周期的最近 N 根分时 K 线."""
    with sqlite3.connect(DB_PATH) as conn:
        query = (
            "SELECT trade_time, open, high, low, close, volume, open_interest "
            "FROM futures_min_bars "
            "WHERE symbol=? AND timeframe=? "
            "ORDER BY trade_time DESC LIMIT ?"
        )
        df = pd.read_sql_query(query, conn, params=(symbol, timeframe, bars))

    if len(df) == 0:
        raise ValueError(f"数据库中未找到品种 {symbol} 在 {timeframe} 周期的有效数据！")

    df = df.sort_values("trade_time").reset_index(drop=True)
    df["trade_time"] = pd.to_datetime(df["trade_time"])
    for col in ["open", "high", "low", "close", "volume", "open_interest"]:
        df[col] = df[col].astype(float)
    return df


def calculate_regimes(df: pd.DataFrame) -> pd.DataFrame:
    """运行第一步当前状态识别与第二步未来延续预测."""
    detector = CurrentTrendDetector(fast_period=10, slow_period=30, er_window=20)
    df_step1 = detector.analyze(df)
    forecaster = FutureTrendForecaster(lookback=20)
    df_res = forecaster.analyze(df_step1)
    return df_res


def generate_plotly_interactive_chart(
    df: pd.DataFrame,
    symbol: str,
    timeframe: str,
    output_html_path: str,
):
    """
    生成高交互式 Plotly 暗色交易员风格 HTML 图表：
    - 主图：Candlestick + 状态分色趋势折线 (红/绿/黄) + 开始 K 线显示「多/空/横盘」
    - 副图 1：成交量柱状图
    - 副图 2：第二步延续概率 P(Continue) 与 趋势强度 TS
    """
    spec = get_spec(symbol)
    n = len(df)
    times = df["trade_time"].dt.strftime("%Y-%m-%d %H:%M").values
    opens = df["open"].values
    highs = df["high"].values
    lows = df["low"].values
    closes = df["close"].values
    volumes = df["volume"].values
    states = df["market_state"].values
    ss_line = df["ss_fast"].values
    ts_scores = df["trend_strength"].values
    p_conts = df["p_continue"].values

    fig = make_subplots(
        rows=3,
        cols=1,
        shared_xaxes=True,
        vertical_spacing=0.03,
        row_heights=[0.65, 0.15, 0.20],
        subplot_titles=(
            f"{symbol} ({spec.name}) - {timeframe} 趋势状态演化全息图",
            "成交量 (Volume)",
            "趋势状态特征 (P_Continue 延续概率 & TS 趋势强度)",
        ),
    )

    # 1. 绘制 K 线 (蜡烛图)
    fig.add_trace(
        go.Candlestick(
            x=times,
            open=opens,
            high=highs,
            low=lows,
            close=closes,
            name="K线 (OHLC)",
            increasing_line_color="#ef5350",  # 红涨
            increasing_fillcolor="#ef5350",
            decreasing_line_color="#26a69a",  # 绿跌
            decreasing_fillcolor="#26a69a",
            opacity=0.85,
        ),
        row=1,
        col=1,
    )

    # 2. 绘制分色趋势线：上涨=红色，下跌=绿色，横盘=黄色，过渡=灰色
    state_colors = {
        1: ("#ef5350", "上涨趋势线 (多)", "solid"),      # 红色
        -1: ("#26a69a", "下跌趋势线 (空)", "solid"),     # 绿色
        0: ("#fbc02d", "横盘震荡线 (横盘)", "solid"),    # 黄色
        2: ("#9e9e9e", "过渡/中性线", "dot"),           # 灰色虚线
    }

    shown_legends = set()
    i = 0
    while i < n - 1:
        st = states[i]
        j = i
        while j < n - 1 and states[j + 1] == st:
            j += 1
        seg_end = min(j + 1, n - 1)
        seg_x = times[i : seg_end + 1]
        seg_y = ss_line[i : seg_end + 1]
        color, name, dash = state_colors.get(st, ("#9e9e9e", "未知", "solid"))

        show_legend = st not in shown_legends
        if show_legend:
            shown_legends.add(st)

        fig.add_trace(
            go.Scatter(
                x=seg_x,
                y=seg_y,
                mode="lines",
                line=dict(color=color, width=3.2, dash=dash),
                name=name,
                legendgroup=f"state_{st}",
                showlegend=show_legend,
                hoverinfo="skip",
            ),
            row=1,
            col=1,
        )
        i = j + 1

    # 3. 在趋势状态开始的那根 K 线上标注显示：多 / 空 / 横盘
    state_start_indices: List[Tuple[int, int]] = []
    for k in range(1, n):
        if states[k] != states[k - 1]:
            state_start_indices.append((k, states[k]))

    for idx, st in state_start_indices:
        t_str = times[idx]
        c_k = closes[idx]
        h_k = highs[idx]
        l_k = lows[idx]

        if st == 1:
            # 上涨开始 K 线 -> 显示「多」
            fig.add_annotation(
                x=t_str,
                y=l_k * 0.998,
                text="<b>多</b>",
                showarrow=True,
                arrowhead=2,
                arrowsize=1.2,
                arrowwidth=2,
                arrowcolor="#ef5350",
                ax=0,
                ay=35,
                bgcolor="#b71c1c",
                bordercolor="#ef5350",
                borderwidth=1.5,
                borderpad=4,
                font=dict(color="#ffffff", size=13, family="PingFang SC, Arial, sans-serif"),
                row=1,
                col=1,
            )
        elif st == -1:
            # 下跌开始 K 线 -> 显示「空」
            fig.add_annotation(
                x=t_str,
                y=h_k * 1.002,
                text="<b>空</b>",
                showarrow=True,
                arrowhead=2,
                arrowsize=1.2,
                arrowwidth=2,
                arrowcolor="#26a69a",
                ax=0,
                ay=-35,
                bgcolor="#004d40",
                bordercolor="#26a69a",
                borderwidth=1.5,
                borderpad=4,
                font=dict(color="#ffffff", size=13, family="PingFang SC, Arial, sans-serif"),
                row=1,
                col=1,
            )
        elif st == 0:
            # 横盘开始 K 线 -> 显示「横盘」
            fig.add_annotation(
                x=t_str,
                y=(h_k + l_k) * 0.5,
                text="<b>横盘</b>",
                showarrow=True,
                arrowhead=1,
                arrowsize=1.0,
                arrowwidth=1.5,
                arrowcolor="#fbc02d",
                ax=0,
                ay=-45 if c_k >= opens[idx] else 45,
                bgcolor="#f57f17",
                bordercolor="#fbc02d",
                borderwidth=1.2,
                borderpad=3,
                font=dict(color="#ffffff", size=11, family="PingFang SC, Arial, sans-serif"),
                row=1,
                col=1,
            )

    # 4. 副图 1: 成交量柱状图
    vol_colors = [
        "#ef5350" if closes[m] >= opens[m] else "#26a69a" for m in range(n)
    ]
    fig.add_trace(
        go.Bar(
            x=times,
            y=volumes,
            marker_color=vol_colors,
            name="成交量",
            opacity=0.75,
            showlegend=False,
        ),
        row=2,
        col=1,
    )

    # 5. 副图 2: P(Continue) 延续概率与趋势强度 TS
    fig.add_trace(
        go.Scatter(
            x=times,
            y=p_conts * 100.0,
            mode="lines",
            line=dict(color="#42a5f5", width=2.0),
            name="P(Continue) 延续概率(%)",
        ),
        row=3,
        col=1,
    )
    fig.add_trace(
        go.Scatter(
            x=times,
            y=ts_scores,
            mode="lines",
            line=dict(color="#ab47bc", width=1.5, dash="dot"),
            name="TS 趋势强度 (0~100)",
        ),
        row=3,
        col=1,
    )

    # 添加副图基准参考线
    fig.add_hline(y=50, line_dash="dash", line_color="#757575", row=3, col=1)
    fig.add_hline(y=65, line_dash="dot", line_color="#ef5350", row=3, col=1)

    # 布局美化 (Dark Theme)
    fig.update_layout(
        template="plotly_dark",
        paper_bgcolor="#121212",
        plot_bgcolor="#1e1e1e",
        xaxis_rangeslider_visible=False,
        height=950,
        margin=dict(l=50, r=50, t=60, b=40),
        legend=dict(
            orientation="h",
            yanchor="bottom",
            y=1.02,
            xanchor="center",
            x=0.5,
            bgcolor="rgba(30, 30, 30, 0.8)",
            bordercolor="#424242",
            borderwidth=1,
        ),
        hovermode="x unified",
    )
    fig.update_yaxes(title_text="价格 (Price)", row=1, col=1, gridcolor="#2c2c2c")
    fig.update_yaxes(title_text="成交量", row=2, col=1, gridcolor="#2c2c2c")
    fig.update_yaxes(title_text="概率 / 强度", row=3, col=1, range=[0, 100], gridcolor="#2c2c2c")
    fig.update_xaxes(gridcolor="#2c2c2c")

    fig.write_html(output_html_path, include_plotlyjs="cdn")
    print(f"✅ 交互式 HTML 图表已保存至: {output_html_path}")


def generate_matplotlib_static_image(
    df: pd.DataFrame,
    symbol: str,
    timeframe: str,
    output_png_path: str,
):
    """
    生成高清 Matplotlib 静态图表并保存为 PNG 图片：
    - 支持直接在系统与图片查看器中打开
    - 针对 Mac 系统设置了中文字体（'Arial Unicode MS', 'PingFang SC', 'STHeiti'）
    - 严格遵循红涨绿跌与黄横盘的标注规范
    """
    plt.rcParams["font.family"] = ["Arial Unicode MS", "PingFang HK", "STHeiti", "Songti SC", "sans-serif"]
    plt.rcParams["axes.unicode_minus"] = False

    n = len(df)
    opens = df["open"].values
    highs = df["high"].values
    lows = df["low"].values
    closes = df["close"].values
    states = df["market_state"].values
    ss_line = df["ss_fast"].values
    p_conts = df["p_continue"].values
    spec = get_spec(symbol)

    fig, (ax_main, ax_sub) = plt.subplots(
        nrows=2,
        ncols=1,
        figsize=(16, 9),
        dpi=180,
        gridspec_kw={"height_ratios": [3.5, 1.2]},
        facecolor="#121212",
    )

    ax_main.set_facecolor("#1e1e1e")
    ax_sub.set_facecolor("#1e1e1e")

    # 1. 绘制 K 线
    indices = np.arange(n)
    for i in range(n):
        o, h, l, c = opens[i], highs[i], lows[i], closes[i]
        c_bar = "#ef5350" if c >= o else "#26a69a"
        # 影线
        ax_main.plot([i, i], [l, h], color=c_bar, linewidth=0.9, alpha=0.9)
        # 实体
        rect_y = min(o, c)
        rect_h = max(abs(c - o), (h - l) * 0.02)
        rect = patches.Rectangle(
            (i - 0.35, rect_y),
            0.7,
            rect_h,
            facecolor=c_bar,
            edgecolor=c_bar,
            alpha=0.85,
        )
        ax_main.add_patch(rect)

    # 2. 绘制趋势状态线 (红/绿/黄/灰)
    state_colors = {
        1: "#ef5350",   # 红 (上涨)
        -1: "#26a69a",  # 绿 (下跌)
        0: "#fbc02d",   # 黄 (横盘)
        2: "#757575",   # 灰 (过渡)
    }

    i = 0
    while i < n - 1:
        st = states[i]
        j = i
        while j < n - 1 and states[j + 1] == st:
            j += 1
        seg_end = min(j + 1, n - 1)
        seg_idx = np.arange(i, seg_end + 1)
        seg_y = ss_line[i : seg_end + 1]
        col = state_colors.get(st, "#757575")
        lw = 2.6 if st in [1, -1, 0] else 1.2
        ls = "-" if st != 2 else ":"
        ax_main.plot(seg_idx, seg_y, color=col, linewidth=lw, linestyle=ls, alpha=0.95)
        i = j + 1

    # 3. 状态翻转标注：多 (红) / 空 (绿) / 横盘 (黄)
    price_span = highs.max() - lows.min()
    for k in range(1, n):
        if states[k] != states[k - 1]:
            st = states[k]
            h_k = highs[k]
            l_k = lows[k]
            if st == 1:
                ax_main.annotate(
                    "多",
                    xy=(k, l_k),
                    xytext=(k, l_k - price_span * 0.04),
                    arrowprops=dict(facecolor="#ef5350", edgecolor="#ef5350", width=1.5, headwidth=6, shrink=0.08),
                    bbox=dict(boxstyle="round,pad=0.3", facecolor="#b71c1c", edgecolor="#ef5350", linewidth=1.2),
                    color="#ffffff",
                    fontsize=10,
                    fontweight="bold",
                    ha="center",
                    va="top",
                )
            elif st == -1:
                ax_main.annotate(
                    "空",
                    xy=(k, h_k),
                    xytext=(k, h_k + price_span * 0.04),
                    arrowprops=dict(facecolor="#26a69a", edgecolor="#26a69a", width=1.5, headwidth=6, shrink=0.08),
                    bbox=dict(boxstyle="round,pad=0.3", facecolor="#004d40", edgecolor="#26a69a", linewidth=1.2),
                    color="#ffffff",
                    fontsize=10,
                    fontweight="bold",
                    ha="center",
                    va="bottom",
                )
            elif st == 0:
                ax_main.annotate(
                    "横盘",
                    xy=(k, (h_k + l_k) * 0.5),
                    xytext=(k, h_k + price_span * 0.03),
                    arrowprops=dict(facecolor="#fbc02d", edgecolor="#fbc02d", width=1.0, headwidth=5, shrink=0.08),
                    bbox=dict(boxstyle="round,pad=0.25", facecolor="#f57f17", edgecolor="#fbc02d", linewidth=1.0),
                    color="#ffffff",
                    fontsize=8.5,
                    fontweight="bold",
                    ha="center",
                    va="bottom",
                )

    # 4. 副图：延续概率 P(Continue) 与 50/70 分界线
    ax_sub.plot(indices, p_conts * 100.0, color="#42a5f5", linewidth=1.8, label="P(Continue) 延续概率(%)")
    ax_sub.axhline(50, color="#757575", linestyle="--", linewidth=1.0, alpha=0.7)
    ax_sub.axhline(65, color="#ef5350", linestyle=":", linewidth=1.2, alpha=0.8, label="强延续警戒线 (65%)")
    ax_sub.set_ylim(0, 100)
    ax_sub.set_ylabel("延续概率 (%)", color="#e0e0e0", fontsize=11)
    ax_sub.legend(loc="upper left", facecolor="#212121", edgecolor="#424242", labelcolor="#e0e0e0", fontsize=9)
    ax_sub.grid(True, color="#2c2c2c", linestyle="--", alpha=0.5)

    # 主图图例与标题
    legend_elements = [
        patches.Patch(facecolor="#ef5350", edgecolor="#ef5350", label="上涨趋势线 (红色，开始标注「多」)"),
        patches.Patch(facecolor="#26a69a", edgecolor="#26a69a", label="下跌趋势线 (绿色，开始标注「空」)"),
        patches.Patch(facecolor="#fbc02d", edgecolor="#fbc02d", label="横盘趋势线 (黄色，开始标注「横盘」)"),
        patches.Patch(facecolor="#757575", edgecolor="#757575", label="过渡/不确定态 (灰色)"),
    ]
    ax_main.legend(
        handles=legend_elements,
        loc="upper left",
        facecolor="#212121",
        edgecolor="#424242",
        labelcolor="#e0e0e0",
        fontsize=10,
    )

    # X 轴刻度展示时间字符串
    step = max(1, n // 8)
    sample_indices = np.arange(0, n, step)
    sample_labels = [df["trade_time"].iloc[idx].strftime("%m-%d %H:%M") for idx in sample_indices]
    ax_sub.set_xticks(sample_indices)
    ax_sub.set_xticklabels(sample_labels, rotation=20, color="#b0bec5", fontsize=9)
    ax_main.set_xticks([])

    ax_main.tick_params(colors="#b0bec5")
    ax_sub.tick_params(colors="#b0bec5")
    ax_main.grid(True, color="#2c2c2c", linestyle="--", alpha=0.5)
    ax_main.set_ylabel("价格 (元)", color="#e0e0e0", fontsize=12)
    ax_main.set_title(
        f"【量化演化系统】{symbol} ({spec.name}) - {timeframe} 趋势状态分色与起止标注图",
        color="#ffffff",
        fontsize=15,
        pad=12,
        fontweight="bold",
    )

    plt.tight_layout()
    plt.savefig(output_png_path, dpi=180, facecolor=fig.get_facecolor(), edgecolor="none")
    plt.close(fig)
    print(f"✅ 高清 PNG 静态图片已保存至: {output_png_path}")


def main():
    parser = argparse.ArgumentParser(description="绘制趋势状态分色线与开始 K 线「多/空/横盘」标注图")
    parser.add_argument("--symbol", type=str, default="AG_IDX", help="期货品种代码 (如 AG_IDX, AU_IDX, RB_IDX)")
    parser.add_argument("--timeframe", type=str, default="15m", help="周期 (15m, 30m, 1h)")
    parser.add_argument("--bars", type=int, default=200, help="展示最近 K 线数量 (默认 200)")
    args = parser.parse_args()

    print(f"🚀 开始提取数据并生成趋势图表: 品种={args.symbol}, 周期={args.timeframe}, 根数={args.bars}")
    df_raw = load_kline_data(symbol=args.symbol, timeframe=args.timeframe, bars=args.bars)
    df_sig = calculate_regimes(df_raw)

    html_path = str(REPORTS_DIR / f"trend_regimes_{args.symbol}_{args.timeframe}.html")
    png_path = str(REPORTS_DIR / f"trend_regimes_{args.symbol}_{args.timeframe}.png")

    generate_plotly_interactive_chart(df_sig, args.symbol, args.timeframe, html_path)
    generate_matplotlib_static_image(df_sig, args.symbol, args.timeframe, png_path)

    print(f"🎉 绘图全部完成！")


if __name__ == "__main__":
    main()
