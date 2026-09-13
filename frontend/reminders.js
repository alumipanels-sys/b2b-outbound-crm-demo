// Follow-up overview: top priorities + manual reminders + emails to send today

async function RReminders(p){
  var today = new Date().toISOString().substring(0,10);
  var reminders=[], coolingReminders=[], topActions=[], todaySeqs=[], emailStats={sent_count:0,limit_count:10,remaining:10};
  try {
    var r1 = await api('/prospects/reminders');
    reminders = r1.reminders || [];
    coolingReminders = r1.cooling_reminders || [];
    topActions = r1.top_actions || [];
  } catch(e) { reminders = []; coolingReminders = []; topActions = []; }
  try { todaySeqs = await api('/sequences/today'); } catch(e) { todaySeqs = []; }
  try { emailStats = await api('/email/stats/today'); } catch(e) {}

  var overdueCount = 0, remTodayCount = 0, thisWeekCount = 0;
  var coolingCount = 0;
  try { var stats = await api('/prospects/stats'); coolingCount = stats.cooling || 0; } catch(e) {}
  reminders.forEach(function(r){
    if (r.days_until == null) return;
    if (r.days_until < 0) overdueCount++;
    else if (r.days_until === 0) remTodayCount++;
    else if (r.days_until <= 7) thisWeekCount++;
  });

  var h = '';
  h += '<div class="page-hd" style="align-items:center"><div><h2>Follow-up Tasks</h2><p class="page-sub">See which customers to push today, by priority: samples, hot replies and overdue reminders come first.</p></div>'
    + '<button class="btn btn-sm btn-b" onclick="RReminders(document.getElementById(\'mainPane\'))">Refresh</button></div>';

  // Top core numbers
  h += '<div style="display:flex;gap:10px;margin-bottom:20px;flex-wrap:wrap">';
  h += remStat('Overdue reminders', overdueCount, '#dc2626');
  h += remStat('Due today', remTodayCount, '#f97316');
  h += remStat('Within 7 days', thisWeekCount, '#0891b2');
  h += remStat('Cooling review', (coolingReminders||[]).length, '#8b5cf6', 'scrollToCooling');
  h += remStat('Emails to send today', todaySeqs.length, '#2563eb');
  h += remStat('Sent today', (emailStats.sent_count||0)+' / '+(emailStats.limit_count||10), '#059669');
  h += '</div>';

  // Top 10 priorities today
  h += '<div class="card" style="margin-bottom:18px;overflow:hidden">';
  h += remSectionHd('Top priorities today', 'TOP '+(topActions.length||0), '#4f46e5', 'Ranked by samples / hot signals / overdue / due date / AI score');
  h += '<div style="padding:14px 16px">';
  if(!topActions.length){
    h += '<div class="empty-state" style="padding:32px">No priority customers right now.</div>';
  }else{
    topActions.forEach(function(r,idx){ h += remActionRow(r, idx+1, true); });
  }
  h += '</div></div>';

  // All reminders
  h += '<div class="card" style="margin-bottom:18px;overflow:hidden">';
  h += '<div style="padding:12px 16px;display:flex;align-items:center;justify-content:space-between;cursor:pointer" id="remToggle">';
  h += '<span style="display:flex;align-items:center;gap:8px"><span class="dot" style="width:8px;height:8px;border-radius:50%;background:#6366f1"></span><span class="fwb fs13" style="color:#0f172a">All reminders</span><span class="fs11 c6">'+reminders.length+' items</span></span>';
  h += '<span class="fs11 c6">Click to collapse / expand</span>';
  h += '</div><div id="remSection" style="padding:14px 16px">';
  if(!reminders.length){
    h += '<div style="text-align:center;padding:28px;color:#94a3b8;font-size:12.5px">No reminders. Open a customer to set the next follow-up date.</div>';
  }else{
    reminders.forEach(function(r){ h += remActionRow(r, '', false); });
  }
  h += '</div></div>';

  // Cooling customer review
  h += '<div class="card" style="margin-bottom:18px;overflow:hidden">';
  h += '<div style="padding:12px 16px;display:flex;align-items:center;justify-content:space-between;cursor:pointer" id="coolToggle">';
  h += '<span style="display:flex;align-items:center;gap:8px"><span class="dot" style="width:8px;height:8px;border-radius:50%;background:#8b5cf6"></span><span class="fwb fs13" style="color:#0f172a">Cooling review</span><span class="fs11 c6">'+(coolingReminders||[]).length+' items</span></span>';
  h += '<span class="fs11 c6">Auto-cooling · manual thaw</span>';
  h += '</div><div id="coolSection" style="padding:14px 16px">';
  if(!coolingReminders.length){
    h += '<div style="text-align:center;padding:28px;color:#94a3b8;font-size:12.5px">No cooling customers need review.</div>';
  }else{
    h += '<div class="fs11 c6 mb2" style="padding:0 2px">Customers go to cooling after 5 unanswered touches. On review day, you decide: thaw, extend 30 days, or drop.</div>';
    coolingReminders.forEach(function(r){ h += coolingRow(r); });
  }
  h += '</div></div>';

  h += remTodayEmails(todaySeqs);
  p.innerHTML = h;

  updateReminderBadge(overdueCount + remTodayCount + todaySeqs.length, overdueCount);

  bindSafe(p, '#remToggle', 'click', function(){
    var sec = document.getElementById('remSection');
    if(!sec) return;
    sec.style.display = sec.style.display === 'none' ? 'block' : 'none';
  });

  bindSafe(p, '#coolToggle', 'click', function(){
    var sec = document.getElementById('coolSection');
    if(!sec) return;
    sec.style.display = sec.style.display === 'none' ? 'block' : 'none';
  });

  // Cooling row click opens customer detail
  p.querySelectorAll('[data-open]').forEach(function(a){
    a.addEventListener('click', function(e){
      e.preventDefault(); e.stopPropagation();
      if(typeof openDrawer === 'function') openDrawer(parseInt(a.dataset.open));
    });
  });

  p.querySelectorAll('[data-rd]').forEach(function(btn){
    btn.addEventListener('click', async function(){
      var pid = parseInt(btn.dataset.rd);
      var days = parseInt(btn.dataset.dd);
      var nd = new Date(today+'T00:00:00'); nd.setDate(nd.getDate()+days);
      var nds = nd.toISOString().substring(0,10);
      try { await api('/prospects/'+pid, {method:'PUT', body:{next_follow_date: nds}}); T('Postponed to '+nds); RReminders(p); }
      catch(e) { T('Failed', '#dc2626'); }
    });
  });

  p.querySelectorAll('[data-rdone]').forEach(function(btn){
    btn.addEventListener('click', async function(){
      try { await api('/prospects/'+btn.dataset.rdone, {method:'PUT', body:{next_follow_date:'', reminder_note:''}}); T('Cleared'); RReminders(p); }
      catch(e) { T('Failed', '#dc2626'); }
    });
  });

  // Cooling: thaw
  p.querySelectorAll('[data-thaw]').forEach(function(btn){
    btn.addEventListener('click', async function(){
      var pid = parseInt(btn.dataset.thaw);
      try { await api('/prospects/'+pid, {method:'PUT', body:{sales_stage:'connected', next_follow_date:'', reminder_note:'[Manual thaw]'}}); T('Thawed'); RReminders(p); }
      catch(e) { T('Failed', '#dc2626'); }
    });
  });
  // Cooling: extend
  p.querySelectorAll('[data-kcool]').forEach(function(btn){
    btn.addEventListener('click', async function(){
      var pid = parseInt(btn.dataset.kcool);
      var days = parseInt(btn.dataset.dd);
      var nd = new Date(today+'T00:00:00'); nd.setDate(nd.getDate()+days);
      var nds = nd.toISOString().substring(0,10);
      try { await api('/prospects/'+pid, {method:'PUT', body:{next_follow_date: nds, reminder_note:'[Cooling extended] Review postponed to '+nds}}); T('Postponed to '+nds); RReminders(p); }
      catch(e) { T('Failed', '#dc2626'); }
    });
  });
  // Cooling: lost
  p.querySelectorAll('[data-lost]').forEach(function(btn){
    btn.addEventListener('click', async function(){
      var pid = parseInt(btn.dataset.lost);
      if(!confirm('Drop this customer? It will move from cooling to lost.')) return;
      try { await api('/prospects/'+pid, {method:'PUT', body:{sales_stage:'lost', next_follow_date:'', reminder_note:'[Manually dropped] moved from cooling to lost'}}); T('Dropped'); RReminders(p); }
      catch(e) { T('Failed', '#dc2626'); }
    });
  });

  p.querySelectorAll('[data-gn]').forEach(function(btn){
    btn.addEventListener('click', async function(){
      btn.disabled = true; btn.textContent = 'Generating...';
      try {
        var r = await api('/ai/suggest-sequence/'+btn.dataset.gn, {method:'POST', body:{channel: btn.dataset.gc}});
        if(r.success){ T('Generated step '+r.step_number); RReminders(p); }
        else { T('Failed: '+(r.error||''), '#dc2626'); btn.disabled = false; btn.textContent = 'Retry'; }
      } catch(e) { T('Request failed', '#dc2626'); btn.disabled = false; btn.textContent = 'Retry'; }
    });
  });

  p.querySelectorAll('[data-eq-cancel]').forEach(function(b){b.addEventListener('click',async function(){
    if(!confirm('Cancel this queued email? It will not be sent automatically.')) return;
    try {
      await api('/email/queue/'+b.dataset.eqCancel+'/cancel',{method:'POST'});
      T('Queued email cancelled'); RReminders(p);
    } catch(e){ T('Cancel failed: '+(e.detail||e.message||''), '#dc2626'); }
  })});
}

