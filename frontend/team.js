// Team work dashboard: the owner's "top supervisor" view
// Each member: customer pool state (assigned / not started / following / due) + output (sent / reply rate / new / deals / won) + sensitive actions

var _teamDays = parseInt(localStorage.getItem('td_team_days') || '1', 10);

async function RTeam(p){
  p.innerHTML = '<div class="empty-state card">Loading...</div>';
  var data, tgt;
  try{
    var res = await Promise.all([
      api('/ops/team-dashboard?days=' + _teamDays),
      api('/ops/team-targets')
    ]);
    data = res[0]; tgt = res[1];
  }catch(e){
    p.innerHTML = '<div class="card tc p4" style="color:#dc2626">'+E(e.detail||e.message||String(e))+'</div>';
    return;
  }
  var rows = data.rows || [];
  var t = data.totals || {};
  var periodLabel = _teamDays === 1 ? 'Today' : (_teamDays === 7 ? 'This week' : 'This month');

  var h = '<div class="page-hd" style="align-items:center">';
  h += '<div><h2>Team Work Dashboard</h2><p class="page-sub">Owner view: who owns the pipeline, who is working, whether it works, and any high-risk actions.</p></div>';
  h += '<div class="flex g2">';
  h += '<button class="btn btn-sm ' + (_teamDays===1?'btn-pri':'btn-b') + '" data-team-days="1">Today</button>';
  h += '<button class="btn btn-sm ' + (_teamDays===7?'btn-pri':'btn-b') + '" data-team-days="7">Week</button>';
  h += '<button class="btn btn-sm ' + (_teamDays===30?'btn-pri':'btn-b') + '" data-team-days="30">Month</button>';
  h += '</div></div>';

  // Summary stats
  h += '<div style="display:flex;gap:10px;margin-bottom:18px;flex-wrap:wrap">';
  h += teamStat('Assigned customers', t.prospects || 0, '#2563eb', 'Total customer resources');
  h += teamStat('Not started', t.not_started || 0, '#f97316', 'Not touched — assign or develop');
  h += teamStat('Following up', t.following || 0, '#0891b2', 'Contacted and in progress');
  h += teamStat('Due follow-ups', t.need_followup || 0, '#dc2626', 'Should have been followed');
  h += teamStat(periodLabel+' emails sent', t.sent || 0, '#6366f1', 'Cold emails sent');
  h += teamStat(periodLabel+' new', t.new_customers || 0, '#16a34a', 'Including '+ (t.imports||0) +' imported');
  h += '</div>';

  // Weekly new-touch target (owner check view)
  h += targetSection(tgt);

  // Member detail table
  h += '<div class="card" style="overflow:hidden">';
  h += '<div style="padding:12px 16px;background:#f7f9fc;border-bottom:1px solid #e4e9f2;display:flex;align-items:center;gap:8px">';
  h += '<span class="dot" style="width:8px;height:8px;border-radius:50%;background:#2563eb"></span>';
  h += '<span class="fs14 fwb" style="color:#0f172a">' + periodLabel + ' member details</span>';
  h += '<span class="fs11 c6">Reply rate = customers with real replies ÷ customers reached (bounces excluded)</span></div>';
  h += '<div style="padding:6px 12px" class="oa">';
  if(!rows.length){
    h += '<div class="fs12 c6 tc" style="padding:20px">No member data yet</div>';
  }else{
    h += '<table style="min-width:1200px"><thead><tr>';
    h += '<th>Member</th><th>Assigned</th><th>Not started</th><th>Following</th><th>Due</th>';
    h += '<th>Sent</th><th>Replies (rate)</th><th>'+periodLabel+' new</th><th>Imports</th><th>Deals</th><th>Won</th><th>Sensitive actions</th>';
    h += '</tr></thead><tbody>';
    rows.forEach(function(r){
      var isUnassigned = r.user_id === null || r.user_id === undefined;
      var roleTxt = ({owner:'Owner', admin:'Admin', member:'Member'})[r.role] || r.role;
      var noAction = !isUnassigned && !(r.sent||0) && !(r.replies||0) && !(r.new_customers||0) && !(r.deals||0) && !(r.won||0);
      h += '<tr'+(isUnassigned?' style="background:#fffbeb"':'')+'>';
      h += '<td><b>'+E(r.name)+'</b> <span class="badge" style="background:#e0e7ff;color:#3730a3">'+roleTxt+'</span>';
      if(noAction) h += ' <span class="badge" style="background:#f1f5f9;color:#94a3b8">No activity</span>';
      if(isUnassigned) h += ' <span class="badge" style="background:#fef3c7;color:#92400e">⚠ Unassigned</span>';
      h += '</td>';
      h += '<td>'+E(r.prospects||0)+'</td>';
      h += '<td style="color:'+(r.not_started>0?'#f97316':'#94a3b8')+'">'+E(r.not_started||0)+'</td>';
      h += '<td style="color:#0891b2">'+E(r.following||0)+'</td>';
      h += '<td style="color:'+(r.need_followup>0?'#dc2626':'#94a3b8')+'">'+E(r.need_followup||0)+'</td>';
      h += '<td>'+E(r.sent||0)+'</td>';
      h += '<td>'+E(r.replies||0)+' <span class="fs11" style="color:'+((r.reply_rate||0)>=20?'#16a34a':(r.reply_rate||0)>0?'#f59e0b':'#94a3b8')+'">('+E(r.reply_rate||0)+'%)</span></td>';
      h += '<td>'+E(r.new_customers||0)+'</td>';
      h += '<td style="color:'+(r.imports>0?'#16a34a':'#94a3b8')+'">'+E(r.imports||0)+'</td>';
      h += '<td>'+E(r.deals||0)+'</td>';
      h += '<td style="color:#7c3aed;font-weight:600">'+E(r.won||0)+'</td>';
      h += '<td>'+(r.sensitive>0
        ? '<span class="badge" style="background:#fee2e2;color:#dc2626;font-weight:700">⚠ Delete/export '+r.sensitive+'</span>'
        : '<span class="fs11 c6">-</span>')+'</td>';
      h += '</tr>';
    });
    h += '</tbody></table>';
  }
  h += '</div></div>';

  h += '<div class="fs11 c6 mt2">Sensitive actions = delete customer / export data / restore data (auto-logged in Audit Log; this is only a reminder).</div>';
  p.innerHTML = h;

  p.querySelectorAll('[data-team-days]').forEach(function(b){
    b.addEventListener('click', function(){
      _teamDays = parseInt(b.dataset.teamDays, 10);
      localStorage.setItem('td_team_days', String(_teamDays));
      RTeam(p);
    });
  });

  p.querySelectorAll('[data-set-target]').forEach(function(b){
    b.addEventListener('click', async function(){
      var uid = b.dataset.setTarget;
      var cur = b.dataset.cur;
      var v = prompt('Set this member\'s daily new-touch target (recommended 3-5; sending is not limited):', cur);
      if(v === null) return;
      var n = parseInt(v, 10);
      if(!n || n < 1 || n > 99){ T('Enter a number from 1-99','#dc2626'); return; }
      b.disabled = true;
      try{
        await api('/ops/team-targets/' + uid + '?target=' + n, {method:'PUT'});
        T('Updated: '+n+' new touches per day','#16a34a');
        RTeam(p);
      }catch(e){
        T(e.detail || e.message || 'Update failed','#dc2626');
        b.disabled = false;
      }
    });
  });
}

