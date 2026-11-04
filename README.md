# 个人收支分析仪表盘

公开页面：<https://ddntp.github.io/personal-finance-dashboard/>

本项目把本地微信支付、支付宝和招商银行流水转成一个可分享的静态分析页面。页面发布按账户、转账对象、月份、年度、类别、收入来源和支付渠道聚合后的结果；不发布交易明细、商品、订单号、账号或银行卡尾号。

## 数据来源与口径

- 微信支付：6 份 Excel，2024-01-01 至 2026-11-03。
- 支付宝：3 份 GB18030 编码 CSV，2024-01-01 至 2026-11-03。
- 招商银行：1 份 296 页 PDF，2022-10-26 至 2026-10-31。
- “支付平台合计”只合并微信支付和支付宝；招商银行流水单独展示，避免银行快捷支付与支付平台账单重复记账。
- 有效消费排除转账、红包、投资理财和账户调拨；全额/部分退款会扣除，支付宝“不计收支”的退款会作为负向调整。
- 2026 年数据不是完整年度，页面会标明实际截止日期。
- 账户视图显示罗文培、胡国凤；往来对象卡片按账户拆分不同交易对方，可切换年度查看收入、支出、净流入和笔数。

## 本地生成

原始账单放在仓库根目录下的账户目录中，原始文件被 `.gitignore` 排除：

```bash
python3 -m pip install -r requirements.txt
python3 scripts/analyze.py
python3 -m unittest discover -s tests -v
python3 -m http.server 8000 --directory site
```

然后打开 <http://127.0.0.1:8000/>。分析脚本支持 `--input-dir` 和 `--output` 参数，便于在不改变仓库结构的情况下重新生成聚合 JSON。

## 目录

- `scripts/analyze.py`：微信、支付宝、招商银行解析、去重、分类和聚合。
- `tests/test_analyze.py`：退款、隐私字段、支付宝和银行文本解析测试。
- `site/`：无需构建工具的静态网页。
- `docs/superpowers/specs/`：数据口径和页面设计说明。
- `.github/workflows/pages.yml`：推送 `master` 后发布 GitHub Pages。

## 隐私边界

不要把原始账单文件加入 Git。公开仓库中的 `site/data/summary.json` 仅包含账户和转账对象聚合结果，不包含交易明细；如果需要撤销分享，应关闭 GitHub Pages 或将仓库改为私有。
