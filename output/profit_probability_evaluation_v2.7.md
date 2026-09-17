# v2.7 +1%/+2% 概率模型评估报告

生成时间：2026-08-25 10:40:42
模型版本：`v2.7-profit-probability-001`
模型文件：`data/models/profit_probability_model_v2.7.pkl`

## 一、总体指标

| 目标 | 数据集 | 样本数 | 正样本率 | AUC | PR-AUC | Brier | 准确率 | 算法 |
|---|---|---:|---:|---:|---:|---:|---:|---|
| 触达后达到+1% | train | 25 | 40.00% | - | - | - | - | `baseline_probability` |
| 触达后达到+1% | validation | 0 | 0.00% | - | - | - | - | `baseline_probability` |
| 触达后达到+1% | test | 0 | 0.00% | - | - | - | - | `baseline_probability` |
| 触达后达到+2% | train | 25 | 8.00% | - | - | - | - | `baseline_probability` |
| 触达后达到+2% | validation | 0 | 0.00% | - | - | - | - | `baseline_probability` |
| 触达后达到+2% | test | 0 | 0.00% | - | - | - | - | `baseline_probability` |
| 触达后触发-2%止损 | train | 25 | 20.00% | - | - | - | - | `baseline_probability` |
| 触达后触发-2%止损 | validation | 0 | 0.00% | - | - | - | - | `baseline_probability` |
| 触达后触发-2%止损 | test | 0 | 0.00% | - | - | - | - | `baseline_probability` |

## 二、测试集分市场表现

### 触达后达到+1%

暂无可统计数据。

### 触达后达到+2%

暂无可统计数据。

### 触达后触发-2%止损

暂无可统计数据。

## 三、使用说明

- v2.7 概率只辅助隔日T收益目标判断，不自动替代规则等级。
- `risk_adjusted_1pct = 达到+1%概率 - 触发止损概率`。
- `probability_risk_reward` 用概率期望收益除以概率期望亏损，数值越高代表概率收益风险比越好。
- 样本不足或标签单一时自动退回基准概率模型，保证预测链路不断。