function remSectionHd(title, count, color, sub){
  return '<div style="padding:12px 16px;background:#f7f9fc;border-bottom:1px solid #e4e9f2;display:flex;align-items:center;gap:8px">'
    + '<span class="dot" style="width:8px;height:8px;border-radius:50%;background:'+color+'"></span>'
    + '<span class="fs14 fwb" style="color:#0f172a">'+E(title)+'</span>'
    + '<span class="badge" style="background:'+color+'22;color:'+color+';font-size:10px">'+E(count)+'</span>'
    + '<span style="flex:1"></span><span class="fs11 c6">'+E(sub||'')+'</span>'
    + '</div>';
}

function remStat(label, value, color, onClickId){
  var extra = onClickId ? ' onclick="document.getElementById(\''+onClickId+'\').scrollIntoView({behavior:\'smooth\'});var s=document.getElementById(\'coolSection\');if(s)s.style.display=\'block\';" style="cursor:pointer"' : '';
  return '<div class="stat-card" style="--stat-color:'+color+';min-width:104px;padding:12px 14px;text-align:left">'
    + '<div class="stat-label"'+extra+'>'+E(label)+'</div>'
    + '<div class="stat-value-wrapper"><span class="stat-value" style="font-size:23px">'+E(value)+'</span></div>'
    + '</div>';
}

