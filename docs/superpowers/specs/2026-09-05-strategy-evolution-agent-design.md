# 策略自动进化 Agent 系统设计

日期：2026-09-05

状态：设计已确认，等待用户审阅后进入实施计划

首个策略：RC-LSR；后续策略通过同一冻结契约接入

## 1. 目标

构建一个自动研究闭环：

1. 在固定期货品种池上运行现有回测；
2. 将确定性回测结果转换成结构化研究诊断包；
3. 无需 API Key，通过本机已登录 ChatGPT 的 Codex CLI 调用研究 Agent；
4. Agent 只能修改隔离区中的候选策略；
5. 候选进入回测前，先拦截核心策略漂移、未来函数、非法代码和复杂度膨胀；
6. 在固定试验预算内自动重复“分析—修改—验证”；
7. 冻结开发区冠军，只在密封历史盲测集上运行一次；
8. 盲测通过后，只自动晋级 Shadow 虚拟盘。

系统必须允许以 `NO_ROBUST_STRATEGY_FOUND` 结束。禁止不断读取同一盲测结果，直到历史曲线被调成盈利。

## 2. 已确认决策

- 架构：单 Codex 研究 Agent + 不可修改的确定性裁判。
- 登录：复用 Codex CLI 已保存的 ChatGPT 登录态，不存储、不传递外部 API Key。
- AI 唯一写权限：当前 Trial 的候选策略工作区。
- 回测器、行情数据、费用、滑点、切分规则、晋级门禁和密封盲测均对 AI 只读。
- AI 可删除或添加指标，可修改信号逻辑、状态机和受限参数。
- 不可变策略本质：均值回归；RC-LSR 当前的每一个指标并非都不可修改。
- 自动晋级上限：Shadow 虚拟盘；真实资金交易不在本系统范围内。
- 启动前允许一次人工审核的通用策略契约整理；验收后冻结 evaluator hash，研究周期内 AI 永远不能修改裁判。
- V1 只接 Codex CLI；Gemini、Antigravity 只预留 reviewer 位置，不作为 V1 依赖。

## 3. 仓库现有能力与复用边界

有限复用：

- `code/autonomous_alpha_research_engine.py`：公式哈希、实验账本、因子诊断思想。
- `code/learning_loop.py`：Registry、Champion/Challenger、Shadow 和晋级状态思想。
- `code/strategy_hot_plugger.py`：策略发现和 AST 安全校验模式。
- `tests/test_rc_lsr_strategy.py`：前缀不变性和信号契约测试。
- `strategies/rc_lsr_strategy.py`：首个基线策略和策略宪法来源。
- `code/run_rc_lsr_deep_audit.py`：经修正后可作为首个冻结 evaluator 的起点。

不得把 `code/strategy_optimizer_agent.py` 直接作为晋级裁判。其当前流程虽然计算了训练集和测试集，但候选排序使用了包含测试段的全样本结果，相当于把样本外重新泄漏进选择过程。只能在独立验证后复用其中的局部工具。

## 4. 总体架构

```text
不可变输入
  策略宪法
  evaluator manifest + 哈希
  行情数据快照
  费用/滑点/撮合规则
  开发集切分清单
  密封盲测清单
          |
          v
Campaign Controller -----> 基线回测
          |                    |
          |                    v
          |                 研究诊断包
          |                    |
          |                    v
          |              Codex Research Agent
          |                    |
          |          proposal.json + 候选策略
          |                    |
          v                    v
静态检查 -> 策略宪法检查 -> 因果测试
          |                    |
          +---------通过-------+
                       |
                       v
              开发区 Walk-Forward
                       |
                 消融/扰动/成本压力
                       |
                  确定性晋级门禁
                  /             \
             淘汰归档        开发区冠军
                  |              |
                  +----反馈------+    最多 24 个候选
                                 |
                                 v
                              冻结代码
                                 |
                                 v
                         一次性密封盲测
                          /              \
                    Campaign 失败      Shadow 虚拟盘
                                             |
                                      PAPER_APPROVED
```

密封盲测不在反馈箭头内。

## 5. 隔离模型

### 5.1 AI 可写候选区

每个 Trial 创建一次性目录，里面只有：

- `strategy.py`；
- 用于生成 `proposal.json` 和 diff 的空输出目录；
- 不包含行情库、回测源码、`.env`、账户状态或凭据文件。

