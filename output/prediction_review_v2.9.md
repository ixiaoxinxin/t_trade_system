# v2.9 预测回顾与模型评分报告

生成时间：2026-07-19 23:23:54
回顾版本：`v2.9-prediction-review-001`

## 一、总体回顾

- 回顾样本数：18
- 方向命中率：0.8333
- +1% 实际发生率：77.78%
- +2% 实际发生率：55.56%
- 止损实际发生率：22.22%
- 低吸区间可成交率：77.78%
- 平均区间覆盖率：44.53%
- 平均区间重合度：35.82%

## 二、模型评分

| 模型版本 | 指标 | 分组 | 分组值 | 样本数 | 分数 |
|---|---|---|---|---:|---:|
| v2.6-direction-001 | direction_hit_rate | all | all | 18 | 0.8333 |
| v2.9-prediction-review-001 | range_coverage_rate | all | all | 18 | 0.4453 |
| v2.9-prediction-review-001 | range_overlap_rate | all | all | 18 | 0.3582 |
| v2.9-prediction-review-001 | buy_range_executable_rate | all | all | 18 | 0.7778 |
| v2.7-profit-probability-001 | hit_1pct_brier | all | all | 18 | 0.1921 |
| v2.7-profit-probability-001 | hit_2pct_brier | all | all | 18 | 0.3241 |
| v2.7-profit-probability-001 | stop_2pct_brier | all | all | 18 | 0.1759 |
| v2.8-calibration-explain-001 | calibrated_hit_1pct_brier | all | all | 18 | 0.1728 |
| v2.8-calibration-explain-001 | calibrated_hit_2pct_brier | all | all | 18 | 0.2469 |
| v2.8-calibration-explain-001 | calibrated_stop_2pct_brier | all | all | 18 | 0.1728 |
| v2.6-direction-001 | direction_hit_rate | market | 情绪冰点 | 18 | 0.8333 |
| v2.7-profit-probability-001 | hit_1pct_actual_rate | market | 情绪冰点 | 18 | 0.7778 |
| v2.6-direction-001 | direction_hit_rate | sector | 未标记 | 5 | 1.0000 |
| v2.7-profit-probability-001 | hit_1pct_actual_rate | sector | 未标记 | 5 | 1.0000 |
| v2.6-direction-001 | direction_hit_rate | sector | IT服务Ⅲ | 1 | 1.0000 |
| v2.7-profit-probability-001 | hit_1pct_actual_rate | sector | IT服务Ⅲ | 1 | 1.0000 |
| v2.6-direction-001 | direction_hit_rate | sector | 保险Ⅱ | 1 | 1.0000 |
| v2.7-profit-probability-001 | hit_1pct_actual_rate | sector | 保险Ⅱ | 1 | 1.0000 |
| v2.6-direction-001 | direction_hit_rate | sector | 养殖业 | 1 | 1.0000 |
| v2.7-profit-probability-001 | hit_1pct_actual_rate | sector | 养殖业 | 1 | 1.0000 |
| v2.6-direction-001 | direction_hit_rate | sector | 农化制品 | 1 | 1.0000 |
| v2.7-profit-probability-001 | hit_1pct_actual_rate | sector | 农化制品 | 1 | 1.0000 |
| v2.6-direction-001 | direction_hit_rate | sector | 氟化工 | 1 | 1.0000 |
| v2.7-profit-probability-001 | hit_1pct_actual_rate | sector | 氟化工 | 1 | 0.0000 |
| v2.6-direction-001 | direction_hit_rate | sector | 软件开发 | 1 | 1.0000 |
| v2.7-profit-probability-001 | hit_1pct_actual_rate | sector | 软件开发 | 1 | 1.0000 |
| v2.6-direction-001 | direction_hit_rate | sector | 通信 | 4 | 0.5000 |
| v2.7-profit-probability-001 | hit_1pct_actual_rate | sector | 通信 | 4 | 0.5000 |
| v2.6-direction-001 | direction_hit_rate | sector | 铜 | 1 | 0.0000 |
| v2.7-profit-probability-001 | hit_1pct_actual_rate | sector | 铜 | 1 | 0.0000 |
| v2.6-direction-001 | direction_hit_rate | sector | 食品饮料 | 1 | 1.0000 |
| v2.7-profit-probability-001 | hit_1pct_actual_rate | sector | 食品饮料 | 1 | 1.0000 |
| v2.6-direction-001 | direction_hit_rate | sector | 饲料 | 1 | 1.0000 |
| v2.7-profit-probability-001 | hit_1pct_actual_rate | sector | 饲料 | 1 | 1.0000 |
| v2.7-profit-probability-001 | hit_1pct_actual_rate_by_bucket | probability_bucket | 80-100% | 18 | 0.7778 |
| v2.7-profit-probability-001 | hit_2pct_actual_rate_by_bucket | probability_bucket | 80-100% | 18 | 0.5556 |
| v2.7-profit-probability-001 | stop_2pct_actual_rate_by_bucket | probability_bucket | 0-20% | 18 | 0.2222 |
| v2.9-prediction-review-001 | intraday_path_distribution | path | 冲高回落再转强型 | 1 | 0.0556 |
| v2.9-prediction-review-001 | intraday_path_distribution | path | 固定持仓 | 5 | 0.2778 |
| v2.9-prediction-review-001 | intraday_path_distribution | path | 弱势收盘型 | 3 | 0.1667 |
| v2.9-prediction-review-001 | intraday_path_distribution | path | 强势横盘型 | 1 | 0.0556 |
| v2.9-prediction-review-001 | intraday_path_distribution | path | 急跌修复失败型 | 5 | 0.2778 |
| v2.9-prediction-review-001 | intraday_path_distribution | path | 普通震荡型 | 2 | 0.1111 |
| v2.9-prediction-review-001 | intraday_path_distribution | path | 高波动震荡型 | 1 | 0.0556 |

## 三、路径标签分布

| 路径标签 | 样本数 | 占比 |
|---|---:|---:|
| 冲高回落再转强型 | 1 | 5.56% |
| 固定持仓 | 5 | 27.78% |
| 弱势收盘型 | 3 | 16.67% |
| 强势横盘型 | 1 | 5.56% |
| 急跌修复失败型 | 5 | 27.78% |
| 普通震荡型 | 2 | 11.11% |
| 高波动震荡型 | 1 | 5.56% |

## 四、说明

- v2.9 负责回顾和评分，不训练新模型。
- 方向模型用方向命中率评分；概率模型用 Brier Score 和概率桶实际发生率评分。
- 路径和区间回顾先使用标签表中的 `first_event`、次日高低幅和可成交标记；有分钟事件序列时再升级为精确先后判断。
- 样本少时分行业/分市场指标只做观察，不能作为稳定结论。
- 后续 v3.0 将读取本评分结果，辅助规则评分和模型概率融合。
