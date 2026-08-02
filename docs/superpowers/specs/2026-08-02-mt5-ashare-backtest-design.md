# MT5 A 股日线回测接入设计

## 目标

在当前 macOS Wine 版 MetaTrader 5 中，使用 `lianghua` 本地 SQLite 行情完成一轮可重复的 MT5 策略测试：

- 标的：`603986`
- MT5 自定义品种：`CN_603986`
- 策略：Supertrend，`period=10`、`multiplier=3.0`
- 区间：`2024-01-01` 至 `2026-07-28`
- 初始资金：`1,000,000`
- 数据粒度：日线
- 执行语义：当日收盘确认方向，下一交易日开盘执行

## 方案

保留 SQLite 作为唯一行情源，不把 Python 嵌入 MT5 策略测试器：

1. 复用 `AShareDataEngine`，通过 AKShare 更新 `603986` 日线。
2. Python 从 `ashare_quant.db` 导出 MT5 可导入的行情文件。
3. `LianghuaImporter.mq5` 创建自定义品种并导入行情。
4. `LianghuaSupertrendEA.mq5` 在 MT5 内原生计算 Supertrend 和交易。
5. 使用 MT5 Strategy Tester 运行 D1 回测并保存报告。
6. 使用现有 Python 回测结果核对 MT5 的信号和交易日期。

不安装原生 macOS `MetaTrader5` Python 包。该包用于 Python 与 Windows MT5 终端进程通信，不能让 Python 策略在 Strategy Tester 中执行，在当前 Wine 架构下也不是完成目标所需依赖。

## 组件

### 数据更新与导出

新增一个最小 Python 命令，负责：

- 调用现有数据引擎更新单个标的；
- 校验日期唯一、OHLC 为有限正数且 `high >= open/close >= low`；
- 从 SQLite 读取截至 `2026-07-28` 的数据；
- 输出 MT5 行情文件和一份 Python 参考信号文件；
- 失败时不覆盖上一份有效导出。

SQLite 数据库继续位于 `lianghua/data/ashare_quant.db`。

### MT5 行情导入

`LianghuaImporter.mq5`：

- 创建或更新 `CN_603986`；
- 设置人民币、合约大小、最小交易量和交易时段；
- 将每个交易日的 OHLCV 导入自定义品种；
- 导入后校验首日、末日和记录数；
- 导入失败时输出明确错误码，不启动回测。

当前源数据只有日线。导入数据用于 D1、Open prices only 回测，不宣称具备分钟或 Tick 级精度。

### Supertrend EA

`LianghuaSupertrendEA.mq5` 只实现本次需要的功能：

- 输入参数仅包括 ATR 周期、倍数、仓位比例和 Magic Number；
- Supertrend 计算与 `strategy_signal_library.supertrend_signal` 一致；
- 只在新 D1 K 线第一次事件中运行；
- 使用已经收盘的前一根 D1 K 线计算信号；
- 多头方向且无持仓时买入，空头方向且有持仓时平仓；
- 不做空，不重复加仓；
- 交易量按 20% 目标仓位和自定义品种交易规格取整。

不移植 LightGBM、HMM、Web UI、组合回测和其余 16 个策略。

## 自动化流程

1. 在工作区生成并验证 Python/MQL5 文件。
2. 把 MQL5 源文件和行情文件复制到已检测到的 MT5 Wine 数据目录。
3. 调用 MetaEditor 编译，要求零编译错误。
4. 启动导入器，检查 MT5 日志确认自定义品种数据已就绪。
5. 通过测试配置启动 Strategy Tester。
6. 把测试日志和报告复制回 `lianghua/mt5/results/`。

写入 MT5 数据目录、启动 GUI 或执行 Wine 程序时，如系统要求权限，由用户批准一次权限提示。

## 费用与成交

首次基线回测使用 MT5 高级测试设置近似现有费用：

- 买入佣金与过户费；
- 卖出佣金、过户费与印花税；
- 0.1% 滑点按测试器可用设置模拟。

MT5 静态佣金配置不能按历史政策切换日自动改变税率，因此费用可能与 Python 模拟器存在小额差异。信号日期和开平仓方向必须一致，净值允许因费用模型产生差异。

## 验证标准

- Python 数据导出检查通过；
- `603986` 数据无重复日期，OHLC 合法；
- 两个 MQL5 程序编译零错误；
- `CN_603986` 在 MT5 中包含目标回测区间；
- Strategy Tester 正常完成且报告中至少有一笔成交；
- MT5 与 Python 的 Supertrend 方向切换日期一致；
- 首笔和末笔开平仓日期一致，或对由 MT5 数据时区造成的一日偏差给出证据；
- 日志和报告保存到工作区。

## 失败处理

- AKShare 更新失败：保留已有数据库，若已有数据覆盖目标区间则继续，否则停止。
- 导出校验失败：不覆盖有效文件并停止。
- MQL5 编译失败：保存编译日志并停止，不运行旧版 EA。
- 行情导入或自定义品种校验失败：不启动 Strategy Tester。
- 自动化受 macOS 权限阻止：请求对应的最小权限后重试。