Codex 以该目录为工作目录，并显式使用 workspace-write 沙箱；shell 网络关闭，禁止权限升级。

策略基线、策略宪法、研究诊断包以只读输入提供。Controller 只接受 `strategy.py` 的变更。

### 5.2 不可变裁判区

Campaign 启动时，对以下内容生成 SHA-256：

- evaluator 源码和可执行产物；
- 数据结构和行情快照；
- 合约乘数、Tick、手续费和保证金配置；
- 滑点、同柱碰撞、换月和撮合规则；
- 数据切分清单和门禁配置。

每个 Trial 前后都重新校验。任一哈希变化，停止整个 Campaign，而不是只淘汰一个候选。

### 5.3 候选执行区

Codex 进程退出后，才在另一个净化子进程中执行候选策略：

- 无网络；
- 不继承账户凭据和秘密环境变量；
- 行情数据只读；
- 输出写入临时目录；
- Python 导入白名单；
- CPU、内存和运行时间上限。

这样可以避免生成的策略代码与拥有 Codex 登录态的进程共存。

## 6. 一次性 evaluator 整理与永久冻结

目前 RC-LSR 入场位于 `strategies/rc_lsr_strategy.py`，退出和成交规则位于 `code/run_rc_lsr_deep_audit.py`。第一轮 Campaign 前，由人审核并完成一次通用契约整理：

1. 定义统一策略契约；
2. 所有成交语义继续由 evaluator 掌握；
3. 策略只能返回因果因子、入场意图和受限的执行政策数据；
4. evaluator 用固定语义解释策略政策；
5. 修正同柱先后顺序、收盘确认后次柱成交、跳空穿越止损、逐柱盯市回撤和期末结算；
6. 增加契约一致性测试；
7. 记录 evaluator hash 并永久冻结。

策略可声明初始 ATR 止损、保本触发、追踪距离、目标定义和最大持仓 Bars 等数据，但不能提供自定义成交回调。新增撮合原语必须创建一个人工审核的新 evaluator 版本和新 Campaign，Agent 无权添加。

## 7. RC-LSR 策略宪法

### 7.1 均值回归本质

- 必须使用 Bar `t` 或更早数据定义因果公平价值中枢。
- 入场前必须出现相对中枢的极端偏离。
- 入场方向必须与偏离方向相反。
- 必须存在衰竭、吸收、失败延续或重新进入中枢方向的确认。
- 预期利润必须来自向公平价值收敛，或确认反转后的右尾延伸。
- 必须定义止损、结构失效和时间失效。

策略不得在保留 RC-LSR 名称的同时变成突破、趋势追踪、动量、Carry 或截面排名策略。

### 7.2 因果本质

- Bar `t` 的决定只能使用时间戳不晚于 `t` 的数据。
- 收盘确认的入场或退出最早只能在 `t+1` 开盘成交。
- 盘中保护止损只能由 evaluator 的固定悲观碰撞规则处理。
- 信号生成禁止负 shift、center rolling、向后填充、倒序未来滚动、未来极值和未来标签。
- 截面指标必须来自可在次柱订单前获得的同时间戳原子快照。

### 7.3 禁止专门化

- 策略代码中禁止按品种名称分支或硬编码白名单。
- 禁止按日期分支。
- 禁止从密封盲测选择参数。
- 禁止降低手续费、滑点、延迟、保证金或风险假设。
- 禁止搜索随机种子挑选漂亮结果。

## 8. 每轮允许的修改

一个 Trial 只验证一个可证伪假设，并且只能有一个主要动作：

- `REMOVE`：删除无贡献或互相冲突的组件；
- `ADD`：添加一个具有经济机制的纯因果指标；
- `CHANGE`：改变标准化、状态转换、确认逻辑、长短非对称或受限退出政策；
- `TUNE`：机制稳定后，在小邻域内调参。

单轮预算：

- 最多新增一个因子族；
- 最多新增两个自由参数；
- 除格式化外，最多修改 40 行策略逻辑；
- 禁止新增依赖；
- 只能修改 `strategy.py`；
- `proposal.json` 中只能有一个核心假设。

超出预算的候选在回测前淘汰。

## 9. 无 API Key 的 Codex 调用

本机 Codex CLI 已安装，并已使用 ChatGPT 登录。V1 使用非交互模式：

