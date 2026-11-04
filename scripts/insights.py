"""以资金性质为核心的深度聚合；金额以人民币分为整数，原始说明不对外发布。"""
from collections import defaultdict
from decimal import Decimal, InvalidOperation
from hashlib import sha256
import re
import pandas as pd

SOURCE_LABELS={'wechat':'微信支付','alipay':'支付宝','cmb':'招商银行'}
NATURES={'earned':'可识别收入','received':'往来收付（用途待确认）','consume':'消费','refund':'退款',
         'asset':'本金与账户调拨','repayment':'借贷与还款','adjustment':'支付回补与冲补','unknown':'待确认','neutral':'其他中性记录','void':'关闭或未支付'}
CATEGORY_MAP={'餐饮美食':'餐饮','交通出行':'交通','日用百货':'日用购物','服饰装扮':'服饰','数码电器':'数码',
 '医疗健康':'医疗','住房物业':'居住','家居家装':'家居','文化休闲':'娱乐','酒店旅游':'旅行','教育培训':'教育',
 '美容美发':'个人护理','运动户外':'运动','母婴亲子':'母婴','充值缴费':'通讯缴费','生活服务':'生活服务','商业服务':'商业服务'}
RULES=[('交通',r'铁路|火车|地铁|公交|滴滴|打车|出行|机票|高速|加油'),('医疗',r'医院|药房|诊所|挂号|医保|体检'),
 ('居住',r'房租|物业|水费|电费|燃气|自如|相寓|租赁'),('餐饮',r'餐饮|食堂|餐厅|饭店|火锅|肯德基|麦当劳|瑞幸|奶茶|咖啡|烧烤'),
 ('生鲜食品',r'朴朴|超市|生鲜|水果|菜场|食品'),('服饰',r'女装|服饰|童装|内衣|男装|鞋'),('数码',r'手机|iphone|电脑|耳机|数码'),
 ('家居',r'家居|家具|门窗|板材|装修|建材|灯具|卫浴|木工'),('通讯缴费',r'话费|宽带|通信|中国移动|中国联通|中国电信'),
 ('旅行',r'酒店|旅行|旅游|景区|门票'),('娱乐',r'电影|游戏|音乐|会员'),('教育',r'大学|学费|教育|培训|书店'),
 ('电商购物（细类待确认）',r'京东|淘宝|天猫|拼多多|唯品会')]


def clean(value):
    return '' if value is None or (not isinstance(value,str) and pd.isna(value)) else str(value).strip()


def cents(value):
    try: return int((Decimal(clean(value).replace(',','').replace('¥','').replace('￥',''))*100).quantize(Decimal('1')))
    except (InvalidOperation,ValueError): raise ValueError('存在无法解析的金额')


def public_name(value):
    text=clean(value)
    text=re.sub(r'[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}','[邮箱已隐藏]',text)
    text=re.sub(r'(?<!\d)\+?\d[\d\s-]{6,}\d(?!\d)','[号码已隐藏]',text)
    return text if text and text not in {'/','nan','None'} else '未提供交易对方'


def category(kind,party,description,source):
    if source=='alipay' and kind in CATEGORY_MAP: return CATEGORY_MAP[kind]
    text=(party+' '+description).lower()
    for name,pattern in RULES:
        if re.search(pattern,text): return name
    return '用途待确认'


