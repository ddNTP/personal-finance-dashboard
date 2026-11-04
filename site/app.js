/* 交互展示；所有计算统一调用 engine.js，原始账单不会在浏览器加载。 */
(() => {
  const E=Finance, $=s=>document.querySelector(s), esc=v=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const money=c=>new Intl.NumberFormat('zh-CN',{style:'currency',currency:'CNY',maximumFractionDigits:2}).format((Number(c)||0)/100);
  const short=c=>Math.abs(c)>=1000000?`${c<0?'−':''}¥${(Math.abs(c)/1000000).toFixed(1)}万`:money(c);
  const integer=n=>new Intl.NumberFormat('zh-CN').format(n||0), pct=v=>v===null?'无可比基数':`${v>0?'+':''}${(v*100).toFixed(1)}%`;
  const sourceNames={wechat:'微信支付',alipay:'支付宝',cmb:'招商银行',platform:'支付平台合计'};
  const S={data:null,owner:'',source:'platform',start:'',end:'',granularity:'month',comparison:'year',page:1,drillPage:1,drill:[],series:new Set(['earned','spending','received'])};
  const colors={earned:'#087e77',spending:'#c36c34',received:'#577cba'}, seriesLabels={earned:'可识别收入',spending:'消费净支出',received:'往来流入'};
  let rows=[],persons=[],actionMap=new Map(),actionId=0;
  function action(label,filter,title,cls='link-button'){const id=String(++actionId);actionMap.set(id,{filter,title});return `<button class="${cls}" data-drill="${id}">${esc(label)}</button>`;}
  function range(){const cs=S.data.sources.filter(x=>x.owner===S.owner&&(S.source==='platform'?x.source!=='cmb':x.source===S.source));return{start:cs.map(x=>x.start).sort()[0],end:cs.map(x=>x.end).sort().at(-1),cs};}
  function scope(){return{owner:S.owner,source:S.source,start:S.start,end:S.end};}
  function current(){return E.select(S.data.records,scope());}
  function toast(text){const n=$('#toast');n.textContent=text;n.hidden=false;clearTimeout(S.toastTimer);S.toastTimer=setTimeout(()=>n.hidden=true,4000);}
  function dates(){ $('#startDate').value=S.start;$('#endDate').value=S.end; }
  function buildControls(){
    $('#personTabs').innerHTML=S.data.owners.map(o=>`<button class="tab ${S.owner===o?'active':''}" aria-pressed="${S.owner===o}" data-owner="${esc(o)}">${esc(o)}</button>`).join('');
    const ss=S.data.sources.filter(x=>x.owner===S.owner).map(x=>x.source);const opts=[...(ss.some(s=>s!=='cmb')?['platform']:[]),...ss];
    if(!opts.includes(S.source))S.source=opts[0];
    $('#sourceSelect').innerHTML=opts.map(s=>`<option value="${s}" ${s===S.source?'selected':''}>${sourceNames[s]}</option>`).join('');
    const bounds=range();const years=[];for(let y=Number(bounds.start?.slice(0,4));y<=Number(bounds.end?.slice(0,4));y++)years.push(y);
    $('#presets').innerHTML=years.map(y=>`<button data-year="${y}" class="${S.start===`${y}-01-01`?'active':''}">${y}年</button>`).join('')+'<button data-year="all">全部</button>';
    dates();
  }
  function renderKpis(m){
    const cards=[['账单流入',m.inflow,'包含转账、退款、本金回流'],['账单流出',m.outflow,'原始收支方向汇总'],['可识别收入',m.earned,'工资、明确利息/收益、返现'],[S.source==='cmb'?'可识别消费支出':'消费净支出',m.spending,S.source==='cmb'?'银行退款单列，未关联抵扣':`${integer(m.expenseCount)} 笔支出，扣除已确认退款`],['往来净流入',m.received-m.sent,'收到转账 − 有效转出，非净利润'],['账单净额',m.net,'当前账本流入 − 流出，不等于储蓄']];
    $('#kpis').innerHTML=cards.map(([label,value,foot],i)=>`<article class="kpi"><div class="kpi-title">${label}</div><div class="kpi-value ${i>=4?(value<0?'negative':'positive'):''}" title="${esc(money(value))}">${esc(short(value))}</div><div class="kpi-foot">${esc(foot)}</div></article>`).join('');
    const incomeCats=E.group(rows.filter(r=>r.in_cents>0),'category','in_cents'),spend=E.group(rows.filter(r=>r.spending_cents!==0),'category','spending_cents'),unknown=m.unknownSpend/Math.max(1,m.spending);
    const peak=E.periods(rows).sort((a,b)=>b.spending-a.spending)[0];
    const statements=[
      {title:incomeCats.length?`最多入账：${incomeCats[0].label}`:'本期没有收入方向记录',detail:incomeCats.length?`${money(incomeCats[0].amount)}。展开下方收入追踪，可以核对付款方。`:'可调整人员、日期或分析账本。'},
      {title:peak&&peak.spending>0?`消费峰值：${peak.label}`:'本期没有可识别消费',detail:peak&&peak.spending>0?`该月 ${money(peak.spending)}。${spend[0]?`最大类别为“${spend[0].label}”。`:''}`:'资金调拨、还款和本金流动单独归类。'},
      {title:unknown>.15?'先确认用途，再判断消费结构':'资金回流已单独解释',detail:unknown>.15?`消费中 ${money(m.unknownSpend)} 的用途仍待确认，占 ${Math.max(0,unknown*100).toFixed(1)}%。`:`本金/账户调拨流入 ${money(m.assetIn)}，退款 ${money(m.refunds)}，这些不能直接当作新增收入。`}
    ];
    $('#insights').innerHTML=statements.map(x=>`<article class="insight"><strong>${esc(x.title)}</strong><p>${esc(x.detail)}</p></article>`).join('');
  }
  function renderChannels(){
    const cs=S.data.sources.filter(c=>c.owner===S.owner);
    $('#channelCards').innerHTML=cs.map(c=>{const rs=E.select(S.data.records,{...scope(),source:c.source}),m=E.totals(rs);return `<button class="channel-card ${S.source===c.source?'active':''}" data-source="${c.source}" aria-label="查看${esc(S.owner)}的${esc(c.label)}"><strong>${esc(c.label)}</strong><span class="source-range">记录覆盖 ${c.start} — ${c.end}</span><dl><dt>可识别收入</dt><dd>${money(m.earned)}</dd><dt>往来流入</dt><dd>${money(m.received)}</dd><dt>本金/调拨流入</dt><dd>${money(m.assetIn)}</dd><dt>退款入账</dt><dd>${money(m.refunds)}</dd></dl></button>`;}).join('');
  }
  function renderTrend(){
    const periods=E.periods(rows,S.granularity),n=periods.length;
    if(!n){$('#trendChart').innerHTML='<p class="empty">此范围没有账单记录</p>';return;}
    const W=1100,H=285,L=75,R=24,T=15,B=45,keys=[...S.series],vals=periods.flatMap(r=>keys.map(k=>r[k]));
    const max=Math.max(1,...vals),min=Math.min(0,...vals),x=i=>L+(n===1?.5:i/(n-1))*(W-L-R),y=v=>T+(max-v)/(max-min)*(H-T-B);
    let svg='';for(let i=0;i<5;i++){const v=min+(max-min)*i/4;svg+=`<line class="grid-line" x1="${L}" x2="${W-R}" y1="${y(v)}" y2="${y(v)}"/><text x="${L-12}" y="${y(v)+4}" text-anchor="end">${esc(short(v))}</text>`;}
    keys.forEach(k=>{svg+=`<path fill="none" stroke="${colors[k]}" stroke-width="2.5" d="${periods.map((r,i)=>`${i?'L':'M'}${x(i)},${y(r[k])}`).join(' ')}"/>`;});
    periods.forEach((p,i)=>{const step=Math.max(1,Math.ceil(n/12));if(i%step===0||i===n-1)svg+=`<text x="${x(i)}" y="${H-12}" text-anchor="middle">${esc(p.label)}</text>`;
      const tip=`${p.label} ${keys.map(k=>seriesLabels[k]+money(p[k])).join(' / ')}`;
      svg+=`<rect class="trend-period" data-period="${esc(p.label)}" x="${x(i)-Math.min(30,(W-L-R)/n/2)}" y="${T}" width="${Math.min(60,(W-L-R)/n)}" height="${H-B-T}" role="button" tabindex="0" aria-label="查看${esc(tip)}"><title>${esc(tip)}</title></rect>`;
      keys.forEach(k=>{svg+=`<circle cx="${x(i)}" cy="${y(p[k])}" r="3" fill="${colors[k]}" pointer-events="none"/>`;});});
    $('#trendChart').innerHTML=`<svg viewBox="0 0 ${W} ${H}" role="img" aria-label="当前人员收支趋势">${svg}</svg>`;
  }
  function renderIncome(){
    const incoming=rows.filter(r=>r.in_cents>0),m=E.totals(rows),flows=E.group(incoming,'nature','in_cents');
    $('#incomeBasis').textContent=sourceNames[S.source];
    $('#incomeBridge').innerHTML=flows.map(x=>`<div class="flow-row"><span>${action(S.data.nature_labels[x.label],r=>r.nature===x.label&&r.in_cents>0,'流入 · '+S.data.nature_labels[x.label])}<br><small>${integer(x.count)} 笔 · ${m.inflow?(x.amount/m.inflow*100).toFixed(1):0}%</small></span><strong>${money(x.amount)}</strong></div>`).join('')+`<div class="flow-total"><span>分项合计 = 账单流入</span><strong>${money(m.inflow)}</strong></div>`;
    const outgoing=E.group(rows.filter(r=>r.out_cents>0),'nature','out_cents');
    $('#incomeBridge').innerHTML+=`<details class="method"><summary>流出去哪了 · ${money(m.outflow)}</summary>${outgoing.map(x=>`<div class="flow-row"><span>${action(S.data.nature_labels[x.label],r=>r.nature===x.label&&r.out_cents>0,'流出 · '+S.data.nature_labels[x.label])}</span><strong>${money(x.amount)}</strong></div>`).join('')}<p class="muted small">毛流出按账单方向分项；消费净额另按已确认退款调整。</p></details>`;
    $('#incomeNote').textContent='只将明确工资、利息、收益和返现列作可识别收入。本人转回、公积金转入、理财赎回及退款不等于新增收入。来源标注为中性的收益单列，不强行改写账单方向。';
    const cats=E.group(incoming,'category','in_cents');
    $('#incomeSources').innerHTML=cats.length?cats.map((c,i)=>{const subset=incoming.filter(r=>r.category===c.label),payees=E.group(subset,'party','in_cents');return `<details class="income-detail" ${i<2?'open':''}><summary><span class="income-name">${esc(c.label)}</span><strong>${money(c.amount)}</strong></summary><p class="muted">${integer(c.count)} 笔 · ${esc(subset[0]?.basis||'')}</p>${payees.slice(0,6).map(p=>`<div class="payee-row">${action(p.label,r=>r.category===c.label&&r.party===p.label&&r.in_cents>0,c.label+' · '+p.label)}<span>${money(p.amount)} · ${p.count} 笔</span></div>`).join('')}<div class="payee-row">${action(`查看本类全部 ${payees.length} 个对象的依据`,r=>r.category===c.label&&r.in_cents>0,c.label)}</div></details>`;}).join(''):'<p class="empty">当前账本和日期没有收入方向记录。其他渠道收入可在上方卡片核对。</p>';
  }
  function renderSpending(m){
    const categories=E.group(rows.filter(r=>r.spending_cents!==0),'category','spending_cents'),max=Math.max(1,...categories.map(r=>Math.abs(r.amount)));
    $('#categoryBars').innerHTML=categories.length?categories.map(c=>`<div class="bar-row"><div class="bar-labels">${action(c.label,r=>r.category===c.label&&r.spending_cents!==0,c.label+' · 消费依据')}<strong>${money(c.amount)}</strong></div><div class="bar-track"><div class="bar-fill orange" style="width:${Math.abs(c.amount)/max*100}%"></div></div><div class="bar-caption"><span>${integer(c.count)} 条相关记录</span><span>${m.spending?(c.amount/m.spending*100).toFixed(1):0}%</span></div></div>`).join(''):'<p class="empty">这个范围没有消费记录</p>';
    const days=E.days(S.start,S.end),stats=[['区间日均消费',money(m.spending/days)],['平均每笔消费',m.expenseCount?money(m.spending/m.expenseCount):'—'],['≤50元的小额支出',`${integer(m.smallCount)} 笔`],['小额支出合计',money(m.smallAmount)]];
    $('#spendingStats').innerHTML=stats.map(([k,v])=>`<div class="mini-stat"><span>${k}</span><strong>${v}</strong></div>`).join('');
    const prior=E.comparisonRange(S.start,S.end,S.comparison),bounds=range();const adequate=E.comparable({start:S.start,end:S.end},prior,bounds);
    const prev=E.select(S.data.records,{...scope(),...prior}),pm=E.totals(prev);
    $('#comparisonSummary').innerHTML=`<p class="muted">本期 ${S.start} — ${S.end}<br>基期 ${prior.start} — ${prior.end}</p><div class="comparison-number ${m.spending-pm.spending>0?'negative':'positive'}">${adequate?pct(E.change(m.spending,pm.spending)):'期间覆盖不足'}</div><p class="muted small">${adequate?`消费净支出差额 ${money(m.spending-pm.spending)}`:'不把缺少账单的日期当作零支出，暂不输出变化率。'}</p>`;
    $('#changes').innerHTML=adequate?E.changes(rows,prev).filter(c=>c.now||c.before).slice(0,6).map(c=>`<div class="change-row"><div>${action(c.label,r=>r.category===c.label&&r.spending_cents!==0,c.label+' · 本期变化依据')}<small>${money(c.before)} → ${money(c.now)}</small></div><div class="delta ${c.delta>0?'negative':'positive'}">${c.delta>0?'+':''}${money(c.delta)}<small>${pct(c.rate)}</small></div></div>`).join(''):'';
    const rec=E.recurring(rows);
    $('#recurring').innerHTML=rec.length?rec.slice(0,6).map(r=>`<div class="event-card"><div>${action(r.label,x=>x.party_id===r.party_id&&x.source===r.source,r.label+' · 周期候选')}<p>${r.months} 个月出现 · 月金额波动 ${(r.variation*100).toFixed(1)}%</p></div><strong>${money(r.average)}<p>平均每个活跃月</p></strong></div>`).join(''):'<p class="empty">当前范围未发现符合规则的周期候选。尝试选择至少三个月。</p>';
    const large=E.largeDays(rows),merchants=E.group(rows.filter(r=>r.spending_cents>0),'party_id','spending_cents'),top5=merchants.slice(0,5).reduce((s,x)=>s+x.amount,0),gross=merchants.reduce((s,x)=>s+x.amount,0);
    $('#largeSpend').innerHTML=`<p class="muted">前 5 个消费对象占正向消费金额 <strong>${gross?(top5/gross*100).toFixed(1):0}%</strong></p>`+large.rows.slice(0,6).map(r=>`<div class="event-card"><div>${action(r.party,x=>x.date===r.date&&x.party_id===r.party_id,r.party+' · '+r.date)}<p>${r.date} · ${esc(r.category)}</p></div><strong>${money(r.max_spending_cents)}<p>当日该对象最大单笔</p></strong></div>`).join('');
    $('#largeNote').textContent=`筛选阈值为所选期间各日/对象聚合组最大单笔的第95百分位与 ¥1,000 的较大值：${money(large.threshold)}。仅供复盘，不据此判断异常用途。`;
  }
  function renderPeople(){
    const mode=$('#partyMode').value,q=$('#partySearch').value.trim().toLowerCase(),sort=$('#partySort').value;
    persons=E.parties(rows,mode==='transfer').filter(r=>r.label.toLowerCase().includes(q));
    persons.sort((a,b)=>sort==='net'?Math.abs(b.net)-Math.abs(a.net):b[sort]-a[sort]);
    const pages=Math.max(1,Math.ceil(persons.length/12));S.page=Math.min(S.page,pages);
    const list=persons.slice((S.page-1)*12,S.page*12);
    $('#partyTable').innerHTML=`<table><thead><tr><th>交易对象</th><th>渠道</th><th class="number">流入</th><th class="number">流出</th><th class="number">净流入</th><th class="number">笔数</th></tr></thead><tbody>${list.map(p=>`<tr><td class="party-name">${action(p.label,r=>r.party===p.label&&r.source===p.source&&(mode!=='transfer'||r.nature==='received'),p.label+' · '+sourceNames[p.source])}</td><td>${sourceNames[p.source]}</td><td class="number">${money(p.income)}</td><td class="number">${money(p.expense)}</td><td class="number ${p.net<0?'negative':'positive'}">${money(p.net)}</td><td class="number">${p.count}</td></tr>`).join('')}</tbody></table>${list.length?'':'<p class="empty">没有匹配的对象，可清空搜索或切换到全部收付款。</p>'}`;
    $('#partyPage').textContent=`共 ${persons.length} 个对象 · 第 ${S.page} / ${pages} 页`;$('#prevParty').disabled=S.page<=1;$('#nextParty').disabled=S.page>=pages;
  }
  function renderQuality(){
    const q=S.data.quality,bank=q.sources.cmb,checks=bank?.balance_checks||[],checked=checks.reduce((n,x)=>n+x.balance_checks,0),bad=checks.reduce((n,x)=>n+x.balance_mismatches,0);
    const items=[['已读取账单',integer(S.data.sources.reduce((s,x)=>s+x.count,0))+' 笔',`${S.data.sources.reduce((s,x)=>s+x.files,0)} 份文件，按人和渠道保留各自范围。图表始终仅计算当前筛选。`],['银行余额连续校验',`${integer(checked-bad)} / ${integer(checked)}`,bad?'存在不连续项，须核对原始 PDF。':'相邻余额差与每笔交易金额一致；列坐标提取对手信息。'],['排除关闭或未支付',integer(q.void_count)+' 笔','保留记录数但不作为实际收付。支付宝同订单的付款与退款分别保留。'],['退款唯一关联',integer(q.refund_links)+' 笔',`支付宝另有 ${q.unlinked_refunds} 笔未唯一关联原消费，只展示退款，不猜测重复扣减。`],['资金用途待确认',integer(q.unknown_count)+' 笔','代发款项和其他不明确资金用途仍需确认，不强行归入工资或盈利。'],['跨渠道重复边界','独立账本','银行快捷支付可能对应微信或支付宝订单。当前不叠加银行与支付平台金额，也不推算家庭净资产。']];
    $('#qualityGrid').innerHTML=items.map(([title,value,detail])=>`<div class="quality-item"><span class="eyebrow">${esc(title)}</span><strong>${esc(value)}</strong><p>${esc(detail)}</p></div>`).join('');
    $('#references').innerHTML=S.data.references.map(r=>`<a href="${esc(r.url)}" target="_blank" rel="noopener">借鉴：${esc(r.name)} ↗</a>`).join('');
    $('#generatedAt').textContent='生成于 '+new Date(S.data.generated_at).toLocaleString('zh-CN',{timeZone:'Asia/Shanghai'})+' 北京时间';
  }
  function render(){
    actionMap.clear();actionId=0; rows=current();
    $('#periodLabel').textContent=`${S.owner} · ${sourceNames[S.source]} · ${S.start} — ${S.end}`;
    const bounds=range();$('#scopeNote').textContent=`当前统计 ${S.owner} 的${sourceNames[S.source]}。此账本记录覆盖 ${bounds.start} — ${bounds.end}；${S.end.slice(5)!=='12-31'?'当前末年不是完整年度。':''}银行与支付平台分开核对。`;
    const m=E.totals(rows);renderKpis(m);renderChannels();renderTrend();renderIncome();renderSpending(m);renderPeople();renderQuality();
    $('#dataStatus').textContent=`${S.data.owners.length} 人 · ${S.data.sources.reduce((s,x)=>s+x.files,0)} 份账单 · ${integer(m.count)} 条匹配记录`;
    $('#filterError').hidden=true;saveView();
  }
  function saveView(){const u=new URL(location.href);u.searchParams.set('owner',S.owner);u.searchParams.set('source',S.source);u.searchParams.set('from',S.start);u.searchParams.set('to',S.end);history.replaceState(null,'',u);}
  function changeSource(source){S.source=source;S.page=1;buildControls();render();}
  function drill(filter,title){S.drill=rows.filter(filter);S.drillPage=1;$('#drillTitle').textContent=title;renderDrill();if(!$('#drillDialog').open)$('#drillDialog').showModal();}
  function renderDrill(){
    const t=E.totals(S.drill),pages=Math.max(1,Math.ceil(S.drill.length/25));S.drillPage=Math.min(S.drillPage,pages);
    $('#drillSummary').textContent=`${S.owner} · ${S.start} — ${S.end} · ${integer(t.count)} 笔，汇总流入 ${money(t.inflow)}，流出 ${money(t.outflow)}，消费净额 ${money(t.spending)}，已确认退款冲减 ${money(E.sum(S.drill,'refund_adjustment_cents'))}。以下为按日和对象聚合的依据，无订单或详细备注。`;
    const rs=[...S.drill].sort((a,b)=>b.date.localeCompare(a.date)).slice((S.drillPage-1)*25,S.drillPage*25);
    $('#drillTable').innerHTML=`<table><thead><tr><th>日期</th><th>对象 / 来源</th><th>性质 / 依据</th><th class="number">流入</th><th class="number">流出</th><th class="number">消费净额</th><th class="number">退款冲减</th><th class="number">笔数</th></tr></thead><tbody>${rs.map(r=>`<tr><td>${r.date}</td><td class="party-name">${esc(r.party)}<br><span class="muted small">${sourceNames[r.source]}</span></td><td class="party-name">${esc(r.category)}<br><span class="muted small">${esc(r.kind)} · ${esc(r.basis)}</span></td><td class="number">${money(r.in_cents)}</td><td class="number">${money(r.out_cents)}</td><td class="number">${money(r.spending_cents)}</td><td class="number">${money(r.refund_adjustment_cents)}</td><td class="number">${r.count}</td></tr>`).join('')}</tbody></table>`;
    $('#drillPage').textContent=`${S.drillPage} / ${pages} 页 · ${S.drill.length} 个聚合组`;$('#prevDrill').disabled=S.drillPage<=1;$('#nextDrill').disabled=S.drillPage>=pages;
  }
  function download(name,data){const blob=new Blob([E.csv(data)],{type:'text/csv;charset=utf-8'}),url=URL.createObjectURL(blob),a=document.createElement('a');a.href=url;a.download=name;a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);toast('已导出当前筛选范围');}
  function reportRows(){return E.periods(rows,S.granularity).map(r=>({'人员':S.owner,'账本':sourceNames[S.source],'期间':r.label,'账单流入(元)':r.inflow/100,'账单流出(元)':r.outflow/100,'可识别收入(元)':r.earned/100,'消费净额(元)':r.spending/100,'往来流入(元)':r.received/100,'往来转出(元)':r.sent/100,'退款(元)':r.refunds/100,'记录数':r.count}));}
  function setPeriod(period){let from,to;const year=Number(period.slice(0,4));if(period.includes('Q')){const q=Number(period.slice(-1));from=`${year}-${String(q*3-2).padStart(2,'0')}-01`;to=new Date(Date.UTC(year,q*3,0)).toISOString().slice(0,10);}else if(period.length===4){from=period+'-01-01';to=period+'-12-31';}else{from=period+'-01';to=new Date(Date.UTC(year,Number(period.slice(5)),0)).toISOString().slice(0,10);}S.start=from;S.end=to>range().end?range().end:to;S.page=1;dates();render();}
  function bind(){
    document.addEventListener('click',e=>{const p=e.target.closest('[data-owner]'),c=e.target.closest('[data-source]'),d=e.target.closest('[data-drill]'),period=e.target.closest('[data-period]'),preset=e.target.closest('[data-year]');
      if(p){S.owner=p.dataset.owner;S.source='platform';S.page=1;buildControls();render();}
      else if(c)changeSource(c.dataset.source);
      else if(d){const a=actionMap.get(d.dataset.drill);if(a)drill(a.filter,a.title);}
      else if(period)setPeriod(period.dataset.period);
      else if(preset){const y=preset.dataset.year,b=range();S.start=y==='all'?b.start:y+'-01-01';S.end=y==='all'?b.end:(y+'-12-31'>b.end?b.end:y+'-12-31');S.page=1;buildControls();render();}
    });
    document.addEventListener('keydown',e=>{if(e.key==='Enter'&&e.target.matches('[data-period]'))setPeriod(e.target.dataset.period);});
    $('#sourceSelect').addEventListener('change',e=>changeSource(e.target.value));
    $('#applyDates').addEventListener('click',()=>{const start=$('#startDate').value,end=$('#endDate').value;if(!start||!end||start>end){$('#filterError').textContent='请选择有效日期，开始日期不能晚于结束日期。';$('#filterError').hidden=false;return;}S.start=start;S.end=end;S.page=1;render();});
    $('#granularity').addEventListener('change',e=>{S.granularity=e.target.value;render();});
    $('#comparison').addEventListener('change',e=>{S.comparison=e.target.value;render();});
    $('#trendLegend').addEventListener('click',e=>{const b=e.target.closest('[data-series]');if(!b)return;const k=b.dataset.series;if(S.series.has(k))S.series.delete(k);else S.series.add(k);b.classList.toggle('active',S.series.has(k));b.setAttribute('aria-pressed',S.series.has(k));renderTrend();});
    for(const id of ['partySearch','partyMode','partySort'])$('#'+id).addEventListener(id==='partySearch'?'input':'change',()=>{S.page=1;renderPeople();});
    $('#prevParty').onclick=()=>{S.page--;renderPeople();};$('#nextParty').onclick=()=>{S.page++;renderPeople();};
    $('#closeDrill').onclick=()=>$('#drillDialog').close();$('#prevDrill').onclick=()=>{S.drillPage--;renderDrill();};$('#nextDrill').onclick=()=>{S.drillPage++;renderDrill();};
    $('#exportPeople').onclick=()=>download('往来对象汇总.csv',persons.map(p=>({'人员':S.owner,'对象':p.label,'来源':sourceNames[p.source],'开始日期':S.start,'结束日期':S.end,'流入(元)':p.income/100,'流出(元)':p.expense/100,'净流入(元)':p.net/100,'笔数':p.count})));
    $('#exportDrill').onclick=()=>download('计算依据汇总.csv',S.drill.map(r=>({'日期':r.date,'人员':r.owner,'来源':sourceNames[r.source],'对象':r.party,'分类':r.category,'依据':r.basis,'流入(元)':r.in_cents/100,'流出(元)':r.out_cents/100,'消费净额(元)':r.spending_cents/100,'退款冲减(元)':r.refund_adjustment_cents/100,'笔数':r.count})));
    $('#exportReport').onclick=()=>download('财务分析报告.csv',reportRows());$('#printReport').onclick=()=>window.print();
    $('#shareFilter').onclick=async()=>{try{await navigator.clipboard.writeText(location.href);toast('已复制含人员、日期和账本的视图链接');}catch{toast('请复制浏览器地址栏中的当前视图链接');}};
  }
  async function init(){
    try{const response=await fetch('data/analytics.json',{cache:'no-store'});if(!response.ok)throw new Error('账单聚合数据加载失败');S.data=await response.json();
      if(!S.data.owners.length)throw new Error('尚无可分析的账单，请先运行本地分析脚本');
      const q=new URLSearchParams(location.search);S.owner=S.data.owners.includes(q.get('owner'))?q.get('owner'):S.data.owners[0];S.source=q.get('source')||'platform';buildControls();
      const b=range();S.start=q.get('from')||`${b.end.slice(0,4)}-01-01`;S.end=q.get('to')||b.end;
      if(!/^\d{4}-\d{2}-\d{2}$/.test(S.start)||!/^\d{4}-\d{2}-\d{2}$/.test(S.end)||S.start>S.end){S.start=b.start;S.end=b.end;}
      dates();bind();render();
    }catch(error){$('#appError').hidden=false;$('#appError').textContent=error.message+'。请刷新或稍后重试。';$('#dataStatus').textContent='数据未加载';console.error(error);}
  }
  init();
})();
