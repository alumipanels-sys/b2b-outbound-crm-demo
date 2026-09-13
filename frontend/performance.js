var perfPeriod = 'week';

async function RPerformance(p){
  p.innerHTML = '<div class="empty-state card">Loading performance dashboard...</div>';
  var data;
  var sampleData = {funnel:[], cards:[]};
  try{
    data = await api('/performance/dashboard?period=' + encodeURIComponent(perfPeriod));
    sampleData = await api('/sample/funnel').catch(function(){return {funnel:[], cards:[]};});
  }catch(e){
    p.innerHTML = '<div class="empty-state card" style="color:#dc2626">Load failed: '+E(e.detail||e.message||String(e))+'</div>';
    return;
  }

  var o = data.overview || {};
  var h = '<div class="flex jcs aic mb3">';
  h += '<div><h2 class="fs20 fwb">Performance</h2><p class="fs12 c6 mt2">Resource allocation and conversion: funnel, trends, profile cycle time, channel output.</p></div>';
  h += '<div class="flex g2"><button class="btn btn-sm" style="background:'+(perfPeriod==='week'?'#2563eb':'#e5e7eb')+';color:'+(perfPeriod==='week'?'#fff':'#374151')+'" id="perfWeek">Weekly</button><button class="btn btn-sm" style="background:'+(perfPeriod==='month'?'#2563eb':'#e5e7eb')+';color:'+(perfPeriod==='month'?'#fff':'#374151')+'" id="perfMonth">Monthly</button><button class="btn btn-sm" style="background:#64748b" id="perfRefresh">Refresh</button></div>';
  h += '</div>';

  h += '<div style="display:grid;grid-template-columns:repeat(4,minmax(150px,1fr));gap:12px;margin-bottom:16px">';
  h += perfMetric('Active customers', o.active_prospects||0, 'Reached '+(o.contacted_prospects||0), '#2563eb');
  h += perfMetric('Reply rate', (o.reply_rate||0)+'%', (o.replied_prospects||0)+' customers replied'+(o.bounced_prospects?' · '+o.bounced_prospects+' bounced':''), '#16a34a');
  h += perfMetric('Actionable replies', o.actionable_replies||0, 'Quotes / samples / partnerships / referrals', '#f97316');
  h += perfMetric('Won customers', o.won_prospects||0, 'Win rate '+(o.won_rate||0)+'%', '#7c3aed');
  h += '</div>';

  h += '<div style="display:grid;grid-template-columns:1fr 1fr;gap:14px;margin-bottom:16px">';
  h += '<div class="card p3"><div class="sec-hd">Customer conversion funnel</div>'+perfFunnel(data.funnel||[])+'</div>';
  h += '<div class="card p3"><div class="sec-hd">Sample conversion funnel</div>'+perfSampleFunnel(sampleData.funnel||[])+'</div>';
  h += '</div>';

  h += '<div style="display:grid;grid-template-columns:1fr 1fr;gap:14px;margin-bottom:16px">';
  h += '<div class="card p3"><div class="sec-hd">Outreach trend</div>'+perfTrend(data.trends||[])+'</div>';
  h += '<div class="card p3"><div class="sec-hd">Sample follow-up list</div>'+perfSampleCards(sampleData.cards||[])+'</div>';
  h += '</div>';

  h += '<div style="display:grid;grid-template-columns:1.1fr .9fr;gap:14px;margin-bottom:16px">';
  h += '<div class="card p3"><div class="sec-hd">Profile performance</div>'+perfProfileTable(data.profiles||[])+'</div>';
  h += '<div class="card p3"><div class="sec-hd">Channel efficiency</div>'+perfChannelTable(data.channels||[])+'</div>';
  h += '</div>';

  // Methodology effectiveness (feedback loop)
  var meths = data.methodologies || [];
  if (meths.length > 0) {
    h += '<div class="card p3 mb3"><div class="sec-hd">Methodology effectiveness <span style="font-weight:400;font-size:11px;color:#64748b">(reply &amp; win rates attributed by methodology)</span></div>';
    h += perfMethodTable(meths);
    h += '</div>';
  }

  h += '<div class="card p3" style="background:#f8fafc">';
  h += '<div class="sec-hd" style="margin-bottom:8px">Business insights</div>';
  h += perfInsight(data);
  h += '</div>';

  p.innerHTML = h;
  bindSafe(p, '#perfWeek', 'click', function(){perfPeriod='week';RPerformance(p);});
  bindSafe(p, '#perfMonth', 'click', function(){perfPeriod='month';RPerformance(p);});
  bindSafe(p, '#perfRefresh', 'click', function(){RPerformance(p);});
}