def nature(kind,party,description,direction,source,owner,status):
    text=kind+' '+description
    incoming=direction=='income'
    if re.search(r'交易关闭|等待付款|支付失败|已撤销',status): return 'void','关闭或未支付','未实际收付'
    if source=='cmb':
        if '代发工资'==kind: return 'earned','工资','账单摘要明确'
        if kind=='代发款项': return 'unknown','单位代发（用途待确认）','摘要未明确工资或报销'
        if '公积金' in kind: return 'asset','住房公积金转入','存量公积金转入，非本期工资'
        if '赎回' in kind or '朝朝宝' in kind: return 'asset','理财本金流动','含本金，不按收益统计'
        if '数字人民币' in kind: return 'asset','数字人民币调拨','账户之间资金流动'
        if '结息' in kind: return 'earned','利息','摘要明确'
        if '收益发放' in kind: return 'earned','理财收益','摘要明确收益'
        if '鼓励金' in kind: return 'earned','奖励返现','摘要明确奖励'
        if '冲补' in kind or (incoming and '快捷支付' in kind): return 'adjustment','支付回补与冲补','资金回流，非新增收入'
        if '退款' in kind: return 'refund','消费退款','独立退款入账'
        if party==owner or any(x in party for x in ['财付通','支付宝（中国）']): return 'asset','本人或支付账户调拨','本人同名或支付账户；资金性质需复核'
        if any(x in party for x in ['基金','理财','证券']): return 'asset','投资账户资金流动','基金机构收付，收益不可直接推定'
        if re.search(r'转账|汇款|渠道转入|代付|网联收款',kind):
            return 'received','往来入账' if incoming else '往来转出','仅确认资金方向，未确认用途'
        if not incoming and re.search(r'支付|消费',kind): return 'consume',category(kind,party,description,source),'商户/描述规则匹配'
        return 'unknown','待确认资金','摘要无法确定经济性质'
    if '投资理财'==kind or re.search(r'基金|理财|余额宝.*收益|买入退款|卖出|赎回',text):
        if re.search(r'收益发放|利息|收益到账',description): return 'earned','理财收益','账单说明明确收益（可能属中性记录）'
        return 'asset','投资账户资金流动','投资本金与收益未分拆'
    if kind in {'信用借还','账户存取'} or re.search(r'信用卡还款|零钱提现|零钱充值|零钱通|数字人民币',kind):
        return ('repayment','借贷与还款','借贷本金或还款') if '借还' in kind or '还款' in kind else ('asset','账户调拨','账户存取')
    if '退款' in kind and direction!='expense': return 'refund','退款待关联','需关联原支出，防止重复扣减'
    if re.search(r'转账|红包',kind): return 'received','往来入账' if incoming else '往来转出','不凭昵称猜测赠与、工资或借款'
    if incoming:
        if re.search(r'工资|薪资',text): return 'earned','工资','账单说明含工资关键词'
        if re.search(r'利息|收益',text): return 'earned','利息与收益','账单说明含收益关键词'
        if re.search(r'返现|奖励|补贴',text): return 'earned','奖励返现','账单说明明确'
        return 'received','收款（用途待确认）','不能直接认定经营收入'
    if direction=='expense': return 'consume',category(kind,party,description,source),'平台分类' if source=='alipay' else '商户/描述规则匹配'
    return 'neutral','其他中性记录','来源标注不计收支'


def status_refund(status,amount):
    if '全额退款' in status or '对方已退还' in status: return amount
    vals=re.findall(r'[¥￥]\s*([\d,]+(?:\.\d+)?)',status)
    return min(amount,max(cents(v) for v in vals)) if vals and ('退款' in status or '退还' in status) else 0


def normalize(frames):
    events=[]; quality={'void_count':0,'unknown_count':0,'refund_links':0,'unlinked_refunds':0}
    for source,frame in frames.items():
        for row in frame.to_dict('records'):
            owner=clean(row.get('__account_key')); party=clean(row.get('交易对方')); kind=clean(row.get('交易类型')); description=clean(row.get('商品'));status=clean(row.get('当前状态'))
            date=pd.Timestamp(row['交易时间']).strftime('%Y-%m-%d'); direction={'收入':'income','支出':'expense','/':'neutral','不计收支':'neutral'}.get(clean(row['收/支']))
            if not direction: raise ValueError('存在未知收支方向')
            amount=cents(row['金额(元)'])
            if amount<0: raise ValueError('标准化金额不能为负')
            nt,cat,reason=nature(kind,party,description,direction,source,owner,status)
            refunded=status_refund(status,amount) if source=='wechat' and direction=='expense' else 0
            valid=nt!='void'
            e={'owner':owner,'source':source,'date':date,'party':public_name(party),'party_id':sha256((owner+'|'+source+'|'+party).encode()).hexdigest()[:16],
               'nature':nt,'category':cat,'basis':reason,'kind':public_name(kind),'count':1,
               'in_cents':amount if valid and direction=='income' else 0,'out_cents':amount if valid and direction=='expense' else 0,
               'neutral_cents':amount if valid and direction=='neutral' else 0,
               'earned_cents':amount if valid and nt=='earned' else 0,
               'spending_cents':amount-refunded if valid and nt=='consume' and direction=='expense' else 0,
               'small_count':1 if valid and nt=='consume' and direction=='expense' and 0<amount-refunded<=5000 else 0,
               'small_cents':amount-refunded if valid and nt=='consume' and direction=='expense' and 0<amount-refunded<=5000 else 0,
               'transfer_in_cents':amount if valid and nt=='received' and direction=='income' else 0,
               'transfer_out_cents':amount-refunded if valid and nt=='received' and direction=='expense' else 0,
               'refund_cents':amount if valid and nt=='refund' else 0,'refund_adjustment_cents':refunded,
               '_amount':amount,'_direction':direction,'_description':description,'_party':party,'_status':status,
               '_order':clean(row.get('交易单号')),'_merchant_order':clean(row.get('商户单号')),
               '_time':pd.Timestamp(row['交易时间']), '_source_file':clean(row.get('__source_file')),'_page':row.get('__page')}
            events.append(e)
            quality['void_count']+=nt=='void'; quality['unknown_count']+=nt=='unknown'
    # 支付宝中性退款：仅在原付款可唯一确认且确实计入消费时扣减，避免全退单/投资退款再扣一次。
    payments=defaultdict(list)
    for e in events:
        if e['source']=='alipay' and e['nature'] not in {'refund','asset','repayment','earned','void'}:
            payments[e['owner']].append(e)
    allocated=defaultdict(int)
    for refund in events:
        if refund['source']!='alipay' or refund['nature']!='refund': continue
        desc=re.sub(r'^退款[-：:]?','',refund['_description']).strip()
        candidates=[]
        exact=[]
        for p in payments[refund['owner']]:
            if p['_time']>refund['_time'] or p['_party']!=refund['_party']: continue
            same_id=refund['_order'] and refund['_order']==p['_order']
            same_desc=desc and desc==p['_description']
            if same_id and refund['_amount']<=p['_amount']: exact.append(p)
            if same_desc and refund['_amount']<=p['_amount']: candidates.append(p)
        if exact: candidates=exact
        if len(candidates)==1:
            p=candidates[0]
            if p['nature']=='consume' and p['spending_cents']-allocated[id(p)]>=refund['_amount']:
                # 退款发生日在聚合中做负向调整；保留原付款日毛支出。
                allocated[id(p)]+=refund['_amount']
                refund['spending_cents']=-refund['_amount'];refund['category']=p['category']
                refund['basis']='原订单/描述及对方唯一关联';refund['refund_adjustment_cents']=refund['_amount']
            elif p['nature']=='consume':
                refund['basis']='累计退款超过可抵扣支出，需复核'
                quality['unlinked_refunds']+=1
                continue
            else: refund['basis']='原单不计消费，退款不再扣减'
            quality['refund_links']+=1
        else:
            quality['unlinked_refunds']+=1; refund['basis']='未能唯一关联原消费，仅展示退款金额'
    return events,quality


