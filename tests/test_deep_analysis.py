"""分析口径的行为测试；全部使用合成数据，不依赖个人账单。"""
import unittest
import pandas as pd
from scripts.analyze import _prepare_transactions


def raw_row(**kwargs):
    row = {'交易时间':'2026-01-02 12:00:00', '交易类型':'商户消费', '交易对方':'商店', '商品':'商品', '收/支':'支出', '金额(元)':100,
           '支付方式':'零钱', '当前状态':'支付成功', '交易单号':'same-id', '__account_key':'测试用户', '__source_file':'test.xlsx'}
    row.update(kwargs)
    return row


class DataIntegrityTest(unittest.TestCase):
    def test_same_order_refund_is_not_duplicate(self):
        purchase=raw_row()
        refund=raw_row(**{'交易时间':'2026-01-03 12:00:00','交易类型':'退款','收/支':'/','金额(元)':20,'当前状态':'退款成功'})
        data,quality=_prepare_transactions(pd.DataFrame([purchase,refund,purchase]),'alipay')
        self.assertEqual(len(data),2)
        self.assertEqual(quality['duplicate_records_removed'],1)

    def test_salary_is_not_inferred_from_generic_payroll(self):
        from scripts.analyze import _income_source
        self.assertEqual(_income_source('代发款项',False),'单位代发（用途待确认）')

    def test_merchant_transaction_type_does_not_force_shopping(self):
        from scripts.analyze import _category_for_expense
        self.assertEqual(_category_for_expense('未知商家','商户消费','wechat'),'其他消费')

    def test_multiline_pdf_counterparty_does_not_bleed_into_previous_row(self):
        from scripts.cmb import parse_words
        words=[]
        def w(text,x,y): words.append({'text':text,'x0':x,'x1':x+30,'top':y,'bottom':y+10})
        for y,date,amt,bal,kind in [(100,'2026-01-01','100.00','100.00','代发工资'),(130,'2026-01-02','50.00','150.00','汇入汇款')]:
            for text,x in [(date,36),('CNY',98),(amt,156),(bal,234),(kind,307)]: w(text,x,y)
        w('甲企业有限',417,94); w('公司 1234567890',417,106)
        w('乙先生 1234567899',417,130)
        records=parse_words(words,1,'test.pdf')
        self.assertEqual(records[0]['交易对方'],'甲企业有限公司')
        self.assertEqual(records[1]['交易对方'],'乙先生')
        self.assertEqual(records[0]['交易类型'],'代发工资')
        self.assertEqual(records[1]['__balance_cents'],15000)

class FinancialNatureTest(unittest.TestCase):
    def test_redemption_and_own_transfer_not_earned_income(self):
        from scripts.insights import normalize
        rows=[raw_row(**{'交易类型':'赎回','收/支':'收入','__account_key':'甲','交易对方':'理财公司','__source':'cmb'}),
              raw_row(**{'交易类型':'汇入汇款','收/支':'收入','__account_key':'甲','交易对方':'甲','__source':'cmb'}),
              raw_row(**{'交易类型':'代发工资','收/支':'收入','__account_key':'甲','交易对方':'甲公司','__source':'cmb'})]
        e,q=normalize({'cmb':pd.DataFrame(rows)})
        self.assertEqual([r['nature'] for r in e],['asset','asset','earned'])

    def test_closed_trade_excluded_and_refund_only_once(self):
        from scripts.insights import normalize
        rows=[raw_row(**{'当前状态':'交易关闭'}),raw_row(**{'交易单号':'2','当前状态':'已退款(¥20.00)'}),
              raw_row(**{'交易单号':'3','交易类型':'商店-退款','当前状态':'已退款¥20.00','收/支':'收入','金额(元)':20})]
        e,q=normalize({'wechat':pd.DataFrame(rows)})
        self.assertEqual(sum(r['spending_cents'] for r in e),8000)
        self.assertEqual(q['void_count'],1)

    def test_alipay_investment_refund_not_consumption_refund(self):
        from scripts.insights import normalize
        rows=[raw_row(**{'交易类型':'餐饮美食','当前状态':'交易成功'}),raw_row(**{'交易单号':'2','交易类型':'退款','商品':'基金买入退款','当前状态':'退款成功','收/支':'/','金额(元)':50})]
        e,q=normalize({'alipay':pd.DataFrame(rows)})
        self.assertEqual(sum(r['spending_cents'] for r in e),10000)
        self.assertEqual(e[1]['nature'],'asset')

    def test_monthly_cube_sums_and_masks_identifiers(self):
        from scripts.insights import normalize, aggregate
        rows=[raw_row(**{'交易对方':'李先生 13800138000','商品':'敏感商品详情'}),raw_row(**{'金额(元)':50,'交易单号':'2','交易对方':'李先生 13800138000','商品':'敏感商品详情'})]
        events,q=normalize({'wechat':pd.DataFrame(rows)})
        cube=aggregate(events)
        self.assertEqual(sum(r['spending_cents'] for r in cube),15000)
        import json
        data=json.dumps(cube,ensure_ascii=False)
        for secret in ['13800138000','敏感商品详情','same-id']:
            self.assertNotIn(secret,data)
        self.assertEqual(sum(r['count'] for r in cube),2)

