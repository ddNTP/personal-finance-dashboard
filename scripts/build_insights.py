#!/usr/bin/env python3
"""读取本地原始账单，生成分享网页使用的深度聚合结果。"""
import argparse
import json
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from scripts.analyze import _load_wechat_transactions,_load_alipay_transactions,_load_cmb_transactions
from scripts.insights import build_data


def main():
    root=Path(__file__).resolve().parents[1]
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--input-dir',type=Path,default=root)
    p.add_argument('--output',type=Path,default=root/'site/data/analytics.json')
    a=p.parse_args(); frames={};quality={}
    for source,loader in [('wechat',_load_wechat_transactions),('alipay',_load_alipay_transactions),('cmb',_load_cmb_transactions)]:
        frames[source],quality[source]=loader(a.input_dir)
    d=build_data(frames,quality)
    a.output.parent.mkdir(exist_ok=True,parents=True)
    a.output.write_text(json.dumps(d,ensure_ascii=False,separators=(',',':'))+'\n',encoding='utf-8')
    print(json.dumps({'账单记录':sum(s['count'] for s in d['sources']),'聚合行':len(d['records']),'校验':d['quality']},ensure_ascii=False))


if __name__=='__main__':main()
