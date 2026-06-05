# stock-quant-model

Quant Model Signal 后端模型，基于 XGBoost 多标签分类模型对 A 股、港股、美股历史行情数据进行分析，输出四种参考信号（正向/负向/强正向/强负向）。

> ⚠ 免责声明：本工具仅供学习研究使用。所有输出信号均为模型推断结果，仅供参考，不构成任何投资建议。投资有风险，入市需谨慎。

## 功能

- 支持 A 股（上海/深圳）、港股、美股
- 基于约 3 年历史数据的滚动回测分析
- 四种参考信号输出
- K 线图与信号时间线可视化

## 技术栈

- 模型：XGBoost 多标签分类
- 数据源：akshare、baostock
- 部署：Vercel Serverless

## 使用

访问 https://quant-ref-signal.vercel.app（假设已部署），输入股票代码即可查看分析结果。
