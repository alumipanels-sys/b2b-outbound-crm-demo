// Today Workbench: daily outreach cockpit

async function RToday(p) {
  var dp = {};
  try { dp = await api('/prospects/daily-plan'); } catch (e) { T('Failed to load', '#dc2626'); dp = {}; }
  var tgt = null;
  try { tgt = await api('/ops/team-targets'); } catch (e) { tgt = null; }

  var nc = dp.new_outreach_count || 0;
  var odc = dp.overdue_count || 0;
  var dtc = dp.due_today_count || 0;
  var upc = dp.upcoming_count || 0;

  // Header: date + greeting
  var h = '';
  h += '<div class="page-hd" style="align-items:center">';
  h += '<div><h2>' + E(dp.today_date||'') + '</h2><p class="page-sub">Handle overdue items first, then today\'s due tasks — everything below is today\'s work.</p></div>';
  h += '<button class="btn btn-sm btn-b" onclick="nav(\'reminders\')">View all follow-up tasks →</button>';
  h += '</div>';

  // Weekly new-touch target (personal view, purely motivational)
  if (tgt && tgt.weekly_target) {
    var wk = tgt.weekly_target, doneN = tgt.week_touched || 0, remain = tgt.remaining || 0;
    var schedN = tgt.week_scheduled || 0;
    var pct = wk ? Math.min(100, Math.round((doneN + schedN) / wk * 100)) : 0;
    var todayRow = tgt.days && tgt.days[tgt.days.length - 1];
    var okColor = tgt.weekly_done ? '#16a34a' : (pct >= 70 ? '#f59e0b' : '#dc2626');
    h += '<div style="background:'+(tgt.weekly_done ? '#ecfdf5' : '#fff7ed')+';border:1px solid '+(tgt.weekly_done ? '#a7f3d0' : '#fed7aa')+';border-radius:10px;padding:10px 14px;margin-bottom:16px;display:flex;align-items:center;gap:12px;flex-wrap:wrap">';
    h += '<span style="font-size:18px">🎯</span>';
    h += '<div style="flex:1;min-width:200px">';
    h += '<div style="font-size:13px;font-weight:600;color:#0f172a">This week\'s new outreach <span style="color:'+okColor+'">'+(doneN+schedN)+' / '+wk+'</span> ('+pct+'%)'+(tgt.weekly_done ? ' target reached 🎉' : ' — <b>'+remain+'</b> more needed')+'</div>';
    if (schedN > 0) h += '<div class="fs11" style="color:#0891b2;margin-top:2px">'+schedN+' email(s) already written and scheduled; they will be sent during the customer\'s working hours on send day</div>';
    if (todayRow && todayRow.is_send_day) {
      var tRemain = Math.max(0, (todayRow.target||0) - (todayRow.touched||0));
      var wdName = todayRow.weekday_en || todayRow.weekday_cn || '';
      h += '<div class="fs11" style="color:#b45309;margin-top:2px">Today ('+wdName+') target: '+todayRow.target+', completed: '+todayRow.touched+(tRemain > 0 ? ' — '+tRemain+' more needed' : ' ✅ target exceeded')+'</div>';
    } else if (todayRow && !todayRow.is_send_day) {
      h += '<div class="fs11" style="color:#94a3b8;margin-top:2px">Today is not a send day (send days: Tue/Wed/Thu), but you can write and schedule cold emails in advance — the system sends them during customer working hours.</div>';
    }
    h += '</div></div>';
  }

  // Core numbers
  h += '<div style="display:flex;gap:12px;margin-bottom:22px;flex-wrap:wrap">';
  h += todayStat('Due today', dtc, '#dc2626', 'Customers due for follow-up today');
  h += todayStat('Overdue', odc, '#f59e0b', 'The longer they wait, the harder to close');
  h += todayStat('Next 7 days', upc, '#0891b2', 'Plan ahead, develop calmly');
  h += todayStat('New today', nc, '#6366f1', 'New prospects not yet contacted');
  h += '</div>';

  // Grouped lists
  if (dp.overdue && dp.overdue.length) {
    h += wbSection('Overdue follow-ups', dp.overdue.length, '#dc2626', 'Handle these first: customers drift away if they wait too long', 'overdue');
    dp.overdue.forEach(function(f){ h += fuRow(f, 'overdue'); });
    h += '</div>';
  }

  if (dp.due_today && dp.due_today.length) {
    h += wbSection('Due today', dp.due_today.length, '#16a34a', 'Follow up with these customers today', 'today');
    dp.due_today.forEach(function(f){ h += fuRow(f, 'today'); });
    h += '</div>';
  }

  if (dp.upcoming && dp.upcoming.length) {
    h += wbSection('Upcoming follow-ups', dp.upcoming.reduce(function(a,g){return a+g.items.length;},0), '#0891b2', 'Be prepared in advance', 'upcoming');
    dp.upcoming.forEach(function(group){
      var daysUntil = group.days_until;
      var labelText = daysUntil === 0 ? 'today' : daysUntil === 1 ? 'tomorrow' : daysUntil === 2 ? 'in 2 days' : 'in ' + daysUntil + ' days';
      var dateColor = daysUntil <= 3 ? '#0891b2' : daysUntil <= 7 ? '#6366f1' : '#94a3b8';
      h += '<div style="font-size:11px;color:' + dateColor + ';font-weight:600;margin:8px 2px 6px">' + E(group.date) + ' · ' + labelText + ' (' + group.items.length + ')</div>';
      group.items.forEach(function(f){ h += fuRow(f, 'upcoming'); });
    });
    h += '</div>';
  }

  if (dp.new_outreach && dp.new_outreach.length) {
    h += wbSection('New prospects today', dp.new_outreach.length, '#6366f1', 'Just imported — click "Start" to send the first cold email', 'new');
    dp.new_outreach.forEach(function(f){ h += newOutreachRow(f); });
    h += '</div>';
  }

  if (dp.cooling_due && dp.cooling_due.length) {
    h += wbSection('Cooling customer review', dp.cooling_due.length, '#8b5cf6', 'No replies for a while — open details and decide: warm up / extend / drop', 'cooling');
    dp.cooling_due.forEach(function(f){ h += coolingRow(f); });
    h += '</div>';
  }

  if (!(dp.overdue && dp.overdue.length) && !(dp.due_today && dp.due_today.length) && !(dp.upcoming && dp.upcoming.length) && !(dp.new_outreach && dp.new_outreach.length) && !(dp.cooling_due && dp.cooling_due.length)) {
    h += '<div class="card" style="padding:36px;text-align:center;color:#94a3b8;font-size:13px">✅ No follow-ups due today — you can research prospects or refine your profiles instead.</div>';
  }

  p.innerHTML = h;

  // Event bindings
  p.querySelectorAll('[data-start-outreach]').forEach(function(b){
    b.addEventListener('click', async function(e){ e.stopPropagation();
      var pid = parseInt(b.dataset.startOutreach);
      b.disabled = true; b.textContent = '...';
      try {
        var next = new Date(); next.setDate(next.getDate()+3);
        if(next.getDay()===0) next.setDate(next.getDate()+1);
        if(next.getDay()===6) next.setDate(next.getDate()+2);
        var nextStr = next.toISOString().substring(0,10);
        await api('/prospects/'+pid, {method:'PUT', body:{
          sales_stage:'touched',
          new_outreach_date: '',
          next_follow_date: nextStr,
          reminder_note: '[New outreach] Cold email sent, follow up in 3 days'
        }});
        T('Marked as touched → next follow-up '+nextStr,'#6366f1');
        b.closest('.no-row').style.opacity='0.4';
        setTimeout(function(){RToday(p);},800);
      } catch(e){ T('Failed','#dc2626'); b.disabled=false; b.textContent = 'Start'; }
    });
  });

  p.querySelectorAll('[data-fdone]').forEach(function(b){
    b.addEventListener('click', async function(e){ e.stopPropagation();
      var pid = parseInt(b.dataset.fdone);
      b.disabled = true; b.textContent = '...';
      try {
        var r = await api('/prospects/'+pid+'/complete-followup',{method:'POST',body:{advance_days:3}});
        var nextStr = r.remaining_next_follow_date || '';
        T(nextStr ? 'Follow-up done → company next due '+nextStr : 'Follow-up done, no remaining schedule','#16a34a',4000);
        b.closest('.fu-row').style.opacity='0.4';
        setTimeout(function(){RToday(p);},500);
      } catch(e){ T('Failed','#dc2626'); b.disabled=false; b.textContent='✓'; }
    });
  });

  p.querySelectorAll('[data-open]').forEach(function(a){
    a.addEventListener('click',function(e){ e.preventDefault();
      if(typeof openDrawer==='function') openDrawer(parseInt(a.dataset.open));
    });
  });
}

