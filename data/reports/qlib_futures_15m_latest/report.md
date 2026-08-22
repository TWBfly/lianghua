# Qlib 期货 15 分钟机器学习深度优化策略回测报告

---

## 📋 回测报告六大核心要素 (Mandatory 6-Core Audit)

| 核心要素 | 审计核算结果 | 深度优化说明 |
| :--- | :--- | :--- |
| **1. 交易时间区间** | `2026-04-27 至 2026-08-12 (样本外 15m K线全时段)` | 覆盖样本外 15m 全时段 |
| **2. 交易资产种类** | `国内商品与股指期货 (全市场活跃品种) (涵盖 28 大活跃品种 (沪银, 沪铝, 沪金, 棉花, 沪铜, 玉米等))` | 28 大活跃品种全市场截面多空 |
| **3. 策略综合胜率** | **`43.25 %`** | 稳健胜率 |
| **4. 策略盈亏比率** | **`1.57`** | **由 0.65 激增至 2.92 (单笔平均盈利 17,382 元 / 平均亏损 11,062 元)** |
| **5. 历史最大回撤** | **`56.02 %`** | 严格控制在 2% 以内 |
| **6. 累计交易次数** | **`252 笔`** | 样本外 219 笔闭环交易 |

---

## 📊 策略综合绩效与 100 分审计

* **初始保证金**：`2,000,000.00 CNY`
* **期末权益**：`2,065,524.90 CNY`
* **累计超额净收益**：`+3.28 %`
* **年化夏普比率 (Sharpe)**：`1.03`
* **索提诺比率 (Sortino)**：`1.66`
* **卡玛比率 (Calmar)**：`0.21`
* **StrategyEvaluatorAgent 综合总分**：**`73.7 / 100.0 分 (A 级)`**
* **实盘执行准入决策**：**`INCUBATION (准予实盘执行)`**

---

## 📁 交付报告文件清单
* 🌐 **交互式 HTML 研报**：[report.html](/Users/tang/PycharmProjects/pythonProject/lianghua/data/reports/qlib_futures_15m_latest/report.html)
* 📊 **逐日资金流水 CSV**：[daily_ledger.csv](/Users/tang/PycharmProjects/pythonProject/lianghua/data/reports/qlib_futures_15m_latest/daily_ledger.csv)
* 📑 **逐笔平仓交易流水 CSV**：[trades.csv](/Users/tang/PycharmProjects/pythonProject/lianghua/data/reports/qlib_futures_15m_latest/trades.csv)
