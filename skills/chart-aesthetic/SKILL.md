---
name: chart-aesthetic
description: 图表表达优化——让回答里的图表选型与轴字段命名更适合汇报场景
---

你在生成回答时，额外遵循以下图表表达规范：

1. chart_type 选择以"汇报一眼懂"为准：
   - 分类对比（如各区域销售额）→ response_bar_chart
   - 时间趋势（如按月变化）→ response_line_chart
   - 构成占比（部分占总体的比例，类别 ≤ 6 个）→ response_pie_chart
   - 两数值变量的相关性 → response_scatter_chart
   - 单值/明细列表 → response_table，不要强行画图
2. 聚合列的 AS 别名用业务化中文措辞（如 total_amount AS 销售总额），不要输出 cnt、sum_1 这类工程命名。
3. 分类轴的值如有多语言或大小写不一致，先用规范写法聚合（如 UPPER/TRIM）再分组，避免同类分裂成多段。
4. 结果行数超过 20 行时优先做 Top N + "其他"归并，图表可读性优先于完整性。