function todayStat(label, val, color, sub){
  return '<div class="stat-card" style="--stat-color:'+color+'">'
    + '<div class="stat-label">'+label+'</div>'
    + '<div class="stat-value-wrapper"><span class="stat-value">'+E(val)+'</span></div>'
    + '<div class="fs11 c6" style="margin-top:3px">'+E(sub)+'</div>'
    + '</div>';
}

function wbSection(title, count, color, sub, key){
  return '<div class="wb-section" data-sec="'+key+'">'
    + '<div class="wb-sec-hd"><span class="dot" style="background:'+color+'"></span>'
    + '<span class="t">'+title+'</span><span class="n">'+count+'</span>'
    + '<span style="flex:1"></span><span class="fs11 c6">'+E(sub||'')+'</span>'
    + '</div>';
}

function newOutreachRow(f){
  var pt = f.profile_type || '';
  var vl = f.value_level || '';
  var score = f.ai_score || 0;
  var isVIP = pt === 'A' && vl === 'HIGH';
  var badgeColor = pt === 'A' ? '#7c3aed' : pt === 'B' ? '#2563eb' : pt === 'C' ? '#059669' : '#64748b';
  var vlBadge = vl === 'HIGH' ? '<span style="background:#fef3c7;color:#92400e;font-size:9px;padding:1px 5px;border-radius:4px;font-weight:600">HIGH</span>' : '';
  var r = '<div class="card no-row" style="padding:11px 15px;margin-bottom:6px;border-left:3px solid #6366f1;cursor:pointer;transition:opacity .3s" data-open="'+f.id+'">';
  r += '<div style="display:flex;align-items:center;justify-content:space-between">';
  r += '<div style="flex:1;min-width:0">';
  r += '<div style="display:flex;align-items:center;gap:6px;margin-bottom:4px">';
  if (isVIP) r += '<span style="font-size:12px">⭐</span>';
  r += '<span style="font-weight:600;font-size:13px;color:#0f172a">' + E(f.company) + '</span>';
  r += '<span style="font-size:11px;color:#64748b">' + E(f.country||'') + '</span>';
  r += '<span style="background:'+badgeColor+';color:#fff;font-size:9px;padding:1px 7px;border-radius:4px;font-weight:600">' + E(pt) + '</span>';
  if (vlBadge) r += vlBadge;
  r += '</div>';
  r += '<div style="font-size:11px;color:#94a3b8;display:flex;align-items:center;gap:6px;flex-wrap:wrap">';
  if (f.industry) { r += '<span>' + E(f.industry) + '</span>'; r += '<span style="color:#d1d5db">·</span>'; }
  if (f.contact) { r += '<span>' + E(f.contact) + '</span>'; r += '<span style="color:#d1d5db">·</span>'; }
  if (f.size) { r += '<span>' + E(f.size) + '</span>'; r += '<span style="color:#d1d5db">·</span>'; }
  if (f.email) { r += '<span style="font-size:10px">' + E(f.email) + '</span>'; r += '<span style="color:#d1d5db">·</span>'; }
  r += '<span>Score ' + score + '</span>';
  if (f.note) { r += '<span style="color:#d1d5db">·</span>'; r += '<span style="color:#64748b;font-style:italic;max-width:200px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">' + E(f.note) + '</span>'; }
  r += '</div>';
  r += '</div>';
  r += '<button class="btn btn-sm" style="background:#6366f1;color:#fff;white-space:nowrap;margin-left:10px;font-size:11px;padding:5px 14px" data-start-outreach="'+f.id+'">Start</button>';
  r += '</div></div>';
  return r;
}

