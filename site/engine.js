/* 统一的筛选、聚合和比较逻辑；浏览器与 Node 测试共用。 */
(function(root,factory){const api=factory();if(typeof module==='object'&&module.exports)module.exports=api;else root.Finance=api;})(globalThis,()=>{
  const n=v=>Number(v||0), sum=(r,k)=>r.reduce((s,x)=>s+n(x[k]),0);
  function select(records,f){
    if(f.start&&f.end&&f.start>f.end)throw new Error('开始日期不能晚于结束日期');
    return records.filter(r=>(!f.owner||r.owner===f.owner)&&(!f.source||(f.source==='platform'?r.source!=='cmb':r.source===f.source))&&(!f.start||r.date>=f.start)&&(!f.end||r.date<=f.end));
  }
  function totals(rows){const valid=rows.filter(r=>r.nature!=='void');return {
    count:sum(rows,'count'),validCount:sum(valid,'count'),expenseCount:sum(valid.filter(r=>r.nature==='consume'&&r.out_cents>0),'count'),
    inflow:sum(valid,'in_cents'),outflow:sum(valid,'out_cents'),neutral:sum(valid,'neutral_cents'),
    earned:sum(valid,'earned_cents'),spending:sum(valid,'spending_cents'),received:sum(valid,'transfer_in_cents'),sent:sum(valid,'transfer_out_cents'),
    refunds:sum(valid,'refund_cents'),assetIn:sum(valid.filter(r=>r.nature==='asset'),'in_cents'),
    unknown:sum(valid.filter(r=>r.nature==='unknown'),'in_cents'),unknownSpend:sum(valid.filter(r=>/待确认/.test(r.category)),'spending_cents'),
    smallCount:sum(valid,'small_count'),smallAmount:sum(valid,'small_cents'),net:sum(valid,'in_cents')-sum(valid,'out_cents')};}
  function group(rows,key,metric){const m=new Map();for(const r of rows){const k=r[key]||'未分类';if(!m.has(k))m.set(k,{label:k,amount:0,count:0});const v=m.get(k);v.amount+=n(r[metric]);v.count+=n(r.count);}return [...m.values()].sort((a,b)=>b.amount-a.amount||a.label.localeCompare(b.label,'zh'));}
  function periods(rows,unit='month'){
    const m=new Map();for(const r of rows){const label=unit==='year'?r.date.slice(0,4):unit==='quarter'?`${r.date.slice(0,4)}-Q${Math.ceil(Number(r.date.slice(5,7))/3)}`:r.date.slice(0,7);if(!m.has(label))m.set(label,[]);m.get(label).push(r);}
    return [...m].sort(([a],[b])=>a.localeCompare(b)).map(([label,rs])=>({label,...totals(rs)}));
  }
  const iso=d=>d.toISOString().slice(0,10), day=s=>new Date(`${s}T00:00:00Z`), days=(a,b)=>Math.round((day(b)-day(a))/86400000)+1;
  function previousYear(s){const y=Number(s.slice(0,4))-1,month=Number(s.slice(5,7)),date=Number(s.slice(8,10));return iso(new Date(Date.UTC(y,month-1,Math.min(date,new Date(Date.UTC(y,month,0)).getUTCDate()))));}
  function comparisonRange(start,end,kind='previous'){
    if(kind==='year')return{start:previousYear(start),end:previousYear(end)};
    const span=days(start,end);const to=day(start);to.setUTCDate(to.getUTCDate()-1);const from=new Date(to);from.setUTCDate(from.getUTCDate()-span+1);return{start:iso(from),end:iso(to)};
  }
  const comparable=(current,prior,bounds)=>[current,prior].every(r=>r.start>=bounds.start&&r.end<=bounds.end);
  const change=(now,before)=>before===0?null:(now-before)/Math.abs(before);
  function changes(current,previous){const a=group(current,'category','spending_cents'),b=group(previous,'category','spending_cents'), labels=[...new Set([...a,...b].map(x=>x.label))];return labels.map(label=>{const now=a.find(x=>x.label===label)?.amount||0,before=b.find(x=>x.label===label)?.amount||0;return{label,now,before,delta:now-before,rate:change(now,before)};}).sort((a,b)=>Math.abs(b.delta)-Math.abs(a.delta));}
  function parties(rows,transferOnly=false){const m=new Map();for(const r of rows){if(r.nature==='void'||(transferOnly&&r.nature!=='received'))continue;const k=`${r.owner}|${r.source}|${r.party_id}`;if(!m.has(k))m.set(k,{id:k,label:r.party,owner:r.owner,source:r.source,income:0,expense:0,count:0});const x=m.get(k);x.income+=n(transferOnly?r.transfer_in_cents:r.in_cents);x.expense+=n(transferOnly?r.transfer_out_cents:r.out_cents);x.count+=n(r.count);}return [...m.values()].map(x=>({...x,net:x.income-x.expense})).sort((a,b)=>Math.abs(b.net)-Math.abs(a.net));}
  function recurring(rows){const m=new Map();for(const r of rows){if(r.nature!=='consume'||r.spending_cents<=0)continue;const key=`${r.owner}|${r.source}|${r.party_id}`;if(!m.has(key))m.set(key,{label:r.party,source:r.source,owner:r.owner,party_id:r.party_id,months:new Map()});const item=m.get(key),mo=r.date.slice(0,7);if(!item.months.has(mo))item.months.set(mo,{amount:0,count:0});const v=item.months.get(mo);v.amount+=r.spending_cents;v.count+=r.count;}
    return [...m.values()].flatMap(v=>{const ms=[...v.months.values()];if(ms.length<3||ms.some(x=>x.count>2))return[];const avg=ms.reduce((s,x)=>s+x.amount,0)/ms.length;const cv=Math.sqrt(ms.reduce((s,x)=>s+(x.amount-avg)**2,0)/ms.length)/avg;if(cv>.2)return[];return[{label:v.label,source:v.source,party_id:v.party_id,months:ms.length,average:Math.round(avg),variation:cv}];}).sort((a,b)=>b.average-a.average);
  }
  function largeDays(rows){const rs=rows.filter(r=>r.nature==='consume'&&r.max_spending_cents>0),values=rs.map(r=>r.max_spending_cents).sort((a,b)=>a-b);const threshold=Math.max(100000,values[Math.floor((values.length-1)*.95)]||0);return{threshold,rows:rs.filter(r=>r.max_spending_cents>=threshold).sort((a,b)=>b.max_spending_cents-a.max_spending_cents)};}
  function csv(rows){if(!rows.length)return '\ufeff';const keys=Object.keys(rows[0]),quote=v=>'"'+(typeof v==='string'?v.replace(/^[=+\-@]/,"'$&"):String(v??'')).replaceAll('"','""')+'"';return '\ufeff'+[keys.map(quote).join(','),...rows.map(r=>keys.map(k=>quote(r[k])).join(','))].join('\r\n');}
  return{select,totals,group,periods,days,comparisonRange,comparable,change,changes,parties,recurring,largeDays,csv,sum};
});
