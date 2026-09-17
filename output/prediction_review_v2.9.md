# v2.9 预测回顾与模型评分报告

生成时间：2026-08-25 10:41:20
回顾版本：`v2.9-prediction-review-001`

## 一、总体回顾

- 回顾样本数：49
- 方向命中率：-
- +1% 实际发生率：40.00%
- +2% 实际发生率：8.00%
- 止损实际发生率：20.00%
- 低吸区间可成交率：30.61%
- 平均区间覆盖率：12.95%
- 平均区间重合度：12.64%

## 二、模型评分

| 模型版本 | 指标 | 分组 | 分组值 | 样本数 | 分数 |
|---|---|---|---|---:|---:|
| v2.6-direction-001 | direction_hit_rate | all | all | 49 | nan |
| v2.9-prediction-review-001 | range_coverage_rate | all | all | 49 | 0.1295 |
| v2.9-prediction-review-001 | range_overlap_rate | all | all | 49 | 0.1264 |
| v2.9-prediction-review-001 | buy_range_executable_rate | all | all | 49 | 0.3061 |
| v2.7-profit-probability-001 | hit_1pct_brier | all | all | 49 | nan |
| v2.7-profit-probability-001 | hit_2pct_brier | all | all | 49 | nan |
| v2.7-profit-probability-001 | stop_2pct_brier | all | all | 49 | nan |
| v2.8-calibration-explain-001 | calibrated_hit_1pct_brier | all | all | 49 | nan |
| v2.8-calibration-explain-001 | calibrated_hit_2pct_brier | all | all | 49 | nan |
| v2.8-calibration-explain-001 | calibrated_stop_2pct_brier | all | all | 49 | nan |
| v2.6-direction-001 | direction_hit_rate | market | 未标记 | 25 | nan |
| v2.7-profit-probability-001 | hit_1pct_actual_rate | market | 未标记 | 25 | 0.4000 |
| v2.6-direction-001 | direction_hit_rate | market | 偏弱 | 24 | nan |
| v2.7-profit-probability-001 | hit_1pct_actual_rate | market | 偏弱 | 24 | nan |
| v2.6-direction-001 | direction_hit_rate | sector | 未标记 | 29 | nan |
| v2.7-profit-probability-001 | hit_1pct_actual_rate | sector | 未标记 | 29 | 0.4000 |
| v2.6-direction-001 | direction_hit_rate | sector | 光伏设备 | 1 | nan |
| v2.7-profit-probability-001 | hit_1pct_actual_rate | sector | 光伏设备 | 1 | nan |
| v2.6-direction-001 | direction_hit_rate | sector | 其他电子Ⅲ | 1 | nan |
| v2.7-profit-probability-001 | hit_1pct_actual_rate | sector | 其他电子Ⅲ | 1 | nan |
| v2.6-direction-001 | direction_hit_rate | sector | 分立器件 | 1 | nan |
| v2.7-profit-probability-001 | hit_1pct_actual_rate | sector | 分立器件 | 1 | nan |
| v2.6-direction-001 | direction_hit_rate | sector | 半导体 | 2 | nan |
| v2.7-profit-probability-001 | hit_1pct_actual_rate | sector | 半导体 | 2 | nan |
| v2.6-direction-001 | direction_hit_rate | sector | 无机盐 | 1 | nan |
| v2.7-profit-probability-001 | hit_1pct_actual_rate | sector | 无机盐 | 1 | nan |
| v2.6-direction-001 | direction_hit_rate | sector | 机床工具 | 1 | nan |
| v2.7-profit-probability-001 | hit_1pct_actual_rate | sector | 机床工具 | 1 | nan |
| v2.6-direction-001 | direction_hit_rate | sector | 汽车电子电气系统 | 1 | nan |
| v2.7-profit-probability-001 | hit_1pct_actual_rate | sector | 汽车电子电气系统 | 1 | nan |
| v2.6-direction-001 | direction_hit_rate | sector | 消费电子 | 2 | nan |
| v2.7-profit-probability-001 | hit_1pct_actual_rate | sector | 消费电子 | 2 | nan |
| v2.6-direction-001 | direction_hit_rate | sector | 电池化学品 | 1 | nan |
| v2.7-profit-probability-001 | hit_1pct_actual_rate | sector | 电池化学品 | 1 | nan |
| v2.6-direction-001 | direction_hit_rate | sector | 能源金属 | 2 | nan |
| v2.7-profit-probability-001 | hit_1pct_actual_rate | sector | 能源金属 | 2 | nan |
| v2.6-direction-001 | direction_hit_rate | sector | 诊断服务 | 1 | nan |
| v2.7-profit-probability-001 | hit_1pct_actual_rate | sector | 诊断服务 | 1 | nan |
| v2.6-direction-001 | direction_hit_rate | sector | 贵金属 | 1 | nan |
| v2.7-profit-probability-001 | hit_1pct_actual_rate | sector | 贵金属 | 1 | nan |
| v2.6-direction-001 | direction_hit_rate | sector | 通信 | 3 | nan |
| v2.7-profit-probability-001 | hit_1pct_actual_rate | sector | 通信 | 3 | nan |
| v2.6-direction-001 | direction_hit_rate | sector | 钨 | 1 | nan |
| v2.7-profit-probability-001 | hit_1pct_actual_rate | sector | 钨 | 1 | nan |
| v2.6-direction-001 | direction_hit_rate | sector | 铅锌 | 1 | nan |
| v2.7-profit-probability-001 | hit_1pct_actual_rate | sector | 铅锌 | 1 | nan |
| v2.7-profit-probability-001 | hit_1pct_actual_rate_by_bucket | probability_bucket | 0-20% | 49 | 0.4000 |
| v2.7-profit-probability-001 | hit_2pct_actual_rate_by_bucket | probability_bucket | 0-20% | 49 | 0.0800 |
| v2.7-profit-probability-001 | stop_2pct_actual_rate_by_bucket | probability_bucket | 0-20% | 49 | 0.2000 |
| v2.9-prediction-review-001 | intraday_path_distribution | path | 固定持仓 | 5 | 0.1020 |
| v2.9-prediction-review-001 | intraday_path_distribution | path | 弱势收盘型 | 9 | 0.1837 |
| v2.9-prediction-review-001 | intraday_path_distribution | path | 强势横盘型 | 2 | 0.0408 |
| v2.9-prediction-review-001 | intraday_path_distribution | path | 急跌修复失败型 | 3 | 0.0612 |
| v2.9-prediction-review-001 | intraday_path_distribution | path | 急跌修复成功型 | 1 | 0.0204 |
| v2.9-prediction-review-001 | intraday_path_distribution | path | 未触达低吸 | 24 | 0.4898 |
| v2.9-prediction-review-001 | intraday_path_distribution | path | 高波动震荡型 | 5 | 0.1020 |

## 三、路径标签分布

| 路径标签 | 样本数 | 占比 |
|---|---:|---:|
| 固定持仓 | 5 | 10.20% |
| 弱势收盘型 | 9 | 18.37% |
| 强势横盘型 | 2 | 4.08% |
| 急跌修复失败型 | 3 | 6.12% |
| 急跌修复成功型 | 1 | 2.04% |
| 未触达低吸 | 24 | 48.98% |
| 高波动震荡型 | 5 | 10.20% |

## 四、说明

- v2.9 负责回顾和评分，不训练新模型。
- 方向模型用方向命中率评分；概率模型用 Brier Score 和概率桶实际发生率评分。
- 路径和区间回顾先使用标签表中的 `first_event`、次日高低幅和可成交标记；有分钟事件序列时再升级为精确先后判断。
- 样本少时分行业/分市场指标只做观察，不能作为稳定结论。
- 后续 v3.0 将读取本评分结果，辅助规则评分和模型概率融合。