function coolingRow(f){
  var od = f.overdue_days || 0;
  var h = '<div class="card" style="padding:10px 14px;margin-bottom:6px;border-left:3px solid #8b5cf6;background:#faf5ff;display:flex;align-items:center;justify-content:space-between;gap:8px;flex-wrap:wrap;cursor:pointer" data-open="'+f.id+'">';
  h += '<div style="flex:1;min-width:200px">';
  h += '<span class="fwb fs13" style="color:#0f172a">'+E(f.company)+'</span>';
  if(f.country) h += '<span class="fs11 c6" style="margin-left:5px">'+E(f.country)+'</span>';
  if(f.contact) h += '<span class="fs11 c6" style="margin-left:5px">'+E(f.contact)+'</span>';
  h += ' <span class="badge" style="background:#ede9fe;color:#6b21a8;font-size:9px">🧊 Cooling</span>';
  h += '<div class="fs11 c6 mt1">'+(od>0?'Cooling for '+od+' day(s)':'Review due today')+' · '+E(f.next_follow_date||'')+'</div>';
  if (f.next_follow_reason) h += '<div class="fs11 mt1" style="color:#475569">📌 '+E(f.next_follow_reason)+'</div>';
  h += '</div>';
  h += '<span class="fs11 c6">Click to view</span>';
  h += '</div>';
  return h;
}