class RefundLinkTest(unittest.TestCase):
    def test_multiple_refunds_cannot_exceed_original_payment(self):
        from scripts.insights import normalize
        rows=[raw_row(**{'交易类型':'餐饮美食','商品':'原订单','当前状态':'交易成功'}),
              raw_row(**{'交易时间':'2026-01-03','交易类型':'退款','商品':'退款-原订单','收/支':'/','金额(元)':60,'当前状态':'退款成功','交易单号':'r1'}),
              raw_row(**{'交易时间':'2026-01-04','交易类型':'退款','商品':'退款-原订单','收/支':'/','金额(元)':60,'当前状态':'退款成功','交易单号':'r2'})]
        e,q=normalize({'alipay':pd.DataFrame(rows)})
        self.assertEqual(sum(x['spending_cents'] for x in e),4000)
        self.assertEqual(q['unlinked_refunds'],1)

    def test_invalid_input_quality_cannot_be_silently_published(self):
        from scripts.insights import build_data
        with self.assertRaises(ValueError):
            build_data({}, {'wechat':{'unparseable_dates':1}})

class ImportSnapshotTest(unittest.TestCase):
    def test_updated_refund_status_replaces_prior_payment_snapshot(self):
        before=raw_row(**{'当前状态':'支付成功'})
        after=raw_row(**{'当前状态':'已退款(¥20.00)'})
        d,q=_prepare_transactions(pd.DataFrame([before,after]),'wechat')
        self.assertEqual(len(d),1)
        self.assertEqual(d['__effective_consumption'].sum(),80)

    def test_two_partial_refund_events_of_same_order_are_kept(self):
        a=raw_row(**{'交易类型':'退款','收/支':'/','金额(元)':10,'当前状态':'退款成功'})
        b={**a,'交易时间':'2026-01-03 12:00:00'}
        d,q=_prepare_transactions(pd.DataFrame([a,b,a]),'alipay')
        self.assertEqual(len(d),2)

class RefundPriorityTest(unittest.TestCase):
    def test_exact_order_wins_over_same_description(self):
        from scripts.insights import normalize
        a=raw_row(**{'交易类型':'餐饮美食','商品':'相同商品','当前状态':'交易成功','交易单号':'p1'})
        b={**a,'交易单号':'p2'}
        r=raw_row(**{'交易时间':'2026-01-03','交易类型':'退款','商品':'退款-相同商品','收/支':'/','金额(元)':20,'当前状态':'退款成功','交易单号':'p1'})
        e,q=normalize({'alipay':pd.DataFrame([a,b,r])})
        self.assertEqual(sum(x['spending_cents'] for x in e),18000)
        self.assertEqual(q['refund_links'],1)