MEASURES=['count','in_cents','out_cents','neutral_cents','earned_cents','spending_cents','transfer_in_cents','transfer_out_cents','refund_cents','refund_adjustment_cents','small_count','small_cents']
DIMENSIONS=['owner','source','date','party','party_id','nature','category','basis','kind']


def aggregate(events):
    cube={}
    for e in events:
        key=tuple(e[k] for k in DIMENSIONS)
        if key not in cube: cube[key]={**{k:e[k] for k in DIMENSIONS},**{k:0 for k in MEASURES},'max_spending_cents':0}
        row=cube[key]
        for k in MEASURES: row[k]+=e[k]
        row['max_spending_cents']=max(row['max_spending_cents'],e['spending_cents'])
    return sorted(cube.values(),key=lambda r:(r['date'],r['owner'],r['source'],r['party_id']))


def build_data(frames,quality):
    for source,q in quality.items():
        if any(q.get(k,0) for k in ['unparseable_dates','unparseable_amounts','unknown_directions']):
            raise ValueError(f'{source} 存在无效记录，停止发布并保留原输出')
        if any(b.get('balance_mismatches',0) for b in q.get('balance_checks',[])):
            raise ValueError('银行余额不连续，停止发布并保留原输出')
    events,quality_checks=normalize(frames)
    records=aggregate(events)
    sources=[]
    for source,frame in frames.items():
        if frame.empty:continue
        for owner,part in frame.groupby('__account_key'):
            eventpart=[e for e in events if e['owner']==owner and e['source']==source]
            sources.append({'owner':owner,'source':source,'label':SOURCE_LABELS[source], 'count':len(part),
                            'start':str(part['__date'].min().date()),'end':str(part['__date'].max().date()),
                            'files':int(part['__source_file'].nunique()),'void_count':sum(e['nature']=='void' for e in eventpart)})
    checks={k:{key:val for key,val in q.items() if key!='file_records'} for k,q in quality.items()}
    return {'schema_version':3,'generated_at':pd.Timestamp.now(tz='Asia/Shanghai').isoformat(),
            'owners':sorted(set(e['owner'] for e in events)),'sources':sources,'nature_labels':NATURES,
            'quality':{'sources':checks,**quality_checks},'records':records,
            'policy':'所有图表基于同一筛选范围；银行与支付平台单独核对。赎回本金、调拨和退款不计新增收入。用途不明确的往来保持待确认。',
            'references':[{'name':'Actual Budget','url':'https://actualbudget.org/docs/reports/custom-reports/'},
                          {'name':'Firefly III','url':'https://github.com/firefly-iii/firefly-iii'},
                          {'name':'z-bill-analyzer','url':'https://github.com/zLatiao/z-bill-analyzer'}]}
