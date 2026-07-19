# v3.0 封板产品开发计划

更新日期：2026-07-19

## 1. 开发目标

v3.0 封板目标不是继续堆模型，而是把 v2.6-v2.9 已完成的方向概率、收益概率、校准结果和预测回顾，统一变成用户可直接使用的最终操作。

最终用户体验：

```text
生成明日计划 -> 看最终操作 -> 处理固定持仓 -> 记录真实交易 -> 次日复盘 -> 模型评分反哺
```

## 2. 五个 Commit 顺序

| 顺序 | Commit | 目标 | 主要输出 | 验收命令 |
|---:|---|---|---|---|
| 1 | `feat: add v3.0 decision fusion engine` | 生成融合评分和最终操作 | `decision_fusion.py`、`final_decision_v3`、`output/final_decision_v3.0.csv` | `python main.py decision-fusion` |
| 2 | `feat: integrate final decision into trade plan` | 交易计划和固定持仓展示最终操作 | `output/final_decision_v3.0.md`、页面最终操作列 | `streamlit` 页面验收 |
| 3 | `feat: add single stock decision workspace` | 支持单票查询，不覆盖全量预测 | 单票查询区、临时单票输出 | 查询 `002466` |
| 4 | `feat: improve intraday path and range review` | 补齐路径和区间复盘 | 路径标签、区间覆盖率、区间重合度 | `python main.py prediction-review` |
| 5 | `chore: seal v3.0 workflow and quality gates` | 封板文档、质量门禁、验收流 | README、工作流、质量提示 | `python -m unittest discover -s tests` |

## 3. Commit 1：融合决策引擎

### 开发内容

- 新增融合评分字段：
  - `rule_score`
  - `model_score`
  - `risk_score`
  - `sector_score`
  - `market_score`
  - `fusion_score`
- 新增最终操作：
  - 优先低吸。
  - 小仓观察。
  - 只观察。
  - 放弃。
  - 继续持有。
  - 减仓。
  - 止盈。
  - 清仓。
  - 止损。
- 新增 SQLite 表：`final_decision_v3`。
- 已接入 CLI：`python main.py decision-fusion`。

### 验收标准

- D 级不被模型概率强行拉成买入。
- 板块回避不输出优先低吸。
- 情绪冰点时自动降低激进操作。
- 输出有操作解释。

## 4. Commit 2：交易计划接入最终操作

### 开发内容

- 明日计划接入 `final_decision_v3.0.csv`。
- 固定持仓接入最终操作。
- 页面明日计划和固定持仓表新增：
  - 融合评分。
  - 最终操作。
  - 操作解释。
  - 模型依据。
  - 风控理由。
- 已实现：`report_generator.py` 自动刷新融合决策并写入 `daily_plan.md`。
- 已实现：`app.py` 明日计划和固定持仓表展示最终操作、融合评分、操作解释。

### 验收标准

- 用户一眼能看到明天最值得盯的 1-3 只。
- 固定持仓五只票都有处理建议。
- 规则依据和模型依据并列展示。

## 5. Commit 3：单票工作台

### 开发内容

- 页面增加股票代码/名称输入。
- 单票查询读取已有全量预测，不覆盖全量文件。
- 必要时生成单票临时输出：
  - `output/single_stock_decision.csv`
  - 或 SQLite 临时查询表。
- 单票结果一屏展示：
  - 规则等级。
  - 最终操作。
  - 次日上涨概率。
  - +1% / +2% / 止损概率。
  - 板块状态。
  - 卖点信号。
  - 历史回顾。
- 已实现：新增 `single_stock_decision.py`，单票查询读取现有全量结果，不覆盖全市场预测文件。
- 已实现：页面新增 `单票决策` Tab，支持固定持仓快捷选择和股票代码输入。

### 验收标准

- 查询 `002466` 可看到天齐锂业完整决策链。
- 查询后 `output/model_predictions_v2.6.csv` 不被覆盖成单票。
- 查询固定持仓时能看到持仓处理建议。

## 6. Commit 4：路径标签与区间回顾

### 开发内容

- 优先用分钟数据判断事件先后。
- 新增路径标签：
  - 先涨后跌。
  - 先跌后涨。
  - 冲高回落。
  - 探底回升。
  - 横盘震荡。
- 新增区间指标：
  - 计划区间覆盖率。
  - 真实区间重合度。
  - 低吸区间可成交标记。
- 已实现：预测回顾明细新增路径标签、计划区间、区间覆盖率、区间重合度和低吸可成交标记。
- 已实现：模型评分卡新增 `range_coverage_rate`、`range_overlap_rate`、`buy_range_executable_rate`、`intraday_path_distribution`。
- v2.9 评分卡新增路径和区间评分。

### 验收标准

- 有分钟数据时能判断先触发收益还是先触发止损。
- 无分钟数据时显示不可判断。
- 不用日线 OHLC 伪造路径顺序。

## 7. Commit 5：封板体验与质量门禁

### 开发内容

- 更新 README 和 Obsidian 知识库。
- 增加 v3.0 验收命令清单。
- 页面增加数据质量提示：
  - 样本不足。
  - 预测缺失。
  - 校准缺失。
  - 回顾缺失。
- 增加最小测试覆盖。

### 验收标准

- `python main.py --help` 能看到 v3.0 命令。
- `python main.py decision-fusion` 能单独运行。
- `python -m unittest discover -s tests` 通过。
- 页面能完成完整工作流。

## 8. 封板后再考虑

- 真正 SHAP。
- 更复杂概率校准。
- 个性化交易模型。
- 多设备同步。
- 自动下单。
