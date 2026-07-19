# A股隔日T选股系统

本项目是一个本地运行的 A股隔日T选股、交易计划、卖点信号和复盘辅助系统。系统只做规则化辅助分析，不自动下单，不构成投资建议。

## 安装

建议使用 Python 3.10+。

```bash
pip install -r requirements.txt
```

## 配置

核心参数在 `config.yaml`：

- `capital`：总资金、单票资金、最大交易数量。
- `stock_filter`：价格、成交额、振幅、涨幅、MA5偏离过滤。
- `score_weight`：日线评分和尾盘评分权重。
- `tail_confirm`：尾盘确认阈值。
- `risk`：风险扣分阈值。
- `runtime`：缓存和候选扫描数量。
- `dataset`：SQLite 样本库位置、CSV 导出目录、切分目录。
- `llm_labeling`：大模型辅助标签开关、国产供应商优先级、成本上限和 API Key 环境变量。

PushPlus token 当前沿用既有代码逻辑，可通过环境变量 `PUSHPLUS_TOKEN` 覆盖。

## 命令行运行

查看帮助：

```bash
python main.py --help
```

生成明日计划：

```bash
python main.py pipeline
```

快速测试候选扫描：

```bash
python main.py candidates --max-count 20
```

单模块运行：

```bash
python main.py market
python main.py candidates
python main.py tail
python main.py plan
python main.py lunch
python main.py sell
python main.py next-day
python main.py review
python main.py factor-rank
python main.py dataset
python main.py holdings-refresh
python main.py model-train
python main.py model-predict
python main.py model-predict --stock-code 002466
python main.py probability-train
python main.py probability-predict
python main.py calibrate-explain
python main.py prediction-review
python main.py decision-fusion
python main.py single-stock --stock-code 002466
python main.py migrate-db
python main.py labels
python main.py split
python main.py quality
```

每次通过 `main.py` 运行后，会生成：

```text
output/run_manifest.json
```

用于追踪本次运行的步骤、输出文件和失败原因。

## 本地前端

```bash
streamlit run app.py
```

前端按真实工作流分为「明日计划」「固定持仓」「单票决策」「交易记录」「午盘验证」「模型训练」「模型预测」。日常入口是生成明日计划、更新卖点信号、午盘验证、次日复盘和保存训练数据。使用时优先看最终操作，再进入单票决策看依据。

## 主要输出

- `output/market_environment.csv`
- `output/market_environment.md`
- `output/market_environment.json`
- `output/overnight_t_candidates.csv`
- `output/final_watchlist.csv`
- `output/final_watchlist.md`
- `output/daily_plan.md`
- `output/lunch_review.csv`
- `output/lunch_review.md`
- `output/sell_signal.csv`
- `output/sell_signal.md`
- `output/next_day_review.csv`
- `output/next_day_review.md`
- `output/factor_performance.csv`
- `output/run_manifest.json`
- `data/dataset/trade_dataset.sqlite3`
- `data/dataset/splits/latest.json`
- `output/dataset_quality_report.md`
- `data/models/direction_model_v2.6.joblib`
- `output/model_evaluation_v2.6.md`
- `output/model_predictions_v2.6.csv`
- `output/label_review_queue.md`
- `output/profit_probabilities_v2.7.csv`
- `output/calibrated_probabilities_v2.8.csv`
- `output/model_explanations_v2.8.csv`
- `output/prediction_review_v2.9.csv`
- `output/model_scorecard_v2.9.csv`
- `output/final_decision_v3.0.csv`
- `output/final_decision_v3.0.md`
- `output/single_stock_decision.csv`
- `output/single_stock_decision.md`

v2.5 起，SQLite 是页面和训练数据的主存储。旧 CSV/Markdown/JSON 文件只作为兼容导入或过渡导出，页面读取优先走 `data/dataset/trade_dataset.sqlite3`。

## 方向模型

方向模型使用 LightGBM 训练次日涨跌方向分类模型，主标签为 `direction_up_close`，即次日收盘是否上涨。模型输出次日上涨概率和方向置信度，只用于辅助排序，不自动替代规则等级。

如果所有股票的次日上涨概率或方向置信度都一样，说明当前模型可能处在基准概率状态，通常是样本太少、标签分布单一或特征还不能区分个股。此时应优先看最终操作、规则等级和卖点信号。

固定持仓样本池包含融捷股份、云天化、大为股份、神火股份、天齐锂业；这些股票会在卖点信号、午盘验证和次日复盘中置顶。行情缺失时显示待刷新，不写入有效训练标签。

## 收益目标概率

收益目标概率模型输出 +1%、+2%、-2% 止损概率：

```bash
python main.py probability-train
python main.py probability-predict
```

输出文件为 `output/profit_probability_evaluation_v2.7.md` 和 `output/profit_probabilities_v2.7.csv`，SQLite 表为 `profit_probability_training_runs` 和 `profit_probability_predictions`。

## 概率校准与解释

```bash
python main.py calibrate-explain
```

输出校准报告、校准后概率和单票多空因素：`output/probability_calibration_v2.8.md`、`output/calibrated_probabilities_v2.8.csv`、`output/model_explanations_v2.8.csv`。

## 预测回顾与模型评分

```bash
python main.py prediction-review
```

输出预测回顾、模型评分卡和回顾报告：`output/prediction_review_v2.9.csv`、`output/model_scorecard_v2.9.csv`、`output/prediction_review_v2.9.md`。

当前已增强路径和区间回顾：预测回顾会输出 `intraday_path_label`、`range_coverage_rate`、`range_overlap_rate`、`buy_range_executable`，用于判断计划区间是否覆盖真实走势、低吸区间是否可成交。

## 融合决策与单票工作台

生成最终操作：

```bash
python main.py decision-fusion
```

输出 `output/final_decision_v3.0.csv` 和 `output/final_decision_v3.0.md`。融合层会把规则等级、方向概率、+1%/+2%概率、止损概率、板块状态、市场环境和模型评分合成最终操作。

查看单票：

```bash
python main.py single-stock --stock-code 002466
```

输出 `output/single_stock_decision.csv` 和 `output/single_stock_decision.md`。单票工作台只读取现有全量结果，不覆盖全市场预测文件。

## 常见问题

### 行情接口失败怎么办？

本系统依赖新浪、腾讯、东方财富/AKShare 等公开数据接口。网络异常、接口限流、字段变化都可能导致失败。建议先用：

```bash
python main.py candidates --max-count 5
```

做小规模验证。

### 为什么不再输出轻量板块/热点标签？

当前已去掉轻量板块识别功能，避免基于股票名称的弱规则误导交易计划。后续如需恢复，应接入更可靠的行业/概念映射。

### 为什么次日验证结果更细了？

当前不再只看“次日最高达到 1% 且未触发 -2%”，而是先判断是否触达计划低吸区间，再区分给买点成功、给买点失败、未给买点、风险触发和数据不足。

### 数据集为什么用 SQLite？

v2.5 默认用 SQLite：免费、轻量、无需启动服务，数据库文件位于 `data/dataset/trade_dataset.sqlite3`。页面输出、报告文档、真实交易记录、日线缓存和分钟缓存都会迁入 SQLite。后续样本量变大后，可从 SQLite 迁移到 DuckDB 或 PostgreSQL。