function coolingRow(r){
  var isOverdue = r.days_until != null && r.days_until < 0;
  var badgeText = isOverdue ? 'Review overdue '+Math.abs(r.days_until)+' day(s)' : r.days_until != null ? 'Review in '+r.days_until+' day(s)' : '';
  var h = '<div class="card" style="padding:10px 14px;margin-bottom:7px;border-left:3px solid #8b5cf6;background:#faf5ff;display:flex;align-items:center;justify-content:space-between;gap:8px;flex-wrap:wrap;cursor:pointer" data-open="'+r.id+'" title="Click to open customer">';
  h += '<div style="flex:1;min-width:200px">';
  h += '<span class="fwb fs13" style="color:#2563eb">'+E(r.company)+'</span>';
  if(r.contact) h += '<span class="fs11 c6" style="margin-left:5px">'+E(r.contact)+'</span>';
  h += '<span class="badge" style="background:#ede9fe;color:#6b21a8;font-size:9px;margin-left:5px">🧊 Cooling</span>';
  h += '<span class="fs11 c6" style="margin-left:5px">'+E(r.next_follow_date||'')+'</span>';
  if(r.reminder_note) h += '<div class="fs11" style="color:#475569;margin-top:3px">'+E(r.reminder_note).substring(0,140)+'</div>';
  h += '</div><div style="display:flex;gap:5px;flex-shrink:0">';
  if(badgeText) h += '<span class="badge" style="background:#8b5cf6;color:#fff;font-size:10px">'+badgeText+'</span>';
  h += '<button class="btn btn-sm" style="font-size:10px;padding:3px 9px;background:#16a34a;color:#fff" data-thaw="'+r.id+'" onclick="event.stopPropagation()">Thaw</button>';
  h += '<button class="btn btn-sm" style="font-size:10px;padding:3px 7px;background:#9ca3af;color:#fff" data-kcool="'+r.id+'" data-dd="30" onclick="event.stopPropagation()">+30 days</button>';
  h += '<button class="btn btn-sm" style="font-size:10px;padding:3px 9px;background:#dc2626;color:#fff" data-lost="'+r.id+'" onclick="event.stopPropagation()">Drop</button>';
  h += '</div></div>';
  return h;
}

