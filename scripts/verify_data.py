#!/usr/bin/env python3
"""对发布聚合结果执行计数、金额、来源与隐私边界检查。"""
import json
from pathlib import Path
import re


def verify(path):
    data=json.loads(path.read_text(encoding='utf-8'))
    assert data['schema_version']==3
    rows=data['records']
    measures=['in_cents','out_cents','neutral_cents','earned_cents','spending_cents','transfer_in_cents','transfer_out_cents','refund_cents','refund_adjustment_cents']
    for r in rows:
        assert r['owner'] in data['owners']
        assert isinstance(r['count'],int) and r['count']>0
        assert all(isinstance(r[k],int) for k in measures)
        assert r['in_cents']>=0 and r['out_cents']>=0
        assert not any(k.startswith('_') for k in r)
        assert not any(re.search(r'\d{7,}|[\w.+-]+@[\w.-]+',r[k]) for k in ['party','kind','owner'])
        assert not {'交易单号','商户单号','对方账号','商品','备注'} & r.keys()
    assert sum(r['count'] for r in rows)==sum(s['count'] for s in data['sources'])
    totals=[]
    for source in data['sources']:
        rs=[r for r in rows if r['owner']==source['owner'] and r['source']==source['source']]
        assert sum(r['count'] for r in rs)==source['count']
        gross_in=sum(r['in_cents'] for r in rs);gross_out=sum(r['out_cents'] for r in rs)
        totals.append({'人员':source['owner'],'来源':source['source'],'笔数':source['count'],'流入_分':gross_in,'流出_分':gross_out})
    bank=data['quality']['sources'].get('cmb',{})
    if bank.get('source_files'):
        rs=[r for r in rows if r['source']=='cmb']
        assert sum(r['in_cents']-r['out_cents'] for r in rs)==sum(c['net_cents'] for c in bank['balance_checks'])
        assert all(c['balance_mismatches']==0 and c['opening_cents']+c['net_cents']==c['closing_cents'] for c in bank['balance_checks'])
    return {'通过':True,'原始记录':sum(r['count'] for r in rows),'聚合组':len(rows),'来源合计':totals}


if __name__=='__main__':
    root=Path(__file__).resolve().parents[1]
    print(json.dumps(verify(root/'site/data/analytics.json'),ensure_ascii=False,indent=2))
