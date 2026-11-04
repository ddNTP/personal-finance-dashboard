import json
import tempfile
import unittest
from pathlib import Path

import pandas as pd

from scripts.analyze import build_summary


class AnalyzeSummaryTest(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        account = self.root / "本地账户"
        account.mkdir()
        rows = [["微信支付账单明细"]] + [[None] for _ in range(16)]
        rows.append([
            "交易时间", "交易类型", "交易对方", "商品", "收/支", "金额(元)",
            "支付方式", "当前状态", "交易单号", "商户单号", "备注",
        ])
        rows.extend([
            ["2026-01-01 09:00:00", "转账", "收款方", "转账备注", "收入", 100, "零钱", "已收钱", "id-1", "/", "/"],
            ["2026-01-02 12:00:00", "商户消费", "餐厅", "午餐", "支出", 100, "零钱", "支付成功", "id-2", "/", "/"],
            ["2026-01-03 12:00:00", "商户消费", "商店", "商品", "支出", 80, "零钱", "已退款(¥20.00)", "id-3", "/", "/"],
            ["2026-01-04 12:00:00", "商店-退款", "商店", "商品", "收入", 20, "零钱", "已退款¥20.00", "id-4", "/", "/"],
            ["2026-01-05 12:00:00", "零钱提现", "本人", "提现", "/", 50, "零钱", "提现已到账", "id-5", "/", "/"],
        ])
        frame = pd.DataFrame(rows)
        frame.to_excel(account / "账单.xlsx", header=False, index=False)

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_refunds_reduce_effective_consumption_and_are_separate_income(self):
        summary = build_summary(self.root)
        view = summary["views"]["combined"]
        metrics = view["metrics"]
        self.assertEqual(summary["meta"]["record_count"], 5)
        self.assertEqual(metrics["gross_income"], 120.0)
        self.assertEqual(metrics["gross_expense"], 180.0)
        self.assertEqual(metrics["gross_neutral"], 50.0)
        self.assertEqual(metrics["consumption"], 160.0)
        self.assertEqual(metrics["refunds"], 20.0)
        self.assertEqual(metrics["net_cashflow"], -60.0)
        self.assertEqual(view["categories"][0]["label"], "餐饮")

    def test_public_summary_does_not_contain_raw_identifiers(self):
        summary = build_summary(self.root)
        encoded = json.dumps(summary, ensure_ascii=False)
        for forbidden in ("交易单号", "商户单号", "微信昵称"):
            self.assertNotIn(forbidden, encoded)
        self.assertIn("本地账户", encoded)
        self.assertIn("counterparties", encoded)
        self.assertIn(summary["meta"]["accounts"][0]["label"], {"本地账户"})


if __name__ == "__main__":
    unittest.main()

class AdditionalSourcesTest(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        account = self.root / "本地账户"
        account.mkdir()
        rows = [["微信支付账单明细"]] + [[None] for _ in range(16)]
        rows.append(["交易时间", "交易类型", "交易对方", "商品", "收/支", "金额(元)", "支付方式", "当前状态", "交易单号", "商户单号", "备注"])
        rows.append(["2026-01-01 09:00:00", "商户消费", "餐厅", "午餐", "支出", 10, "零钱", "支付成功", "wx-1", "/", "/"])
        pd.DataFrame(rows).to_excel(account / "微信.xlsx", header=False, index=False)
        csv_text = "\n".join([
            "支付宝账单",
            "共1笔记录",
            "交易时间,交易分类,交易对方,对方账号,商品说明,收/支,金额,收/付款方式,交易状态,交易订单号,商家订单号,备注,",
            "2026-01-02 12:00:00,餐饮美食,食堂,/,午餐,支出,20.00,花呗,交易成功,ali-1,merchant-1,,",
        ])
        (account / "支付宝.csv").write_bytes(csv_text.encode("gb18030"))

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_alipay_source_is_loaded_without_publishing_raw_csv_fields(self):
        summary = build_summary(self.root)
        self.assertIn("alipay", summary["views"])
        self.assertEqual(summary["views"]["alipay"]["metrics"]["gross_expense"], 20.0)
        encoded = json.dumps(summary, ensure_ascii=False)
        self.assertNotIn("merchant-1", encoded)
        self.assertNotIn("交易订单号", encoded)

    def test_neutral_alipay_refund_reduces_effective_consumption_total(self):
        csv_path = self.root / "本地账户" / "支付宝.csv"
        with csv_path.open("ab") as handle:
            handle.write("\n2026-01-03 12:00:00,退款,商户,/,退款,不计收支,10.00,花呗,退款成功,ali-refund,merchant-refund,,\n".encode("gb18030"))
        summary = build_summary(self.root)
        self.assertEqual(summary["views"]["alipay"]["metrics"]["consumption"], 10.0)
        self.assertEqual(summary["views"]["alipay"]["metrics"]["refunds"], 10.0)

    def test_bank_text_parser_keeps_bank_as_separate_source(self):
        from scripts.analyze import parse_cmb_text

        text = """记账日期 货币 交易金额 联机余额 交易摘要 对手信息
2026-01-02 CNY -20.00 980.00 快捷支付 食堂
2026-01-03 CNY 100.00 1080.00 代发工资 公司
2026-01-04 CNY 12.00 1092.00 快捷退款 商户
"""
        frame = parse_cmb_text(text, "test.pdf", page_number=1)
        self.assertEqual(len(frame), 3)
        self.assertEqual(frame["收/支"].tolist(), ["支出", "收入", "收入"])
        self.assertEqual(frame["金额(元)"].tolist(), [20.0, 100.0, 12.0])
        self.assertEqual(frame["交易类型"].tolist(), ["快捷支付", "代发工资", "快捷退款"])

class CounterpartyViewTest(unittest.TestCase):
    def test_account_names_and_counterparty_breakdown_are_exposed(self):
        from pathlib import Path
        from scripts.analyze import build_summary
        summary = build_summary(Path('/Users/luowenpei/work/记账'))
        labels = {item['label'] for item in summary['meta']['accounts']}
        self.assertTrue({'罗文培', '胡国凤'}.issubset(labels))
        hu = next(item for item in summary['meta']['accounts'] if item['label'] == '胡国凤')
        view = summary['views'][hu['id']]
        luo = next(item for item in view['counterparties'] if item['label'] == '爸比 (罗勇)')
        self.assertEqual(luo['years']['2024']['net'], 105266.0)
        self.assertEqual(luo['years']['2025']['net'], 191281.0)
        self.assertEqual(luo['years']['2026']['net'], 153950.0)

class AccountFirstViewTest(unittest.TestCase):
    def test_primary_view_options_are_people_and_sources_are_secondary(self):
        from pathlib import Path
        from scripts.analyze import build_summary
        summary = build_summary(Path('/Users/luowenpei/work/记账'))
        primary_ids = [item['id'] for item in summary['meta']['view_options']]
        self.assertEqual(primary_ids, ['combined', 'account-1', 'account-2'])
        self.assertEqual([item['id'] for item in summary['meta']['source_options']], ['platform', 'wechat', 'alipay', 'bank'])
        self.assertIn('account-2:wechat', summary['views'])
        self.assertIn('account-1:cmb', summary['views'])

class IncomeSourceLabelTest(unittest.TestCase):
    def test_bank_income_source_labels_distinguish_salary_and_interest(self):
        from scripts.analyze import _income_source
        self.assertEqual(_income_source('代发工资', False), '工资')
        self.assertEqual(_income_source('账户结息', False), '利息')
        self.assertEqual(_income_source('银联代付', False), '转账收入')

class BankSourceDetailTest(unittest.TestCase):
    def test_bank_specific_transaction_types_are_labeled(self):
        from scripts.analyze import _income_source
        self.assertEqual(_income_source('代发款项', False), '工资')
        self.assertEqual(_income_source('朝朝宝转出', False), '理财赎回')
        self.assertEqual(_income_source('银联快捷支付', False), '支付回补')

class BankOtherIncomeDetailTest(unittest.TestCase):
    def test_bank_correction_fund_transfer_and_reward_labels(self):
        from scripts.analyze import _income_source
        self.assertEqual(_income_source('代发住房公积金', False), '住房公积金')
        self.assertEqual(_income_source('数字人民币自动存银行', False), '资金调拨')
        self.assertEqual(_income_source('冲补账处理', False), '账务冲补')
        self.assertEqual(_income_source('一网通支付鼓励金', False), '奖励返现')

class BankInvestmentIncomeTest(unittest.TestCase):
    def test_bank_redemption_and_remittance_labels(self):
        from scripts.analyze import _income_source
        self.assertEqual(_income_source('赎回', False), '理财赎回')
        self.assertEqual(_income_source('体验金收益发放', False), '理财收益')
        self.assertEqual(_income_source('汇入汇款', False), '转账收入')