```text
codex exec --json \
  --output-schema proposal.schema.json \
  --sandbox workspace-write \
  -o proposal.json \
  <task prompt>
```

Codex 官方非交互模式支持 JSONL 和 JSON Schema，并默认复用已保存的 CLI 登录。Controller 禁止读取、复制、打印或提交 `~/.codex/auth.json`，凭据优先存入系统 Keychain。

官方文档：

- https://learn.chatgpt.com/docs/non-interactive-mode
- https://learn.chatgpt.com/docs/auth

Gemini/Antigravity 以后只能作为 reviewer adapter。启用前必须验证其非交互输出、登录态复用、超时和结构化输出协议。

## 10. Agent 获得的研究诊断包

只提供开发区信息：

- 当前冠军源码和哈希；
- 策略宪法和修改预算；
- 五个 Walk-Forward 窗口指标；
- 分品种、分板块的收益、PF、期望、回撤和交易数；
- 多空分解、市场状态分解；
- 入场条件漏斗；
- 退出原因贡献；
- MFE/MAE、持仓时间分布；
- 成本占毛利比例；
- 1x/2x/3x 摩擦和延迟一根成交压力；
- 参数邻域和自动组件消融；
- 过去所有 Trial 的假设、diff、哈希和裁决。

严禁提供密封盲测的 Bars、日期、交易记录、分品种指标和详细失败原因。

## 11. proposal.json 契约

必须包含：

```text
trial_id
failure_mechanism
hypothesis
change_type
economic_rationale
expected_metric_effect
mean_reversion_invariants
falsification_test
rollback_condition
new_factors
new_parameters
removed_components
changed_files
complexity_delta
```

JSON Schema 拒绝缺失字段、未知动作、多文件修改或超预算声明。

有效假设示例：

```text
亏损集中于 Setup 后四根确认期内截面广度继续恶化的交易。
在 Trigger 时重新检查广度，应降低初始止损比例，且不降低赢家 MFE 中位数。
```

“优化策略”不构成有效假设。

## 12. 单轮协议

1. 校验 evaluator 和数据哈希；
2. 在开发清单上重跑当前冠军；
3. 生成研究诊断包；
4. 要求 Codex 返回一个结构化假设和一个候选补丁；
5. 拒绝重复 proposal、公式或策略哈希；
6. 检查文件白名单和复杂度预算；
7. 运行静态检查和策略宪法检查；
8. 运行信号契约和因果测试；
9. 运行开发区 Walk-Forward；
10. 运行消融、参数扰动、成交延迟和成本压力；
11. 同时对比初始基线与当前冠军；
12. 保存成功和失败的全部产物；
13. 只有确定性门禁通过才更新开发区冠军；
14. 下一轮只反馈开发区诊断。

AI 的解释文本不能覆盖确定性拒绝。

## 13. 失败诊断到修改动作

- 某组件在多数窗口为负贡献：优先 `REMOVE`，用反向消融确认。
- 亏损集中在特定状态：调整纯因果门禁或状态转换。
- 毛收益为正但成本吞噬：降低换手或提高确认强度，禁止调低成本。
- 入场后 MAE 很大才出现 MFE：改善入场时机或更早作废 Setup。
- MFE 高但实际利润低：调整受限退出政策。
- 机制稳定但略低于阈值：允许小邻域 `TUNE`。
- 找不到可解释的剩余失败机制：停止，不叠加新指标。

## 14. 数据切分与防过拟合

### 14.1 固定时间切分

- 最早 70%：开发池，AI 可看到诊断。
- 最新 30%：密封历史盲测。
- 时间戳写入 Campaign manifest 后永久固定。
- Purge/Embargo 不小于最大标签/持仓周期；RC-LSR 30m 最少 24 Bars。

### 14.2 开发区 Walk-Forward

70% 开发池使用五个扩展窗口的 Purged Walk-Forward。候选选择不得使用包含密封 30% 的全样本指标。

### 14.3 多重试验控制

- 所有被评估候选，包括崩溃和非法补丁，都记录并占用提案预算。
- 每个 Campaign 最多回测 24 个候选。
- 连续六个有效候选未改善 Pareto 前沿时停止。
- 保存公式、AST、策略、参数、Prompt 和结果哈希。
- 样本允许时计算 Deflated Sharpe 与 PBO。
- 对新增参数和代码复杂度惩罚。
- 禁止删除失败记录或重命名等价公式逃避计数。