function perfMetric(label, value, sub, color){
  return '<div class="stat-card" style="--stat-color:'+color+'"><div class="stat-label">'+E(label)+'</div><div class="stat-value-wrapper"><span class="stat-value">'+E(value)+'</span></div><div class="fs11" style="color:#64748b;margin-top:2px">'+E(sub||'')+'</div></div>';
}

function perfFunnel(rows){
  if(!rows.length)return '<div class="tc c6 p3">No funnel data yet</div>';
  var max = Math.max.apply(null, rows.map(function(r){return r.count||0;})) || 1;
  var colors = ['#3b82f6','#8b5cf6','#16a34a','#f97316','#64748b'];
  var h = '';
  rows.forEach(function(r,i){
    var pct = Math.max(4, Math.round((r.count||0)/max*100));
    h += '<div style="margin-bottom:10px">';
    h += '<div class="flex jcs fs12 mb1"><span class="fwm">'+E(r.stage)+'</span><span class="c6">'+E(r.count)+' · share '+E(r.share)+'%</span></div>';
    h += '<div style="height:22px;background:#f8fafc;border-radius:4px;overflow:hidden"><div style="height:100%;width:'+pct+'%;background:'+(colors[i]||'#64748b')+'"></div></div>';
    h += '</div>';
  });
  return h;
}

function perfSampleFunnel(rows){
  if(!rows.length)return '<div class="tc c6 p3">No sample data yet</div>';
  var max = Math.max.apply(null, rows.map(function(r){return r.count||0;})) || 1;
  var colors = ['#2563eb','#3b82f6','#8b5cf6','#ec4899','#16a34a','#059669','#64748b','#dc2626'];
  var h = '';
  rows.forEach(function(r,i){
    var pct = Math.max(4, Math.round((r.count||0)/max*100));
    h += '<div style="margin-bottom:9px">';
    h += '<div class="flex jcs fs12 mb1"><span class="fwm">'+E(r.label||r.stage)+'</span><span class="c6">'+E(r.count)+'</span></div>';
    h += '<div style="height:18px;background:#f8fafc;border-radius:4px;overflow:hidden"><div style="height:100%;width:'+pct+'%;background:'+(colors[i]||'#64748b')+'"></div></div>';
    h += '</div>';
  });
  return h;
}

function perfSampleCards(rows){
  if(!rows.length)return '<div class="tc c6 p3">No sample follow-ups yet</div>';
  var h = '';
  rows.slice(0,8).forEach(function(r){
    var urgent = r.days_until != null && r.days_until <= 1;
    h += '<div style="padding:9px 10px;margin-bottom:7px;border-left:3px solid '+(urgent?'#f97316':'#2563eb')+';background:'+(urgent?'#fff7ed':'#fff')+';border-radius:4px">';
    h += '<div class="flex jcs aic"><span class="fwm fs12" style="color:#2563eb;cursor:pointer" onclick="openDrawer('+r.prospect_id+')">'+E(r.company||'')+'</span><span class="badge" style="background:#dbeafe;color:#1d4ed8">'+E(r.stage_label||r.stage)+'</span></div>';
    h += '<div class="fs11 c6 mt1">Follow-up '+E(r.next_follow_date||'-')+(r.reminder_note?' · '+E(r.reminder_note).substring(0,70):'')+'</div>';
    h += '</div>';
  });
  return h;
}

function perfTrend(rows){
  if(!rows.length)return '<div class="tc c6 p3">No trend data yet</div>';
  var max = Math.max.apply(null, rows.map(function(r){return Math.max(r.outbound||0,r.inbound||0,r.email_sent||0);})) || 1;
  var h = '<div style="display:flex;align-items:flex-end;gap:8px;height:190px;border-bottom:1px solid #e5e7eb;padding:0 4px 8px">';
  rows.forEach(function(r){
    var outH = Math.max(4, Math.round((r.outbound||0)/max*145));
    var inH = Math.max(4, Math.round((r.inbound||0)/max*145));
    h += '<div style="flex:1;min-width:36px;text-align:center">';
    h += '<div style="height:150px;display:flex;align-items:flex-end;justify-content:center;gap:3px">';
    h += '<div title="Outreach '+E(r.outbound||0)+'" style="width:10px;height:'+outH+'px;background:#2563eb;border-radius:3px 3px 0 0"></div>';
    h += '<div title="Replies '+E(r.inbound||0)+'" style="width:10px;height:'+inH+'px;background:#16a34a;border-radius:3px 3px 0 0"></div>';
    h += '</div><div class="fs11 c6" style="white-space:nowrap;overflow:hidden;text-overflow:ellipsis">'+E(r.period)+'</div>';
    h += '</div>';
  });
  h += '</div><div class="fs11 c6 mt2"><span style="color:#2563eb">Blue</span> outreach, <span style="color:#16a34a">green</span> replies</div>';
  return h;
}