function fuRow(f, type){
  var isOver = type === 'overdue';
  var isUpcoming = type === 'upcoming';
  var isHigh = f.value_level === 'HIGH' && f.profile_type === 'A';
  var isCooling = (f.sales_stage === 'cooling') || f.is_cooling;
  var isBounced = f.is_bounced;
  var od = f.overdue_days || 0;
  var du = f.days_until || 0;
  var leftColor = isOver ? (od >= 7 ? '#dc2626' : '#f59e0b') : isUpcoming ? '#0891b2' : '#16a34a';
  if (isHigh && isOver) leftColor = '#dc2626';
  var r = '<div class="card fu-row" style="padding:11px 15px;margin-bottom:6px;display:flex;align-items:center;justify-content:space-between;border-left:3px solid '+leftColor+';cursor:pointer;transition:opacity .3s" data-open="'+f.id+'">';
  r += '<div style="flex:1;min-width:0">';
  r += '<div style="display:flex;align-items:center;gap:6px;margin-bottom:3px">';
  if (isHigh) r += '<span style="font-size:12px">⭐</span>';
  r += '<span style="font-weight:600;font-size:13px;color:#0f172a">' + E(f.company) + '</span>';
  r += '<span style="font-size:11px;color:#64748b">' + E(f.country||'') + '</span>';
  if (f.contact) r += '<span style="font-size:11px;color:#94a3b8">' + E(f.contact) + '</span>';
  if (isHigh) r += '<span style="background:#fef3c7;color:#92400e;font-size:9px;padding:1px 5px;border-radius:4px;font-weight:600">VIP</span>';
  if (isCooling) r += '<span style="background:#f1f5f9;color:#64748b;font-size:9px;padding:1px 5px;border-radius:4px">Cooling</span>';
  if (isBounced) r += '<span style="background:#fee2e2;color:#dc2626;font-size:9px;padding:1px 5px;border-radius:4px">Bounced</span>';
  r += '</div>';
  r += '<div style="font-size:11px;color:#94a3b8;display:flex;align-items:center;gap:6px;flex-wrap:wrap">';
  var ch = f.first_touch_channel || 'email';
  r += '<span>' + E(ch) + '</span>';
  r += '<span style="color:#d1d5db">·</span>';
  r += '<span>' + E(({new:'New',touched:'Cold email sent',connected:'Connected',replied:'Replied',interested:'Interested',sample_pending:'Sample pending',sample_sent:'Sample sent',testing:'Testing',feedback:'Feedback',trial_order:'Trial order',won:'Won',lost:'Lost',cooling:'Cooling'})[f.sales_stage||'new'] || f.sales_stage||'-') + '</span>';
  if (isOver && od > 0) {
    var dayColor = od >= 7 ? '#dc2626' : '#ea580c';
    r += '<span style="color:#d1d5db">·</span>';
    r += '<span style="color:'+dayColor+';font-weight:600">Overdue ' + od + ' day(s)</span>';
  } else if (isUpcoming) {
    r += '<span style="color:#d1d5db">·</span>';
    r += '<span style="color:#0891b2;font-weight:600">due in ' + du + ' day(s)</span>';
  } else {
    r += '<span style="color:#d1d5db">·</span>';
    r += '<span>due today</span>';
  }
  if (f.outbound_count) {
    r += '<span style="color:#d1d5db">·</span>';
    var obText = 'Sent ' + f.outbound_count;
    if (f.inbound_count === 0 && f.outbound_count >= 3) obText += ' · no reply';
    r += '<span>' + obText + '</span>';
  }
  if (f.inbound_count) {
    r += '<span style="color:#d1d5db">·</span>';
    r += '<span style="color:#16a34a">Replies ' + f.inbound_count + '</span>';
  }
  if (isOver && f.outbound_count >= 2 && f.inbound_count === 0) {
    var ch2 = getRecommendedChannel(f.first_touch_channel, f.country);
    r += '<span style="color:#d1d5db;margin:0 2px">·</span>';
    r += '<span style="color:#6366f1;font-size:10px">Try ' + ch2 + ' instead</span>';
  }
  r += '</div>';
  if (f.next_follow_reason) r += '<div class="fs11" style="color:#475569;margin-top:3px">📌 ' + E(f.next_follow_reason) + '</div>';
  r += '</div>';
  var btnColor = isOver && od >= 7 ? '#dc2626' : '#16a34a';
  r += '<button class="btn btn-sm" style="background:'+btnColor+';color:#fff;white-space:nowrap;margin-left:10px;font-size:11px;padding:4px 11px" data-fdone="'+f.id+'">✓ Done</button>';
  r += '</div>';
  return r;
}

function getRecommendedChannel(ch, country){
  var c = (ch||'').toLowerCase();
  var co = (country||'').toUpperCase();
  var byRegion = {linkedin:'LinkedIn', whatsapp:'WhatsApp', phone:'Phone', email:'Email'};
  if (!c) c = 'email';
  var order;
  if (['DE','GERMANY','AT','CH'].indexOf(co) >= 0) order = ['linkedin','phone','whatsapp'];
  else if (['SA','AE','UAE','KW','QA','OM','BH'].indexOf(co) >= 0) order = ['whatsapp','phone','linkedin'];
  else order = ['linkedin','phone','whatsapp'];
  for (var i=0; i<order.length; i++){ if (order[i] !== c) return byRegion[order[i]]; }
  return byRegion[order[order.length-1]];
}
