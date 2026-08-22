# S-Grade 纯量价结构性 Alpha 策略详细回测报告

---

## 1. 策略概览与执行准入判定
* **策略名称**：`S-Grade Pure OHLCV Structural Alpha (Top-8)`
* **模型后端**：`Qlib LightGBM + 结构性微观特征提取 (Zero Market Beta)`
* **回测区间**：`2026-05-11 ~ 2026-07-28` (样本外 Out-of-Sample)
* **初始资金**：`1,000,000.00 CNY`
* **期末净值**：`1,049,479.71 CNY`
* **综合评分**：**86.5 / 100.0 分 (S 级)**
* **执行决策**：**【准予执行 · 实盘候选】(APPROVED)**

---

## 2. 核心绩效指标 (Performance Metrics)
* **累计超额收益**：`+4.95 %`
* **年化夏普比率 (Sharpe)**：`1.65`
* **索提诺比率 (Sortino)**：`2.82`
* **卡玛比率 (Calmar)**：`4.43`
* **年化波动率**：`13.72 %`
* **最长回撤持续期**：`45 天`
* **总交易换手率**：`14.88 x`
* **总交易成本 (佣金+印花税+滑点)**：`17,385.29 CNY`

---

## 3. 因子质量与天梯榜表现
* **样本外 Mean Rank IC**：`+0.0474`
* **样本外 Rank ICIR**：`+6.90`
* **IC 正胜率**：`64.7 %`
* **核心量价因子**：
  - `kaufman_efficiency_20` (KER 趋势效率比): Rank ICIR +4.93, 多空夏普 +4.74
  - `vol_squeeze_ratio_20` (波动率挤压比): Rank ICIR +3.96, 多空夏普 +2.72
  - `breakout_channel_pos_20` (唐奇安突破位置): 单调性得分 1.00

---

## 4. 交付文件清单
* **交互式 HTML 研报**：[report.html](/Users/tang/PycharmProjects/pythonProject/lianghua/data/reports/s_grade_pure_ohlcv_latest/report.html)
* **日度资金流水 CSV**：[daily_ledger.csv](/Users/tang/PycharmProjects/pythonProject/lianghua/data/reports/s_grade_pure_ohlcv_latest/daily_ledger.csv)
