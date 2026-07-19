# v2.7 +1%/+2% 概率模型需求文档

## 1. 目标

v2.7 从“次日是否上涨”扩展到更贴近隔日T执行的收益目标概率：

- 触达低吸后达到 +1% 的概率。
- 触达低吸后达到 +2% 的概率。
- 触达低吸后触发 -2% 止损的概率。
- 概率收益风险比和最终概率信号。

模型只作为辅助排序和风险提示，不自动替代规则等级。

## 2. 输入

- SQLite：`data/dataset/trade_dataset.sqlite3`
- 样本表：`dataset_samples`
- 特征表：`feature_snapshot`
- 标签表：`label_snapshot`

核心标签：

- `hit_1pct_after_touch`
- `hit_2pct_after_touch`
- `stop_2pct_after_touch`

## 3. 模型设计

- 使用 LightGBM 二分类模型分别训练三个目标。
- 样本不足、标签单一或 LightGBM 不可用时，回退为正样本率基准模型。
- 训练/验证/测试切分沿用 v2.5 时间序列切分，不随机打乱。
- 特征工程沿用 v2.6 方向模型特征，并显式排除所有标签字段，避免未来函数。

## 4. 输出字段

预测结果输出到 `output/profit_probabilities_v2.7.csv` 和 SQLite 表 `profit_probability_predictions`。

字段：

- `hit_1pct_probability`
- `hit_2pct_probability`
- `stop_2pct_probability`
- `risk_adjusted_1pct = hit_1pct_probability - stop_2pct_probability`
- `risk_adjusted_2pct = hit_2pct_probability - stop_2pct_probability`
- `probability_risk_reward`
- `final_probability_signal`

概率信号：

- 进攻：+2% 概率较高且止损概率低。
- 偏多：+1% 概率较高且止损概率可控。
- 观察：概率没有明显优势。
- 风险优先：止损概率高于收益概率。
- 放弃：收益概率偏低且止损概率偏高。

## 5. 页面要求

保持 v2.6 页面结构不变，只在现有表格中增加收益目标概率字段：

- 明日计划：展示达到 1%、达到 2%、止损概率、概率收益风险比和概率信号。
- 固定持仓：展示持仓的收益目标概率和概率信号。
- 卖点、午盘、次日验证：并列展示方向概率与收益目标概率。
- 模型训练：新增「训练收益目标概率模型」按钮。
- 模型预测：新增「生成收益目标概率」按钮和 v2.7 概率排序表。

## 6. CLI

```bash
python main.py probability-train
python main.py probability-predict
python main.py probability-predict --stock-code 002466
```

## 7. 验收标准

- `python main.py probability-train` 可生成模型文件和评估报告。
- `python main.py probability-predict` 可生成收益目标概率排序。
- SQLite 中存在 `profit_probability_training_runs` 和 `profit_probability_predictions`。
- 页面可展示达到 1%、达到 2%、止损概率和概率收益风险比。
- 标签字段不会进入特征列。
- 样本不足时不阻断链路，退回基准概率模型。

## 8. 风险

- 日线 OHLC 无法完整判断高低点先后，路径顺序仍需分钟数据增强。
- 当前样本较少时，概率更像经验频率，不能直接作为加仓依据。
- 概率未校准前只用于排序，v2.8 再做校准和解释。
