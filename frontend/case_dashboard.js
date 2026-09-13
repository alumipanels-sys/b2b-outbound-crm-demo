async function RCaseIntel(p){
  p.innerHTML = '<div class="empty-state card">Loading CASE cold-outreach dashboard...</div>';
  var data;
  try {
    data = await api('/case-intel/dashboard');
  } catch(e) {
    p.innerHTML = '<div class="empty-state card" style="color:#dc2626">Load failed: '+E(e.detail||e.message||String(e))+'</div>';
    return;
  }

  var o = data.overview || {};
  var h = '<div class="flex jcs aic mb3">';
  h += '<div><h2 class="fs20 fwb">Won-Case Intelligence</h2><p class="fs12 c6 mt2">Turn successful cases into reusable plays; watch channel, profile, reply and case coverage.</p></div>';
  h += '<button class="btn btn-sm" style="background:#2563eb" id="refreshCaseIntel">Refresh data</button>';
  h += '</div>';

  h += '<div style="display:grid;grid-template-columns:repeat(4,minmax(140px,1fr));gap:12px;margin-bottom:16px">';
  h += caseMetric('Active customers', o.active_prospects || 0, (o.profiled_rate||0)+'% profiled', '#2563eb');
  h += caseMetric('Reply rate', (o.prospect_reply_rate||0)+'%', (o.replied_prospects||0)+' / '+(o.contacted_prospects||0)+' reached customers replied'+(o.bounced_prospects?' · '+o.bounced_prospects+' bounced':''), '#16a34a');
  h += caseMetric('Outreach sent', o.outbound_interactions || 0, (o.inbound_interactions||0)+' real replies', '#7c3aed');
  h += caseMetric('Reusable cases', o.case_studies || 0, (o.pending_sequences||0)+' steps pending', '#f97316');
  h += '</div>';

  var gaps = data.gaps || [];
  if(gaps.length){
    h += '<div class="card p3 mb3" style="border-left:3px solid #fbbf24;background:#fffced">';
    h += '<div class="sec-hd" style="margin-bottom:8px;color:#d97706">Gaps to fill now</div>';
    gaps.forEach(function(g){
      h += '<span class="badge" style="background:rgba(251,191,36,.15);color:#d97706;margin-right:6px;margin-bottom:4px;border:1px solid rgba(251,191,36,.2)">'+E(caseGapLabel(g.label))+': '+E(g.count)+'</span>';
    });
    h += '</div>';
  }

  h += '<div style="display:grid;grid-template-columns:1.1fr .9fr;gap:14px;margin-bottom:16px">';
  h += '<div class="card p3"><div class="sec-hd">Channel performance</div>'+caseChannelTable(data.channels||[])+'</div>';
  h += '<div class="card p3"><div class="sec-hd">Profile performance</div>'+caseProfileTable(data.profiles||[])+'</div>';
  h += '</div>';

  h += '<div style="display:grid;grid-template-columns:.9fr 1.1fr;gap:14px;margin-bottom:16px">';
  h += '<div class="card p3"><div class="sec-hd">Reply intent distribution</div>'+caseIntentList(data.reply_intents||{})+'</div>';
  h += '<div class="card p3"><div class="sec-hd">Case coverage</div>'+caseCoverage(data.cases_by_profile||{}, data.cases_by_outcome||{})+'</div>';
  h += '</div>';

  h += '<div class="flex jcs aic mb2"><h3 class="fs18 fwb">Structured win cases</h3><span class="fs12 c6">From case_study entries in the knowledge base</span></div>';
  var cases = data.cases || [];
  if(!cases.length){
    h += '<div class="card p4 tc c6">No case_study entries enabled yet.</div>';
  } else {
    h += '<div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(310px,1fr));gap:12px">';
    cases.forEach(function(c){ h += caseCard(c); });
    h += '</div>';
  }

  p.innerHTML = h;
  bindSafe(p, '#refreshCaseIntel', 'click', function(){ RCaseIntel(p); });
}

function caseMetric(label, value, sub, color){
  return '<div class="stat-card" style="--stat-color:'+color+'"><div class="stat-label">'+E(label)+'</div><div class="stat-value-wrapper"><span class="stat-value">'+E(value)+'</span></div><div class="fs11" style="color:#64748b;margin-top:2px">'+E(sub||'')+'</div></div>';
}

function caseChannelLabel(v){
  var map = {email:'Email', linkedin:'LinkedIn', whatsapp:'WhatsApp', phone:'Phone', unknown:'Unknown channel'};
  return map[v] || v || 'Unknown channel';
}

function caseOutcomeLabel(v){
  var map = {won:'Won', sample:'Sample', meeting:'Meeting / factory visit', reply:'Successful reply'};
  return map[v] || v || 'Unknown outcome';
}