### 14.4 密封盲测

- 打开盲测前只能选择一个冻结开发区冠军。
- 只运行一次。
- 详细结果不反馈 Codex。
- 失败即归档整个 Campaign。
- 同一盲测集不得用于另一轮优化。
- 新 Campaign 必须等待新增市场数据，或使用事先保留的另一份未触碰数据。

## 15. 开发区硬门禁

所有门禁必须同时通过。

### 因果与完整性

- 前缀不变性精确通过；
- 无禁止 AST 模式；
- evaluator/data hash 不变；
- 逐笔账本与资金曲线对账；
- 同柱碰撞使用冻结的悲观规则；
- 期末持仓正确结算。

### 样本量

- 开发验证交易合计至少 500 笔；
- 声称单品种有效时，该品种验证交易至少 20 笔；
- 禁止因零交易而“避免亏损”并晋级。

### 收益与风险

- 标准成本组合净收益 > 0；
- 组合 PF ≥ 1.20；
- 单笔期望中位数 > 0；
- 组合最大回撤 ≤ 10%；
- 任一 Walk-Forward 窗口回撤 ≤ 12%；
- 五个窗口至少四个净收益为正。

### 跨品种稳健性

- 固定 25 品种中至少 60% 盈利；
- 品种期望中位数为正；
- 主要商品板块不得出现灾难性总亏损；
- 多空分开报告，任一侧不得隐藏 Kill Switch。

### 摩擦和扰动

- 2x 摩擦仍盈利；
- 3x 摩擦 PF ≥ 0.90，且不触发回撤 Kill Switch；
- 成交延迟一根不能使组合转为大幅亏损；
- 预定义相邻参数组合至少 70% 盈利；
- 新增因子必须在消融中改善 Walk-Forward 中位表现。

### 复杂度和统计证据

- 策略逻辑复杂度最多比基线增加 20%，除非同时删除等量旧组件；
- 可计算时，Deflated Sharpe 置信概率 ≥ 95%；
- 可计算时，PBO ≤ 20%；
- 候选必须位于收益/回撤/成本/复杂度 Pareto 前沿。

禁止用一个不透明总分抵消硬门禁失败。总分只能在已经通过完整性检查的候选之间排序。

## 16. 盲测与 Shadow 晋级

冻结冠军在密封 30% 上必须满足：

- 标准成本净收益 > 0；
- PF ≥ 1.10；
- 最大回撤 ≤ 10%；
- 固定品种池至少 50% 盈利；
- 无未来函数、账本或信号一致性错误；
- 无 Kill Switch。

通过后状态从 `DEVELOPMENT_CHAMPION` 变为 `SHADOW`。

Shadow 虚拟盘中的策略继续冻结，至少运行 30 个自然日且完成 100 笔平仓，最长观察 180 天。必须记录实际模拟成交，而非假定收盘价。晋级 `PAPER_APPROVED` 需要：

- 实际模拟净收益 > 0；
- PF ≥ 1.10；
- 最大回撤 ≤ 10%；
- 研究实现与 Shadow 实现信号一致率 100%；
- 实际滑点在压力测试范围内；
- 无运行和风险 Kill Switch。

任何状态都不能自动连接真实资金账户。

## 17. 状态机

```text
BASELINE
  -> RESEARCHING
  -> DEVELOPMENT_CHAMPION
  -> SEALED_AUDIT
      -> CAMPAIGN_FAILED
      -> SHADOW
          -> SHADOW_FAILED
          -> PAPER_APPROVED

任意状态 -> SAFETY_STOP：evaluator/data hash 变化或因果违规。
```

## 18. 实验账本

使用独立 SQLite，不写入行情数据库。

### campaigns

- Campaign ID、策略 ID、基础 Commit、evaluator/data hash；
- 切分、宪法和门禁 hash；
- 开始/结束时间和终态。

### trials

- Trial 编号、Codex thread ID、模型、Prompt hash；
- 父策略和候选策略 hash；
- 假设和动作类型；
- 校验状态、淘汰原因、指标、耗时和 Token 使用；
- proposal、diff、测试输出和产物路径。

### champions