function perfProfileTable(rows){
  if(!rows.length)return '<div class="tc c6 p3">No profile data yet</div>';
  var h = '<table><thead><tr><th>Profile</th><th>Customers</th><th>Reached</th><th>Reply rate</th><th>Won</th><th>Avg. reply cycle</th></tr></thead><tbody>';
  rows.forEach(function(r){
    h += '<tr><td class="fwm">'+E(r.profile)+'</td><td>'+E(r.prospects)+'</td><td>'+E(r.contacted)+'</td><td><span class="badge" style="background:'+(r.reply_rate>=20?'#dcfce7;color:#166534':'#f1f5f9;color:#475569')+'">'+E(r.reply_rate)+'%</span></td><td>'+E(r.won)+'</td><td>'+E(r.avg_days_to_reply==null?'-':r.avg_days_to_reply+' days')+'</td></tr>';
  });
  return h+'</tbody></table>';
}

function perfChannelTable(rows){
  if(!rows.length)return '<div class="tc c6 p3">No channel data yet</div>';
  var h = '<table><thead><tr><th>Channel</th><th>Outreach</th><th>Replies</th><th>Customer reply rate</th></tr></thead><tbody>';
  rows.forEach(function(r){
    h += '<tr><td class="fwm">'+E(perfChannelLabel(r.channel))+'</td><td>'+E(r.outbound)+'</td><td>'+E(r.inbound)+'</td><td>'+E(r.reply_rate)+'%</td></tr>';
  });
  return h+'</tbody></table>';
}

function perfChannelLabel(v){
  var map={email:'Email',linkedin:'LinkedIn',whatsapp:'WhatsApp',phone:'Phone',note:'Note',unknown:'Unknown'};
  return map[v]||v||'Unknown';
}

function perfMethodTable(rows){
  if(!rows.length)return '<div class="tc c6 p3">No methodology data yet (needs outbound records for attribution)</div>';
  var h = '<table style="width:100%"><thead><tr><th>Methodology</th><th class="ta">Sent</th><th class="ta">Customers</th><th class="ta">Replies</th><th class="ta">Reply rate</th><th class="ta">Samples</th><th class="ta">Won</th></tr></thead><tbody>';
  rows.forEach(function(r){
    var replyColor = r.reply_rate >= 15 ? '#dcfce7;color:#166534' : '#f1f5f9;color:#475569';
    var wonColor = r.won_count > 0 ? '#fef3c7;color:#92400e' : '#f1f5f9;color:#64748b';
    h += '<tr>';
    h += '<td class="fs12" style="max-width:260px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap" title="'+E(r.title)+'">'+E(r.title)+'</td>';
    h += '<td class="ta c6">'+E(r.outbound_count)+'</td>';
    h += '<td class="ta c6">'+E(r.prospect_count)+'</td>';
    h += '<td class="ta fwm">'+E(r.replied_count)+'</td>';
    h += '<td class="ta"><span class="badge" style="background:'+replyColor+'">'+E(r.reply_rate)+'%</span></td>';
    h += '<td class="ta">'+E(r.sample_count||0)+'</td>';
    h += '<td class="ta"><span class="badge" style="background:'+wonColor+'">'+E(r.won_count||0)+'</span></td>';
    h += '</tr>';
  });
  return h+'</tbody></table>';
}

function perfInsight(data){
  var profiles = (data.profiles||[]).filter(function(r){return r.contacted>0;});
  var best = profiles.slice().sort(function(a,b){return (b.reply_rate||0)-(a.reply_rate||0);})[0];
  var slow = profiles.filter(function(r){return r.avg_days_to_reply!=null;}).sort(function(a,b){return (b.avg_days_to_reply||0)-(a.avg_days_to_reply||0);})[0];
  var channels = (data.channels||[]).filter(function(r){return r.contacted_prospects>0;});
  var bestCh = channels.slice().sort(function(a,b){return (b.reply_rate||0)-(a.reply_rate||0);})[0];
  var parts = [];
  if(best)parts.push('Profile with the highest reply rate: '+best.profile+' ('+best.reply_rate+'%) — review its messaging and lead sources first.');
  if(slow)parts.push(slow.profile+' has the longest reply cycle ('+slow.avg_days_to_reply+' days) — reduce email frequency and add trade-show/case-study angles.');
  if(bestCh)parts.push('Best channel by customer reply rate: '+perfChannelLabel(bestCh.channel)+' ('+bestCh.reply_rate+'%) — allocate more similar profiles to it.');
  if(!parts.length)parts.push('Not enough data for a stable read yet — keep building outreach and reply records.');
  return '<div class="fs12" style="line-height:1.7;color:#334155">'+parts.map(function(x){return '<div>- '+E(x)+'</div>';}).join('')+'</div>';
}