function caseIntentLabel(v){
  var map = {
    unclassified:'Unclassified',
    '(blank)':'Unclassified',
    HOT_LEAD:'High intent',
    INFORMATION_REQUEST:'Info request',
    PRICING:'Pricing',
    SAMPLE:'Sample request',
    COOPERATION:'Cooperation intent',
    REJECTION:'Rejected',
    HARD_REJECTION:'Explicit rejection',
    INTERESTED_BUT_BUSY:'Interested but busy',
    NO_REPLY:'No reply',
    HIRING_SIGNAL:'Hiring / expansion signal'
  };
  return map[v] || v || 'Unclassified';
}

function caseGapLabel(v){
  var map = {
    'Unprofiled prospects':'Unprofiled prospects',
    'Inbound replies without intent':'Unanalyzed replies',
    'No reusable success cases':'Missing win cases'
  };
  return map[v] || v || 'Gap to fill';
}

function caseChannelTable(rows){
  if(!rows.length) return '<div class="tc c6 p3">No channel data yet</div>';
  var h = '<table><thead><tr><th>Channel</th><th>Sent</th><th>Replies</th><th>Reply rate</th></tr></thead><tbody>';
  rows.forEach(function(r){
    h += '<tr><td class="fwm">'+E(caseChannelLabel(r.channel))+'</td><td>'+E(r.outbound)+'</td><td>'+E(r.inbound)+'</td><td><span class="badge" style="background:'+(r.reply_rate>=20?'#dcfce7;color:#166534':'#f1f5f9;color:#475569')+'">'+E(r.reply_rate)+'%</span></td></tr>';
  });
  return h + '</tbody></table>';
}

function caseProfileTable(rows){
  if(!rows.length) return '<div class="tc c6 p3">No profile data yet</div>';
  var h = '<table><thead><tr><th>Profile</th><th>Customers</th><th>Reached</th><th>Reply rate</th></tr></thead><tbody>';
  rows.forEach(function(r){
    h += '<tr><td class="fwm">'+E(r.profile)+'</td><td>'+E(r.prospects)+'</td><td>'+E(r.contacted)+'</td><td>'+E(r.reply_rate)+'%</td></tr>';
  });
  return h + '</tbody></table>';
}

function caseIntentList(intents){
  var keys = Object.keys(intents).sort(function(a,b){ return intents[b]-intents[a]; });
  if(!keys.length) return '<div class="tc c6 p3">No reply-intent data yet</div>';
  var h = '<div class="flex fw g2">';
  keys.forEach(function(k){
    var warn = k === 'unclassified' || k === '(blank)' || k === '';
    h += '<span class="badge" style="background:'+(warn?'#fee2e2;color:#991b1b':'#e0e7ff;color:#3730a3')+'">'+E(caseIntentLabel(k))+': '+E(intents[k])+'</span>';
  });
  return h + '</div>';
}

function caseCoverage(byProfile, byOutcome){
  var h = '<div class="fs12 c6 mb2">By profile</div><div class="flex fw g2 mb3">';
  Object.keys(byProfile).sort().forEach(function(k){
    h += '<span class="badge" style="background:#f8fafc;color:#334155">'+E(k)+': '+E(byProfile[k])+'</span>';
  });
  h += '</div><div class="fs12 c6 mb2">By outcome stage</div><div class="flex fw g2">';
  Object.keys(byOutcome).sort().forEach(function(k){
    h += '<span class="badge" style="background:#dcfce7;color:#166534">'+E(caseOutcomeLabel(k))+': '+E(byOutcome[k])+'</span>';
  });
  return h + '</div>';
}

function caseCard(c){
  var h = '<div class="card p3" style="border-left:4px solid '+(c.strength_score>=80?'#16a34a':'#2563eb')+'">';
  h += '<div class="flex jcs aic mb2"><strong class="fs14">'+E(c.title)+'</strong><span class="badge" style="background:#f8fafc;color:#334155">Strength '+E(c.strength_score)+'</span></div>';
  h += '<div class="flex fw g2 mb2">';
  if(c.profile) h += '<span class="badge" style="background:#e0e7ff;color:#3730a3">Profile '+E(c.profile)+'</span>';
  (c.channels||[]).forEach(function(ch){ h += '<span class="badge" style="background:#f0f4ff;color:#1d4ed8">'+E(caseChannelLabel(ch))+'</span>'; });
  (c.outcomes||[]).forEach(function(out){ h += '<span class="badge" style="background:#dcfce7;color:#166534">'+E(caseOutcomeLabel(out))+'</span>'; });
  h += '</div>';
  h += '<p class="fs12 c6" style="line-height:1.55">'+E(c.preview||'')+'</p>';
  var play = c.playbook || [];
  if(play.length){
    h += '<div class="mt2" style="border-top:1px solid #f1f5f9;padding-top:8px">';
    h += '<div class="fs11 fwb mb1" style="color:#334155">Reusable playbook</div>';
    play.slice(0,3).forEach(function(x){ h += '<div class="fs11" style="color:#475569;margin-bottom:4px">- '+E(x)+'</div>'; });
    h += '</div>';
  }
  return h + '</div>';
}