function teamStat(label, val, color, sub){
  return '<div class="stat-card" style="--stat-color:'+color+'"><div class="stat-label">'+label+'</div>'
    + '<div class="stat-value-wrapper"><span class="stat-value">'+(val||0)+'</span></div>'
    + '<div class="fs11" style="color:#64748b;margin-top:2px">'+E(sub||'')+'</div></div>';
}

function targetSection(tgt){
  var rows = (tgt && tgt.rows) || [];
  if(!rows.length) return '';
  var sendDays = ((tgt.send_days)||[]).join(', ');
  var h = '<div class="card" style="margin-bottom:18px">';
  h += '<div style="padding:12px 16px;background:#f7f9fc;border-bottom:1px solid #e4e9f2;display:flex;align-items:center;gap:8px;flex-wrap:wrap">';
  h += '<span style="font-size:14px;font-weight:700;color:#0f172a">🎯 Weekly new-touch target</span>';
  h += '<span class="fs11 c6">Send days '+sendDays+' · first cold email per customer counts 1 · pre-scheduled counts · bounces count · sending not limited</span></div>';
  h += '<div style="padding:4px 16px 12px">';
  rows.forEach(function(r){
    var wk = r.weekly_target || 0;
    var total = (r.week_touched||0) + (r.week_scheduled||0);
    var pct = wk ? Math.min(100, Math.round(total / wk * 100)) : 0;
    var barColor = r.weekly_done ? '#16a34a' : (pct >= 70 ? '#f59e0b' : '#dc2626');
    var detail = ((r.days||[]).filter(function(d){ return d.is_send_day; }).map(function(d){
      return (d.weekday_en || d.weekday_cn) + ' ' + d.touched + '/' + d.target + (d.done ? ' ✅' : '');
    })).join(' · ');
    var roleTxt = ({owner:'Owner', admin:'Admin', member:'Member'})[r.role] || r.role || '';
    h += '<div style="display:flex;align-items:center;gap:12px;padding:10px 0;border-bottom:1px dashed #eef2f7;flex-wrap:wrap">';
    h += '<div style="min-width:110px"><b>'+E(r.name)+'</b> <span class="fs11 c6">'+roleTxt+'</span></div>';
    h += '<div style="flex:1;min-width:160px">';
    h += '<div style="display:flex;justify-content:space-between;font-size:11px;margin-bottom:3px"><span>Week '+E(total)+' / '+E(wk)+(r.week_scheduled ? ' (scheduled '+r.week_scheduled+')' : '')+'</span><span>'+pct+'%</span></div>';
    h += '<div style="height:6px;background:#eef2f7;border-radius:99px;overflow:hidden"><div style="width:'+pct+'%;height:100%;background:'+barColor+';border-radius:99px"></div></div>';
    h += '</div>';
    h += '<div class="fs11" style="color:#64748b">'+detail+'</div>';
    h += '<button class="btn btn-sm btn-b" data-set-target="'+r.user_id+'" data-cur="'+r.target_per_day+'">Target '+r.target_per_day+'/day</button>';
    h += '</div>';
  });
  var maxT = rows.reduce(function(a,r){ return Math.max(a, r.target_per_day||0); }, 0);
  if(maxT > 5){
    h += '<div class="fs11" style="background:#fef9c3;border:1px solid #fde68a;color:#92400e;padding:8px 10px;border-radius:8px;margin-top:10px">⚠️ A member target exceeds 5/day: heavy sending can land in spam or trigger mailbox risk controls. Keep 3-5/day. The system does not enforce this — please understand the risk.</div>';
  }else{
    h += '<div class="fs11" style="color:#94a3b8;margin-top:8px">Targets are displayed for motivation only; the system does not block sending. Recommended 3-5/day — steady consistency beats bursts.</div>';
  }
  h += '</div></div>';
  return h;
}
