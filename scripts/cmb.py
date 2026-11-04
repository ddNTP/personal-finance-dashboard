"""招商银行 PDF 的列坐标适配器。原始对手账号不进入公开聚合结果。"""
from decimal import Decimal
import re

DATE = re.compile(r'^\d{4}-\d{2}-\d{2}$')
MONEY = re.compile(r'^[+-]?[\d,]+\.\d{2}$')


def cents(value):
    return int((Decimal(str(value).replace(',', '')) * 100).quantize(Decimal('1')))


def join_lines(words):
    lines = {}
    for word in words:
        key = round(word['top'] / 2) * 2
        lines.setdefault(key, []).append(word)
    return ''.join(' '.join(w['text'] for w in sorted(line, key=lambda x:x['x0']))
                   for _,line in sorted(lines.items()))


def clean_counterparty(text):
    # 对手姓名在账号前；兼容跨行公司名、脱敏账号及字母账号。
    text = re.split(r'\s+(?=[\dA-Za-z_][\dA-Za-z_*\-]{5,})', text, maxsplit=1)[0]
    text = re.sub(r'[A-Za-z_]*\d[\dA-Za-z_*\-]{5,}.*$', '', text)
    return re.sub(r'\s+', '', text).strip() or '未提供交易对方'


def parse_words(words, page_number, source_file):
    anchors = sorted([w for w in words if w['x0'] < 95 and DATE.fullmatch(w['text'])], key=lambda w:w['top'])
    rows = []
    for i, anchor in enumerate(anchors):
        y = anchor['top']
        low = (anchors[i-1]['top'] + y)/2 if i else y-18
        high = (anchors[i+1]['top'] + y)/2 if i+1<len(anchors) else y+18
        line = [w for w in words if abs(w['top']-y)<2.5]
        def money_col(lo,hi):
            values=[w['text'] for w in line if lo <= w['x0'] < hi and MONEY.fullmatch(w['text'])]
            if len(values)!=1: raise ValueError(f'银行 PDF 第 {page_number} 页金额列解析不唯一')
            return cents(values[0])
        currency=[w['text'] for w in line if 95<=w['x0']<150]
        if currency!=['CNY']: raise ValueError('银行账单包含非人民币或无法识别的币种，暂不混算')
        amount,balance=money_col(150,230),money_col(230,302)
        kind=join_lines([w for w in words if 302<=w['x0']<413 and low<=w['top']<high])
        payee=clean_counterparty(join_lines([w for w in words if w['x0']>=413 and low<=w['top']<high]))
        if not kind: raise ValueError(f'银行 PDF 第 {page_number} 页摘要为空')
        rows.append({'交易时间':anchor['text'],'交易类型':kind,'交易对方':payee,'商品':kind,
                     '收/支':'收入' if amount>=0 else '支出','金额(元)':abs(amount)/100,
                     '支付方式':'银行卡','当前状态':kind,'交易单号':f'{source_file}:{page_number}:{i}',
                     '商户单号':'/','备注':'','__signed_cents':amount,'__balance_cents':balance,'__page':page_number})
    return rows


def check_balances(rows):
    if not rows: raise ValueError('银行 PDF 未提取到交易')
    differences=[]
    for i in range(1,len(rows)):
        if rows[i]['__balance_cents']-rows[i-1]['__balance_cents']!=rows[i]['__signed_cents']:
            differences.append({'page':rows[i]['__page'],'row':i+1})
    opening=rows[0]['__balance_cents']-rows[0]['__signed_cents']
    return {'rows':len(rows),'balance_checks':len(rows)-1,'balance_mismatches':len(differences),
            'opening_cents':opening,'closing_cents':rows[-1]['__balance_cents'],
            'net_cents':sum(r['__signed_cents'] for r in rows),'mismatch_positions':differences}