- Campaign ID、策略 hash、开发区指标；
- 密封盲测裁决和 Shadow 状态；
- 不可变产物 manifest。

失败记录必须永久可查询；删除失败 Trial 会破坏多重试验控制。

## 19. 自动故障处理

- Codex 超时或临时掉登录：重试一次，仍失败则暂停 Campaign。
- JSON/Schema 非法：允许一次格式修复，不进入回测。
- 越权文件变更：立即淘汰并丢弃工作区。
- 静态或因果失败：归档为 `INVALID_STRATEGY`，不回测。
- 候选导入、运行或资源超限：计为失败 Trial。
- evaluator/data hash 变化：整个 Campaign 进入 `SAFETY_STOP`。
- 重复策略/公式/参数 hash：跳过回测但记录提案。
- 连续六个有效候选未改善：停止。
- 24 个候选用尽：`NO_ROBUST_STRATEGY_FOUND`。
- 密封盲测失败：`CAMPAIGN_FAILED`，禁止针对该盲测继续优化。

## 20. 最小文件结构

```text
code/strategy_evolution_agent.py        Controller 与 Codex 调用
code/strategy_evolution_gate.py         确定性安全和晋级门禁
config/rc_lsr_constitution.json         策略宪法与阈值
schemas/strategy_proposal.schema.json   Codex 结构化输出契约
tests/test_strategy_evolution_agent.py  隔离、因果和状态测试
data/strategy_evolution.db              独立实验账本，不提交
data/evolution_runs/                    自动产物，不提交
```

修正后的 evaluator 作为单独的既有模块冻结。V1 不为尚未使用的模型供应商搭抽象框架；一个小型 Codex adapter 足够。

## 21. 验证方案

### 隔离攻击

- 候选试图修改 evaluator 时必须被拒绝；
- 候选不能读取 `.env` 或认证文件；
- evaluator/data hash 变化触发 `SAFETY_STOP`；
- 合法 diff 只能包含 `strategy.py`。

### 因果攻击

- 追加未来数据的前缀不变性；
- 修改未来 Bar 不影响历史信号；
- 同柱高低点冲突按悲观顺序；
- 当前收盘信号不能成交于当前开盘或收盘；
- 拦截负 shift、center rolling、bfill 和倒序未来窗口；
- 截面数据必须满足同时间戳可用性。

### 过拟合攻击

- 日期硬编码和品种白名单必须被拒绝；
- 等价候选不能逃避 Trial 预算；
- Controller 不能在看到结果后移动切分；
- 研究诊断包中不得出现盲测细节；
- 盲测失败后不能恢复同一 Campaign。

### 生命周期

- 基线 → 研究 → 开发冠军；
- 预算耗尽 → `NO_ROBUST_STRATEGY_FOUND`；
- 盲测通过 → `SHADOW`；
- 盲测失败 → 终态失败；
- Shadow 通过 → `PAPER_APPROVED`；
- 任意路径均不能触达真实交易账户。

### 端到端演练

先用故意较弱的合成均值回归策略和已知合法改进验证编排，再对 RC-LSR 运行极小的开发区 Trial 预算。在隔离测试全部通过前，不得打开 RC-LSR 密封盲测。

## 22. 实施阶段

1. 修正并冻结 evaluator 语义，增加 hash manifest 与一致性测试。
2. 定义 RC-LSR 策略宪法和候选策略契约。
3. 实现独立账本、Controller 和确定性门禁。
4. 接入 Codex `exec`、结构化输出和已登录账号复用。
5. 实现开发诊断包和最多 24 个候选的研究循环。
6. 实现一次性密封盲测和 Campaign 终态。
7. 对接既有虚拟/Shadow 基础设施，不提供真实账户凭据。
8. 完成隔离演练，再启动受限 RC-LSR Campaign。

## 23. 验收标准

- Codex 无需 API Key 即可提出并应用策略候选；
- AI 无法写入或影响 evaluator、数据、切分、成本和门禁；
- 未来函数和均值回归本质漂移被确定性拒绝；
- 每个 Trial，包括失败，都有完整记录；
- 循环能在成功、无进展、安全异常或预算耗尽时停止；
- 密封盲测只运行一次且从不回传；
- 只有盲测通过候选才能进入冻结的 Shadow 虚拟盘；
- 工作流在技术上无法触达真实资金账户。