function remActionRow(r, rank, compact){
  var isOverdue = r.days_until != null && r.days_until < 0;
  var isToday = r.days_until === 0;
  var isSoon = r.days_until != null && r.days_until >= 1 && r.days_until <= 3;
  var isSample = (r.reminder_note||'').indexOf('[样品]') >= 0 || (r.reminder_note||'').indexOf('[Sample]') >= 0 || !!r.sample_status;
  var borderColor = isOverdue ? '#dc2626' : isToday ? '#f97316' : isSample ? '#2563eb' : isSoon ? '#f59e0b' : '#e4e9f2';
  var bg = isOverdue ? '#fef2f2' : isToday ? '#fff7ed' : isSample ? '#eff6ff' : '#fff';
  var badgeText = isOverdue ? 'Overdue '+Math.abs(r.days_until)+' day(s)' : isToday ? 'Today' : r.days_until != null ? 'in '+r.days_until+' day(s)' : '';
  var reason = r.priority_reason || (isSample ? 'Sample push' : '');
  var h = '<div class="card" style="padding:10px 14px;margin-bottom:7px;border-left:3px solid '+borderColor+';background:'+bg+';display:flex;align-items:center;justify-content:space-between;gap:8px;flex-wrap:wrap">';
  h += '<div style="flex:1;min-width:200px">';
  if(rank) h += '<span class="fwb" style="color:#1e40af;margin-right:8px;font-size:12px">#'+rank+'</span>';
  h += '<span class="fwb fs13" style="cursor:pointer;color:#2563eb" onclick="openDrawer('+r.id+')">'+E(r.company)+'</span>';
  if(r.contact) h += '<span class="fs11 c6" style="margin-left:5px">'+E(r.contact)+'</span>';
  if(reason) h += '<span class="badge" style="background:#dbeafe;color:#1d4ed8;font-size:9px;margin-left:5px">'+E(reason)+'</span>';
  h += '<span class="fs11 c6" style="margin-left:5px">'+E(r.next_follow_date||'')+'</span>';
  if(r.reminder_note) h += '<div class="fs11" style="color:#475569;margin-top:3px">'+E(r.reminder_note).substring(0,140)+'</div>';
  h += '</div><div style="display:flex;gap:5px;flex-shrink:0">';
  if(badgeText) h += '<span class="badge" style="background:'+borderColor+';color:#fff;font-size:10px">'+badgeText+'</span>';
  h += '<button class="btn btn-sm" style="font-size:10px;padding:3px 7px;background:#eef2f7;color:#475569;border:1px solid #d7dee8" data-rd="'+r.id+'" data-dd="3">+3 days</button>';
  if(!compact) h += '<button class="btn btn-sm" style="font-size:10px;padding:3px 7px;background:#eef2f7;color:#475569;border:1px solid #d7dee8" data-rd="'+r.id+'" data-dd="7">+1 week</button>';
  h += '<button class="btn btn-sm" style="font-size:10px;padding:3px 9px;background:#16a34a;color:#fff" data-rdone="'+r.id+'">Done</button>';
  h += '</div></div>';
  return h;
}

function remTodayEmails(todaySeqs){
  var h = '<div class="card" style="overflow:hidden"><div style="padding:12px 16px;background:#f7f9fc;border-bottom:1px solid #e4e9f2;display:flex;align-items:center;gap:8px">';
  h += '<span class="dot" style="width:8px;height:8px;border-radius:50%;background:#2563eb"></span>';
  h += '<span class="fs14 fwb" style="color:#334155">Emails to send today</span>';
  h += '<span class="badge" style="background:#2563eb22;color:#2563eb;font-size:10px">'+todaySeqs.length+' emails</span>';
  h += '<span style="flex:1"></span><span class="fs11 c6">Sent in the customer\'s local time · unsent emails roll to the next send day</span></div>';
  if(!todaySeqs.length) return h + '<div style="text-align:center;padding:28px;color:#94a3b8;font-size:12.5px">No emails to send today</div></div>';
  h += '<div style="padding:14px 16px">';
  todaySeqs.forEach(function(s){
    h += '<div class="card" style="padding:10px 14px;margin-bottom:8px;border-left:3px solid #e4e9f2">';
    h += '<div style="display:flex;align-items:center;justify-content:space-between;gap:8px;flex-wrap:wrap"><div style="flex:1;min-width:180px">';
    h += '<span class="fwb fs13" style="cursor:pointer;color:#2563eb" onclick="openDrawer('+s.prospect_id+')">'+E(s.company||'?')+'</span>';
    h += '<div class="fs11 c6" style="margin-top:2px">'+(s.scheduled_at?'⏰ '+fmtTimeLocal(s.scheduled_at)+' · ':'')+'Step '+E(s.step_number||1)+' · '+E(s.subject||'No subject')+'</div>';
    h += '<p class="fs11" style="color:#475569;margin-top:3px;line-height:1.5;white-space:pre-wrap">'+E((s.content||'').substring(0,200))+'</p></div>';
    h += '<div style="display:flex;gap:5px;flex-shrink:0"><button class="btn btn-sm" style="background:#f87171;color:#fff;font-size:10px;padding:3px 9px" data-eq-cancel="'+s.id+'">Cancel queued</button></div>';
    h += '</div></div>';
  });
  return h + '</div></div>';
}

function updateReminderBadge(total, overdue) {
  var badge = document.getElementById('remBadge');
  if (!badge) return;
  if (total > 0) {
    badge.textContent = total;
    badge.style.display = 'inline-block';
    badge.style.background = overdue > 0 ? '#dc2626' : '#f59e0b';
  } else {
    badge.style.display = 'none';
  }
}
