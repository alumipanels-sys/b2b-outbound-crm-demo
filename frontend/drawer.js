// ── Drawer: detail view for a single prospect ──

async function openDrawer(id){
  _intChatSaved = ''; _intChatScrollTop = 0; _seqChatSaved = '';
  window._companyIntsKey = null;
  try{ var r1 = await api('/prospects/'+id); }catch(e){ T('Customer was deleted or no longer exists'); return; }
  try{ var r2 = await api('/intelligence/'+id).catch(function(){return {};}); }catch(e){ r2 = {}; }
  try{ var r3 = await api('/sequences/'+id).catch(function(){return [];}); }catch(e){ r3 = []; }
  try{ var r4 = await api('/interactions/'+id).catch(function(){return [];}); }catch(e){ r4 = []; }
  try{ var r4b = await api('/sample-tracking/'+id).catch(function(){return [];}); }catch(e){ r4b = []; }
  try{ var r5 = await api('/case-intel/prospect/'+id+'/matches').catch(function(){return {matches:[]};}); }catch(e){ r5 = {matches:[]}; }
  dp = r1; drIntel = r2 || {}; drSeqs = Array.isArray(r3) ? r3 : [];
  drInts = Array.isArray(r4) ? r4 : [];
  drSample = Array.isArray(r4b) ? r4b : [];
  drCaseMatches = (r5 && Array.isArray(r5.matches)) ? r5.matches : [];
  ed = Object.assign({}, dp);
  dtab = 'info'; scrResult = null; msgResult = null; drawerOpen = true;
  try { renderDrawer(); } catch(e) { console.error('renderDrawer:',e); drawerOpen = false; }
}

function closeDrawer(){
  drawerOpen = false; dp = null;
  try { var m = document.getElementById('dmask'); if(m) m.remove(); } catch(e) {}
  try { var d = document.getElementById('ddraw'); if(d) d.remove(); } catch(e) {}
}

// 本地时区期（YYYY-MM-DD）——用于展示"Actual send期"
function _localDate(iso){
  if(!iso) return '';
  try {
    var d = new Date(iso);
    if(isNaN(d.getTime())) return String(iso).substring(0,10);
    var mm = ('0'+(d.getMonth()+1)).slice(-2);
    var dd = ('0'+d.getDate()).slice(-2);
    return d.getFullYear()+'-'+mm+'-'+dd;
  } catch(e) { return String(iso).substring(0,10); }
}

function normalizeProfileType(profileType){
  var p = String(profileType || '').trim().toUpperCase();
  if(p.indexOf('PROFILE_') === 0) p = p.substring(8);
  return p;
}

function getProfileSignature(profileType){
  var p = normalizeProfileType(profileType);
  // 优先用系统配置里Save的签名模板（系统配置 → 签名设计）
  var cfg = window._profileSignatures || null;
  if(cfg){
    var key = p || 'DEFAULT';
    if(cfg[key]) return cfg[key];
    if(p && cfg['DEFAULT']) return cfg['DEFAULT'];
  }
  // 兜底默认
  var fallback = {
    A: '{{USER_NAME}} | Export Sales\n{{COMPANY}} - Certified Manufacturer\nQuality certified | Custom specs OK\n{{USER_EMAIL}} | {{WEBSITE}}',
    B: '{{USER_NAME}} | Export Sales\n{{COMPANY}} - Reliable Supply\nStable quality | Competitive lead time | Sample support\n{{USER_EMAIL}} | {{WEBSITE}}',
    C: "{{USER_NAME}} | International Sales Manager\n{{COMPANY}} - Your Manufacturing Partner\nQuality certified | Free sampling | Flexible MOQ | Let's talk\n{{USER_EMAIL}} | {{WEBSITE}}",
    D: '{{USER_NAME}} | Product Specialist\n{{COMPANY}} - Custom Components\nCustom specs | Quality guaranteed | Fast sampling\n{{USER_EMAIL}} | {{WEBSITE}}',
    E: '{{USER_NAME}} | Sales\n{{COMPANY}} - Supply Specialists\nSmall batches OK | Fast shipping | Full range support\n{{USER_EMAIL}} | {{WEBSITE}}'
  };
  return fallback[p] || '{{USER_NAME}} | {{COMPANY}}\nCertified Manufacturer\n{{USER_EMAIL}} | {{WEBSITE}}';
}

function signatureOptionsHtml(selectedProfileType){
  var current = normalizeProfileType(selectedProfileType) || 'DEFAULT';
  var opts = [
    { value: 'AUTO', label: 'Auto (by profile)' },
    { value: 'A', label: 'A - Engineering' },
    { value: 'B', label: 'B - Brand' },
    { value: 'C', label: 'C - Sales' },
    { value: 'D', label: 'D - Service' },
    { value: 'E', label: 'E - Flexible' },
    { value: 'DEFAULT', label: 'General signature' }
  ];
  if(currentUser && currentUser.email_signature){
    opts.splice(1, 0, { value: 'MINE', label: 'My signature' });
  }
  return opts.map(function(opt){
    var selected = opt.value === 'AUTO'
      ? ' selected'
      : ((opt.value === current) ? ' selected' : '');
    return '<option value="'+opt.value+'"'+selected+'>'+opt.label+'</option>';
  }).join('');
}

function resolveSelectedSignature(selectValue, fallbackProfileType){
  var pick = normalizeProfileType(selectValue);
  if(!pick || pick === 'AUTO') return getProfileSignature(fallbackProfileType);
  if(pick === 'MINE'){
    var mine = (currentUser && currentUser.email_signature) || '';
    if(!mine) return getProfileSignature(fallbackProfileType);
    mine = mine.replace(/\{\{USER_NAME\}\}/g, currentUser.name || '').replace(/\{\{USER_EMAIL\}\}/g, currentUser.email || '');
    return mine;
  }
  if(pick === 'DEFAULT') return getProfileSignature('');
  return getProfileSignature(pick);
}

function loadCompanyAlert(){
  if(!dp || !dp.id) return;
  var alertEl = document.getElementById('companyAlert');
  if(!alertEl) return;
  api('/prospects/'+dp.id+'/colleagues').then(function(cr){
    var cols = (cr && cr.colleagues) || [];
    if(!cols.length) return;
    api('/interactions/company/'+dp.id).then(function(list){
      var arr = Array.isArray(list) ? list : [];
      var countBy = {};
      arr.forEach(function(i){ if(i.contact) countBy[i.contact] = (countBy[i.contact]||0)+1; });
      var parts = cols.map(function(c){
        var nm = c.contact || c.company || 'Contact';
        var n = countBy[nm] || 0;
        return '<b>'+E(nm)+'</b>（'+(n ? 'contacted '+n+' times' : 'Not contacted')+'）';
      });
      alertEl.style.display = 'block';
      alertEl.innerHTML = '⚠ This company has '+cols.length+' contacts: '+parts.join(', ')+'。Check Interactions > Company timeline before choosing who to contact.';
    }).catch(function(){});
  }).catch(function(){});
}

function renderDrawer(){
  // Save chat content before destroying the drawer
  var intChatBox = document.getElementById('intAIChatMsgs');
  if (intChatBox && intChatBox.innerHTML.indexOf('I have the profile, history and intelligence here') === -1) {
    _intChatSaved = intChatBox.innerHTML;
    try { _intChatScrollTop = intChatBox.scrollTop; } catch(e) { _intChatScrollTop = 0; }
  }
  var seqChatBox = document.getElementById('seqChatMsgs');
  if (seqChatBox && seqChatBox.innerHTML.indexOf('I know this customer profile, pain points and intelligence') === -1) {
    _seqChatSaved = seqChatBox.innerHTML;
  }
  var prospect = dp; closeDrawer(); if(!prospect) return; dp = prospect;
  var tabs = [['info','Customer Info'],['scoring','AI Score'],['deals','Deals'],['quotes','Quote History'],['intel','Intelligence'],['sequence','Development Plan'],['interactions','Interactions'],['sample','Sample Tracking']];
  var th = tabs.map(function(item){ return '<button'+(item[0]===dtab?' class="active"':'')+' data-tab="'+item[0]+'">'+item[1]+'</button>'; }).join('');
  var pe = (dp.email || dp.dm_email || '');
  var emailDomain = pe.indexOf('@') >= 0 ? pe.substring(pe.indexOf('@')) : '';
  var gNews = 'https://www.google.com/search?q='+encodeURIComponent((dp.company||'')+' lawsuit OR litigation OR fraud OR bankruptcy OR acquisition');
  var gCompany = 'https://www.google.com/search?q='+encodeURIComponent((dp.company||'')+' linkedin');
  var gPeople = 'https://www.google.com/search?q='+encodeURIComponent((dp.contact||'')+' '+(dp.company||'')+' linkedin');
  var gTitle = 'https://www.google.com/search?q='+encodeURIComponent((dp.title||'procurement OR purchasing OR buyer')+' '+(dp.company||'')+' linkedin');
  var gAll = 'https://www.google.com/search?q='+encodeURIComponent('site:linkedin.com/in/ "'+(dp.company||'')+'"');
  var gSite = 'https://www.google.com/search?q='+encodeURIComponent('site:'+(dp.website||''));
  var gDomain = 'https://www.whois.com/whois/'+encodeURIComponent(dp.website||'');
  var gEmail = emailDomain ? 'https://www.google.com/search?q='+encodeURIComponent('"'+emailDomain+'" email OR contact') : '';
  var liUrlCompany = 'https://www.linkedin.com/search/results/companies/?keywords='+encodeURIComponent(dp.company||'');
  var liUrlPeople = 'https://www.linkedin.com/search/results/people/?keywords='+encodeURIComponent((dp.contact||'')+' '+(dp.company||''));
  var liNote = 'Hi, I am {{USER_NAME}} from {{COMPANY}}; I noticed your company '+(dp.company||'')+',  hope there is a chance to work together.';
  var companyEnc = encodeURIComponent(dp.company||'');
  var liJobsUrl = 'https://www.google.com/search?q=site:linkedin.com/company/+OR+site:linkedin.com/jobs/+%22'+companyEnc+'%22+jobs+OR+hiring+OR+careers';
  var liPostsUrl = 'https://www.google.com/search?q=site:linkedin.com/company/+OR+site:linkedin.com/posts/+%22'+companyEnc+'%22+post+OR+update+OR+news+OR+announced';
  var liPersonUrl = 'https://www.google.com/search?q=site:linkedin.com/in/+OR+site:linkedin.com/posts/+%22'+companyEnc+'%22+optical+OR+lens+OR+medical+OR+engineering';
  var h = '<div id="dmask" class="mask"></div><div id="ddraw" class="drawer">';
  h += '<div class="drawer-header">';
  h += '<div class="drawer-header-top" style="align-items:flex-start">';
  h += '<div style="flex:1;min-width:0">';
  // ── Company + 徽章行 ──
  h += '<div style="display:flex;align-items:center;gap:8px;flex-wrap:wrap">';
  h += '<h3 style="font-size:17px;font-weight:700">'+E(dp.company)+'</h3>';
  if(dp.country) h += '<span class="fs11 c6">'+E(dp.country)+'</span>';
  var dStageLabel = ({new:'New',touched:'Cold email sent',connected:'Connected',replied:'Replied',interested:'Interested',sample_pending:'Sample pending',sample_sent:'Sample sent',testing:'Testing',feedback:'Feedback',trial_order:'Trial order',won:'Won',lost:'Lost',cooling:'Cooling'})[dp.sales_stage||'new'] || (dp.sales_stage||'-');
  var dStageBg = {'Replied':'#059669','Interested':'#059669','Won':'#a78bfa','Trial order':'#22d3ee','Sample pending':'#f59e0b','Sample sent':'#f59e0b','Testing':'#fbbf24','Feedback':'#c084fc','Touched':'#6366f1','Connected':'#6366f1','New':'#64748b','Lost':'#475569','Cooling':'#a78bfa'}[dStageLabel] || '#64748b';
  h += '<span class="badge" style="background:'+dStageBg+';color:#fff">'+E(dStageLabel)+'</span>';
  if(dp.profile_type) h += '<span class="badge" style="background:#7c3aed;color:#fff">'+E(dp.profile_type)+'</span>';
  if(dp.value_level==='HIGH') h += '<span class="badge" style="background:#fef3c7;color:#92400e">HIGH</span>';
  if(dp.email_status==='bounced'||dp.email_status==='bounced_risk') h += '<span class="badge" style="background:#fee2e2;color:#dc2626">Bounced</span>';
  h += '</div>';
  // ── 速览行：评分 + Next follow-up + 快捷按钮 ──
  h += '<div style="display:flex;align-items:center;gap:10px;margin-top:9px;flex-wrap:wrap">';
  if(dp.ai_score){
    var dsc = Math.round(dp.ai_score);
    var dscC = dsc>=75?'#16a34a':dsc>=50?'#ca8a04':'#dc2626';
    h += '<span class="fwb" style="font-size:20px;color:'+dscC+';line-height:1">'+dsc+'</span><span class="fs11 c6">/100</span>';
  }
  if(dp.next_follow_date){
    var dfollow = String(dp.next_follow_date).substring(0,10);
    var ddays = Math.ceil((new Date(dfollow+'T00:00:00') - new Date(new Date().toISOString().substring(0,10)+'T00:00:00'))/86400000);
    var dcol = ddays<0?'#dc2626':ddays===0?'#f97316':'#6366f1';
    h += '<span class="badge" style="background:'+dcol+'1f;color:'+dcol+';font-weight:700">📅 Next follow-up '+E(dfollow)+(ddays<0?' (overdue '+Math.abs(ddays)+' days)':ddays===0?' (today)':'（'+ddays+'  days)')+'</span>';
  } else {
    h += '<span class="fs11 c6">No follow-up date</span>';
  }
  h += '<button class="btn btn-sm btn-b" id="hdrRemQuick3" style="padding:3px 10px">+3 days</button>';
  h += '<button class="btn btn-sm" id="hdrRemDone" style="background:#16a34a;padding:3px 10px">✓ Done</button>';
  h += '</div>';
  h += '</div>';
  h += '<button id="dClose">&times;</button>';
  h += '</div>';
  h += '<div id="companyAlert" style="display:none;margin:8px 22px;padding:8px 12px;background:#fef3c7;border:1px solid #fcd34d;border-radius:8px;font-size:12px;color:#92400e;line-height:1.6"></div>';
  // ── 外部搜索折叠区（默认Collapse，要用再展开）──
  h += '<div class="drawer-quick-links" style="border-bottom:none;padding:4px 22px 2px">';
  h += '<a href="#" id="extToggle" style="background:transparent;color:#6366f1;border:1px solid #c7d2fe;font-weight:600;font-size:11px;padding:3px 10px;border-radius:6px" onclick="return false">External search</a>';
  h += '<span class="fs11 c6" style="margin-left:2px">Click to search Google / LinkedIn / background</span>';
  h += '</div>';
  h += '<div id="extPanel" style="display:none;background:#fafbff;border-bottom:1px solid #eef1f6">';
  h += '<div class="drawer-quick-links"><span class="section-label">Google > LinkedIn:</span>';
  h += '<a href="'+gCompany+'" target="_blank" style="background:#ea4335">Search company</a>';
  h += '<a href="'+gPeople+'" target="_blank" style="background:#ea4335">Search contact</a>';
  h += '<a href="'+gTitle+'" target="_blank" style="background:#ea4335">Search title</a>';
  h += '<a href="'+gAll+'" target="_blank" style="background:#ea4335">All employees</a>';
  h += '<a href="'+gSite+'" target="_blank" style="background:#ea4335">Search website</a>';
  if(gEmail) h += '<a href="'+gEmail+'" target="_blank" style="background:#f97316">Search email '+E(emailDomain)+'</a>';
  h += '</div><div class="drawer-quick-links" style="border-bottom:none"><span class="section-label">Background tools:</span>';
  h += '<a href="'+gNews+'" target="_blank" style="background:#f87171">Search news / lawsuits</a>';
  h += '<a href="'+gDomain+'" target="_blank" style="background:#4b5563">Whois lookup</a>';
  h += '</div><div class="drawer-quick-links" style="border-bottom:none"><span class="section-label">LinkedIn direct:</span>';
  h += '<a href="'+liUrlCompany+'" target="_blank" style="background:#0A66C2">Company page</a>';
  h += '<a href="'+liUrlPeople+'" target="_blank" style="background:#0A66C2">Search people</a>';
  h += '<button class="btn btn-sm" style="background:#fff;color:#334155;border:1px solid #d1d5db" id="cpLiNote">Copy note</button>';
  h += '</div><div class="drawer-quick-links"><span class="section-label">LinkedIn:</span>';
  h += '<a href="'+liJobsUrl+'" target="_blank" style="background:#9333ea">Hiring</a>';
  h += '<a href="'+liPostsUrl+'" target="_blank" style="background:#0A66C2">Company posts</a>';
  h += '<a href="'+liPersonUrl+'" target="_blank" style="background:#059669">Employee posts</a>';
  h += '</div></div><div class="drawer-tabs">'+th+'</div></div>';
  h += '<div class="drawer-body" id="dbody"></div></div>';
  document.body.insertAdjacentHTML('beforeend', h);
  document.getElementById('dmask').onclick = closeDrawer;
  document.getElementById('dClose').onclick = closeDrawer;
  var extBtn = document.getElementById('extToggle');
  var extPanel = document.getElementById('extPanel');
  if(extBtn && extPanel) extBtn.onclick = function(){
    var open = extPanel.style.display !== 'none';
    extPanel.style.display = open ? 'none' : 'block';
    extBtn.textContent = open ? 'External search' : 'External search';
  };
  // 首次打开Customer详情：引导一次外部搜索（看过就不再提示）
  try{
    if(extBtn && !localStorage.getItem('td_hint_ext')){
      localStorage.setItem('td_hint_ext', '1');
      var hb = document.createElement('div');
      hb.style.cssText = 'position:absolute;top:8px;left:110px;background:#0f172a;color:#fff;font-size:11px;padding:5px 10px;border-radius:6px;z-index:999;box-shadow:0 4px 12px rgba(0,0,0,.2)';
      hb.innerHTML = 'Research this customer?<b>click here</b>expand Google / LinkedIn / Background <span style="color:#fbbf24">▼</span>';
      extBtn.parentElement.appendChild(hb);
      setTimeout(function(){ if(hb.parentNode) hb.remove(); }, 6000);
    }
  }catch(e){}
  var nb = document.getElementById('cpLiNote');
  if(nb) nb.onclick = function(){ navigator.clipboard.writeText(liNote); T('Copied'); };
  var hq3 = document.getElementById('hdrRemQuick3');
  if(hq3) hq3.onclick = function(){
    var t = new Date(); t.setDate(t.getDate()+3);
    if(t.getDay()===0) t.setDate(t.getDate()+1);
    if(t.getDay()===6) t.setDate(t.getDate()+2);
    var nd = t.toISOString().substring(0,10);
    api('/prospects/'+dp.id,{method:'PUT',body:{next_follow_date:nd}}).then(function(){
      dp.next_follow_date = nd; ed.next_follow_date = nd;
      T('Postponed to '+nd);
      try{ renderDrawer(); }catch(e){}
    }).catch(function(e){ T('Failed: '+(e.detail||e.message||''), '#dc2626'); });
  };
  var hdone = document.getElementById('hdrRemDone');
  if(hdone) hdone.onclick = function(){
    api('/prospects/'+dp.id+'/complete-followup',{method:'POST'}).then(function(r){
      dp.next_follow_date = r.remaining_next_follow_date || '';
      ed.next_follow_date = dp.next_follow_date;
      dp.reminder_note=''; ed.reminder_note='';
      T('Follow-up marked done','#16a34a');
      try{ renderDrawer(); }catch(e){}
    }).catch(function(e){ T('Failed: '+(e.detail||e.message||''), '#dc2626'); });
  };
  document.querySelectorAll('.drawer-tabs button').forEach(function(b){
    b.addEventListener('click',function(){ dtab = b.dataset.tab; renderDrawer(); });
  });
  loadCompanyAlert();
  try { renderDrawerTab(); } catch(e) { console.error('renderDrawerTab:',e); }
}

function renderDrawerTab(){
  var b = document.getElementById('dbody'); if(!b || !dp) return;
  try {
    if(dtab === 'info') DTInfo(b);
    else if(dtab === 'scoring') DTScore(b);
    else if(dtab === 'deals') DTDeals(b);
    else if(dtab === 'quotes') DTQuotes(b);
    else if(dtab === 'intel') DTIntelCombined(b);
    else if(dtab === 'sequence') DTSeq(b);
    else if(dtab === 'interactions') DTInt(b);
    else if(dtab === 'sample') DTSample(b);
  } catch(e) { console.error('Tab render error:', dtab, e); b.innerHTML = '<p style="color:#dc2626">Render error: '+(e.message||'')+'</p>'; }
}

// ── TAB: Info ──
function DTInfo(b){
  var h = '';

  // ── 待审核Email提醒：该Customer有草稿/待Send，引导去Email管理 ──
  if (drDrafts && drDrafts.length) {
    h += '<div style="background:#fffbeb;border:1px solid #fde68a;border-radius:8px;padding:9px 12px;margin-bottom:12px;display:flex;align-items:center;gap:10px;flex-wrap:wrap">';
    h += '<span class="fs12">📝 This customer has <b>'+drDrafts.length+'</b> emails awaiting review (draft/pending)</span>';
  h += '<button class="btn btn-sm" style="background:#f59e0b;margin-left:auto" onclick="nav(\'email\')">Review & send in Email Center</button>';
    h += '</div>';
  }

  // ── Reminder card (always visible, manual override) ──
  var today = new Date().toISOString().substring(0,10);
  var followDate = ed.next_follow_date || '';
  var followNote = ed.reminder_note || '';
  var daysDiff = null;
  if (followDate) {
    daysDiff = Math.ceil((new Date(followDate+'T00:00:00') - new Date(today+'T00:00:00')) / 86400000);
  }
  var isOverdue = daysDiff !== null && daysDiff < 0;
  var isToday = daysDiff === 0;
  var isSoon = daysDiff !== null && daysDiff >= 1 && daysDiff <= 3;
  var cardBg = followDate ? (isOverdue ? '#fef2f2' : isToday ? '#fff7ed' : isSoon ? '#fffbeb' : '#f0fdf4') : '#f8fafc';
  var cardBorder = followDate ? (isOverdue ? '#dc2626' : isToday ? '#f97316' : isSoon ? '#f59e0b' : '#10b981') : '#d1d5db';
  var cardIcon = followDate ? (isOverdue ? '🔴' : isToday ? '⚠️' : isSoon ? '📅' : '✅') : '📅';

  h += '<div class="card p3 mb3" style="background:'+cardBg+';border:2px solid '+cardBorder+'">';
  h += '<div style="display:flex;align-items:center;gap:8px;margin-bottom:8px"><span style="font-size:20px">'+cardIcon+'</span><span style="font-size:14px;font-weight:700;color:#334155">Next follow-up</span>';
  if (followDate && daysDiff !== null) {
    var badgeLabel = isOverdue ? 'Overdue '+Math.abs(daysDiff)+' days' : isToday ? 'Today!' : daysDiff+' days';
    h += '<span class="badge" style="background:'+(isOverdue?'#dc2626':isToday?'#f97316':'#10b981')+';color:#fff;font-size:11px">'+badgeLabel+'</span>';
  }
  if (ed.reminder_updated_at) h += '<span style="font-size:10px;color:#64748b;margin-left:auto">Last updated: '+fd(ed.reminder_updated_at)+'</span>';
  h += '</div>';
  // Date input + note input side by side
  h += '<div style="display:flex;gap:8px;align-items:end">';
  h += '<div style="flex:1"><label class="fs11 c6">Follow-up date</label><input type="date" id="remDate" value="'+E(followDate)+'" style="font-size:13px" title="Set or change next follow-up date"></div>';
  h += '<div style="flex:2"><label class="fs11 c6">Note</label><input id="remNote" value="'+E(followNote)+'" placeholder="e.g. Send quote / wait for sample confirmation" style="font-size:13px"></div>';
  h += '<div><button class="btn btn-sm" style="background:#6366f1;color:#fff;white-space:nowrap" id="saveRemBtn">Save</button></div>';
  h += '</div>';
  // Quick delay buttons
  h += '<div style="display:flex;gap:4px;margin-top:6px">';
  h += '<button class="btn btn-sm" style="background:#e5e7eb;color:#334155;font-size:10px;padding:2px 8px" data-rem-quick="3">+3 days</button>';
  h += '<button class="btn btn-sm" style="background:#e5e7eb;color:#334155;font-size:10px;padding:2px 8px" data-rem-quick="7">+1 week</button>';
  h += '<button class="btn btn-sm" style="background:#e5e7eb;color:#334155;font-size:10px;padding:2px 8px" data-rem-quick="14">+2 weeks</button>';
  h += '<span style="font-size:10px;color:#64748b;line-height:24px;margin-left:4px">Quick postpone</span>';
  h += '</div>';
  h += '<p style="font-size:10px;color:#64748b;margin-top:6px">Manual setting; nothing is sent automatically. See all reminders in the follow-up sidebar.</p>';
  // LinkedIn search links for company posts + jobs + person posts
  var companyEnc = encodeURIComponent(dp.company||'');
  var liJobsUrl = 'https://www.google.com/search?q=site:linkedin.com/company/+OR+site:linkedin.com/jobs/+%22'+companyEnc+'%22+jobs+OR+hiring+OR+careers';
  var liPostsUrl = 'https://www.google.com/search?q=site:linkedin.com/company/+OR+site:linkedin.com/posts/+%22'+companyEnc+'%22+post+OR+update+OR+news+OR+announced';
  var liPersonUrl = 'https://www.google.com/search?q=site:linkedin.com/in/+OR+site:linkedin.com/posts/+%22'+companyEnc+'%22+optical+OR+lens+OR+medical+OR+engineering';
  h += '<div style="margin-top:8px;padding-top:8px;border-top:1px solid #e5e7eb;display:flex;align-items:center;gap:6px;flex-wrap:wrap">';
  h += '<span class="fs11 c6">LinkedIn:</span>';
  h += '<a href="'+liJobsUrl+'" target="_blank" class="btn btn-sm" style="background:#9333ea;color:#fff;text-decoration:none">Hiring</a>';
  h += '<a href="'+liPostsUrl+'" target="_blank" class="btn btn-sm" style="background:#0A66C2;color:#fff;text-decoration:none">Company posts</a>';
  h += '<a href="'+liPersonUrl+'" target="_blank" class="btn btn-sm" style="background:#059669;color:#fff;text-decoration:none">Employee posts</a>';
  h += '</div>';
  h += '</div>';

  // ── Bounce warning banner ──
  if (dp.email_status === 'bounced' || ed.email_status === 'bounced') {
    var _liUrl = 'https://www.linkedin.com/search/results/people/?keywords='+encodeURIComponent((dp.contact||'')+' '+(dp.company||''));
    h += '<div style="margin-top:10px;padding:10px 14px;background:#fef2f2;border:2px solid #dc2626;border-radius:8px;display:flex;align-items:center;gap:10px">';
    h += '<span style="font-size:22px">📮</span>';
    h += '<div style="flex:1">';
    h += '<div style="font-size:14px;font-weight:700;color:#991b1b;margin-bottom:3px">Email bounced - mailbox returned</div>';
    h += '<div style="font-size:12px;color:#7f1d1d">Emails to this customer bounce. Try LinkedIn, WhatsApp or phone instead - buttons below open them.</div>';
    h += '</div>';
    h += '<div style="display:flex;gap:6px;flex-shrink:0">';
  if (dp.linkedin) h += '<a href="'+dp.linkedin+'" target="_blank" class="btn btn-sm" style="background:#0A66C2;color:#fff;text-decoration:none;white-space:nowrap">LinkedIn page</a>';
  h += '<a href="'+_liUrl+'" target="_blank" class="btn btn-sm" style="background:#059669;color:#fff;text-decoration:none;white-space:nowrap">Search LinkedIn</a>';
  h += '<button class="btn btn-sm" style="background:#f97316;color:#fff;white-space:nowrap" id="dismissBounceBtn">Handled - collapse notice</button>';
    h += '</div>';
    h += '</div>';
  }

  h += renderDrawerCaseMatches();

  h += '<div class="grid gcol2 g3 fs13">';
  [['Company','company'],['Contact','contact'],['Title','title'],['Country','country'],['Size','size'],['Industry','industry'],['Website','website'],['Email','email'],['Phone','phone'],['LinkedIn','linkedin'],['Decision maker','decision_maker'],['Decision role','decision_role']].forEach(function(item){
    h += '<div><label class="fs11 c6">'+item[0]+'</label><input class="deEd" data-key="'+item[1]+'" value="'+E(ed[item[1]]||'')+'">';
    // Email verification badge
    if (item[1] === 'email') {
      // Verification badge
      if (ed.email_verified || ed.email_verdict) {
        var vBadge = '', vColor = '#64748b';
        if (ed.email_verdict === 'valid') { vBadge = 'Verified'; vColor = '#16a34a'; }
        else if (ed.email_verdict === 'risky') { vBadge = 'Risky'; vColor = '#f59e0b'; }
        else if (ed.email_verdict === 'invalid') { vBadge = 'Invalid'; vColor = '#dc2626'; }
        else if (ed.email_verified) { vBadge = 'Verified'; vColor = '#6366f1'; }
        if (vBadge) h += '<span style="display:inline-block;margin-top:2px;font-size:10px;color:'+vColor+';font-weight:600">'+vBadge+'</span> ';
      }
      // Verify button
      h += '<div style="display:flex;gap:4px;margin-top:2px">';
  h += '<button class="btn btn-sm" style="background:#6366f1;color:#fff;font-size:10px;padding:1px 6px" id="verifyBtn'+dp.id+'" onclick="event.stopPropagation();verifySingleEmail('+dp.id+')">Verify</button>';
      h += '</div>';
    }
    h += '</div>';
  });
  h += '<div><label class="fs11 c6" style="color:#0891b2">Sales stage</label><select class="deEd" data-key="sales_stage">';
  var salesStages = {new:'New',touched:'Touched',connected:'Connected',replied:'Replied',interested:'Interested',sample_pending:'Sample pending',sample_sent:'Sample sent',testing:'Testing',feedback:'Feedback',trial_order:'Trial order',won:'Won',lost:'Lost',cooling:'🧊 Cooling'};
  Object.keys(salesStages).forEach(function(k){
    h += '<option value="'+k+'" '+((ed.sales_stage||'new')===k?'selected':'')+'>'+salesStages[k]+'</option>';
  });
  h += '</select></div>';
  // LinkedIn connection status
  h += '<div><label class="fs11 c6" style="color:#0A66C2">LinkedIn status</label><select class="deEd" data-key="linkedin_status">';
  var liStatuses = {not_connected:'Not connected', pending:'Pending', connected:'Connected'};
  Object.keys(liStatuses).forEach(function(k){
    h += '<option value="'+k+'" '+((ed.linkedin_status||'not_connected')===k?'selected':'')+'>'+liStatuses[k]+'</option>';
  });
  h += '</select></div>';
  // Source — dropdown with common channels
  h += '<div><label class="fs11 c6">Source channel</label><select class="deEd" data-key="source">';
  var sources = ['','LinkedIn','WhatsApp','Website','Trade show / event','Email outreach','Google','Referral','Industry directory','Customs data','Other'];
  sources.forEach(function(v){
    h += '<option value="'+v+'" '+(ed.source===v?'selected':'')+'>'+(v||'—')+'</option>';
  });
  h += '</select></div>';
  h += '<div><label class="fs11 c6">Development batch</label><input class="deEd" data-key="development_batch" value="'+E(ed.development_batch||'')+'" placeholder="e.g. 2026-06 US repair companies"></div>';
  h += '<div><label class="fs11 c6">First touch channel</label><select class="deEd" data-key="first_touch_channel">';
  var touchChannels = ['','Email','LinkedIn','WhatsApp','Phone','Trade Show','Other'];
  touchChannels.forEach(function(v){
    h += '<option value="'+v+'" '+((ed.first_touch_channel||'')===v?'selected':'')+'>'+(v||'—')+'</option>';
  });
  h += '</select></div>';
  // Profile type — Customer profile分类（默认 + 自定义，Customer可按自己Industry维护）
  var srcTag = ed.profile_source === 'manual'
  ? '<span style="display:inline-block;background:#dcfce7;color:#166534;border:1px solid #16a34a;padding:2px 10px;border-radius:12px;font-size:12px;font-weight:600;margin-left:8px">✋ My classification</span>'
    : (ed.profile_type
  ? '<span style="display:inline-block;background:#f8fafc;color:#64748b;border:1px solid #cbd5e1;padding:2px 10px;border-radius:12px;font-size:12px;margin-left:8px">🤖 AI guess</span>'
      : '');
  h += '<div><label class="fs11 c6" style="color:#7c3aed">Customer profile <span class="fs11 c6" style="color:#94a3b8">(customizable in System Settings)</span></label>'+srcTag+'<select id="deProfileType" class="deEd" data-key="profile_type" style="margin-top:4px;display:block">';
  h += profileCatOptionsHtml(ed.profile_type);
  h += '<option value="__custom__">+ Add custom profile...</option>';
  h += '</select></div></div>';
  // ── 更多字段（旧字段Collapse，数据保留可Edit）──
  h += '<div class="mt2" style="border-top:1px dashed #e4e9f2;padding-top:8px">';
  h += '<a href="#" id="moreFieldsToggle" style="font-size:11px;color:#6366f1;text-decoration:none;font-weight:600" onclick="return false">More fields</a>';
  h += '<div id="moreFields" style="display:none;margin-top:10px" class="grid gcol2 g3">';
  h += '<div><label class="fs11 c6">Legacy status</label><select class="deEd" data-key="status">';
['New','Following up','Replied','Paused','Won','Lost'].forEach(function(v){ h += '<option value="'+v+'" '+(ed.status===v?'selected':'')+'>'+({'New':'New friend','Following up':'Following','Replied':'Replied','Paused':'Paused','Won':'Won','Lost':'Lost'}[v]||v)+'</option>'; });
  h += '</select></div>';
  h += '<div><label class="fs11 c6">Structured source</label><select class="deEd" data-key="source_channel">';
  var sourceChannels = ['','LinkedIn','Email','Google','Google Maps','Trade Show','Industry Directory','Referral','Website','WhatsApp','Existing Customer','Other'];
  sourceChannels.forEach(function(v){
    h += '<option value="'+v+'" '+((ed.source_channel||'')===v?'selected':'')+'>'+(v||'—')+'</option>';
  });
  h += '</select></div>';
  h += '</div></div>';
  h += '<div class="mt2"><label class="fs11 c6">Note</label><textarea class="deEd" data-key="note" rows="3">'+E(ed.note||'')+'</textarea></div>';
  h += '<div class="flex g2 mt3"><button class="btn" style="background:#6366f1" id="saveBtn">Save</button><button class="btn" style="background:#f87171" id="delBtn">Delete customer</button></div>';
  // ── Colleagues section (same company, other contacts) ──
  h += '<div id="colleagues-section" class="mt3" style="display:none;border-top:1px solid #e5e7eb;padding-top:10px"><div class="flex jcs aic mb2"><div><div class="fs12 fwb" style="color:#334155">Same-company contacts / decision chain</div><div class="fs11 c6">Several people at one company are not duplicates - treat them as decision-chain leads.</div></div><div class="flex aic g3"><span id="colleagues-count" class="badge" style="background:#eef2ff;color:#3730a3"></span><button class="btn btn-sm" style="background:#7c3aed;color:#fff;font-size:10px" id="addColleagueBtn">+ Add colleague</button></div></div><div id="colleagues-list"></div></div>';
  b.innerHTML = h;
  // ── Quick delay buttons in reminder card ──
  var caseBtn = b.querySelector('[data-open-caseintel]');
  if(caseBtn) caseBtn.addEventListener('click', function(){ closeDrawer(); nav('caseintel'); });
  b.querySelectorAll('[data-rem-quick]').forEach(function(btn){
    btn.addEventListener('click', async function(){
      var days = parseInt(btn.dataset.remQuick);
      var today = new Date().toISOString().substring(0,10);
      var newDate = new Date(today+'T00:00:00');
      newDate.setDate(newDate.getDate() + days);
      var nd = newDate.toISOString().substring(0,10);
      var d = document.getElementById('remDate'); if (d) d.value = nd;
      var noteEl = document.getElementById('remNote'); var noteVal = noteEl ? noteEl.value : (ed.reminder_note || '');
      try {
        await api('/prospects/'+dp.id, {method:'PUT', body: {next_follow_date: nd, reminder_note: noteVal}});
        ed.next_follow_date = nd; ed.reminder_note = noteVal;
        dp.next_follow_date = nd; dp.reminder_note = noteVal;
        T('Postponed to '+nd);
        try { renderDrawer(); } catch(e) {}
      } catch(e) {
        T('Failed: '+(e.detail||e.message||''), '#dc2626');
      }
    });
  });
  // ── Save reminder independently (fast save, just date + note) ──
  bindSafe(b, '#saveRemBtn', 'click', async function(){
    var d = document.getElementById('remDate'); var dateVal = d ? d.value : '';
    var n = document.getElementById('remNote'); var noteVal = n ? n.value : '';
    try {
      await api('/prospects/'+dp.id, {method:'PUT', body: {next_follow_date: dateVal, reminder_note: noteVal}});
      ed.next_follow_date = dateVal;
      ed.reminder_note = noteVal;
      dp.next_follow_date = dateVal;
      dp.reminder_note = noteVal;
      T(dateVal ? 'Reminder set: '+dateVal : 'Reminder cleared');
      // Re-render the info tab to update the card badge
      try { renderDrawer(); } catch(e) {}
    } catch(e) {
      T('Save failed: '+(e.detail||e.message||''), '#dc2626');
    }
  });
  b.querySelector('#saveBtn').addEventListener('click',async function(){
    b.querySelectorAll('.deEd').forEach(function(el){ ed[el.dataset.key] = el.tagName==='SELECT' ? el.value : el.value; });
    await api('/prospects/'+dp.id, {method:'PUT', body:ed}); dp = Object.assign({}, ed); T('Saved'); loadList();
  });
  var delBtn = b.querySelector('#delBtn');
  if(delBtn) delBtn.addEventListener('click',function(){
    if(!confirm('Delete '+dp.company+' ?')) return;
    api('/prospects/'+dp.id,{method:'DELETE'}).then(function(){ T('Deleted'); closeDrawer(); loadList(); }).catch(function(e){ T('Delete failed','#dc2626'); });
  });
  var disBtn = b.querySelector('#dismissBounceBtn');
  if(disBtn) disBtn.addEventListener('click', async function(){
    try {
      await api('/prospects/'+dp.id, {method:'PUT', body:{email_status:'', email_verdict:''}});
      if(ed){ ed.email_status=''; ed.email_verdict=''; }
      if(dp){ dp.email_status=''; dp.email_verdict=''; }
      T('Bounce notice dismissed');
      renderDrawer();
    } catch(e){ T('Operation failed','#dc2626'); }
  });
  b.querySelectorAll('.deEd').forEach(function(el){
    if(el.tagName==='SELECT') el.addEventListener('change', function(){ed[el.dataset.key]=el.value});
    else el.addEventListener('input', function(){ed[el.dataset.key]=el.value});
  });
  var mfToggle = b.querySelector('#moreFieldsToggle');
  if(mfToggle) mfToggle.addEventListener('click', function(){
    var mf = document.getElementById('moreFields');
    if(!mf) return;
    var open = mf.style.display !== 'none';
    mf.style.display = open ? 'none' : 'grid';
    mfToggle.textContent = open ? 'More fields' : 'More fields';
  });
  // ── Customer profile：自定义新增 ──
  var profSel = b.querySelector('#deProfileType');
  if(profSel) profSel.addEventListener('change', async function(){
    if(this.value !== '__custom__') return;
    var prev = ed.profile_type || '';
    var name = prompt('Enter a new profile category name (e.g. Brand / Distributor / Assembler / Repair service):');
    if(!name || !name.trim()){
      ed.profile_type = prev;
      this.value = prev;
      return;
    }
    profSel.disabled = true;
    try{
      var r = await api('/setup/profile-categories', {method:'POST', body:{label:name.trim()}});
      window._profileCats = (r && r.categories) || window._profileCats;
      var cats = window._profileCats || [];
      var newKey = cats.length ? cats[cats.length-1].key : '';
      ed.profile_type = newKey;
      this.value = newKey;
      T('Category added: '+name.trim()+' and set as this customer profile', '#16a34a');
    }catch(e){
      T('Add failed: '+(e.detail||e.message||''), '#dc2626');
      ed.profile_type = prev;
      this.value = prev;
    }
    profSel.disabled = false;
  });
  // ── Load colleagues ──
  loadColleagues(dp.id);
}

async function loadColleagues(prospectId) {
  try {
    var r = await api('/prospects/' + prospectId + '/colleagues');
    var list = document.getElementById('colleagues-list');
    var section = document.getElementById('colleagues-section');
    var count = document.getElementById('colleagues-count');
    if (!list || !section) return;
    if (!r.colleagues || r.colleagues.length === 0) {
      section.style.display = 'block';
      if (count) count.textContent = '0 contacts';
      list.innerHTML = '<div class="fs11 c6" style="padding:6px 0">No colleagues added yet. Use Add colleague in the top-right to add more people from this company.</div>';
      wireAddColleague();
      return;
    }
    section.style.display = 'block';
    if (count) count.textContent = r.colleagues.length + ' contacts';
    var stageLabels = {new:'New',touched:'Touched',connected:'Connected',replied:'Replied',interested:'Interested',sample_pending:'Sample pending',sample_sent:'Sample sent',testing:'Testing',feedback:'Feedback',trial_order:'Trial order',won:'Won',lost:'Lost'};
    function roleBadge(title) {
      var t = String(title || '').toLowerCase();
      if (/owner|founder|ceo|president|director|head|vp|general manager/.test(t)) return ['Decision maker','#dcfce7','#166534'];
      if (/purchase|purchasing|procurement|buyer|sourcing|supply/.test(t)) return ['Procurement','#fef3c7','#92400e'];
      if (/operation|operations|repair|technician|engineer|r&d|quality|qa/.test(t)) return ['Technical / user','#e0f2fe','#075985'];
      if (/manager|lead|supervisor/.test(t)) return ['Manager','#ede9fe','#5b21b6'];
      return ['', '', ''];
    }
    var h = '';
    r.colleagues.forEach(function(c) {
      var daysInfo = '';
      if (c.next_follow_date) {
        var diff = Math.ceil((new Date(c.next_follow_date + 'T00:00:00') - new Date()) / 86400000);
  if (diff < 0) daysInfo = '<span style="color:#dc2626;font-size:10px;font-weight:600">Overdue '+Math.abs(diff)+' days</span>';
        else if (diff === 0) daysInfo = '<span style="color:#f97316;font-size:10px;font-weight:600">Follow up today</span>';
        else daysInfo = '<span style="color:#10b981;font-size:10px">'+diff+' days later</span>';
      }
      var rb = roleBadge(c.title);
      var st = stageLabels[c.sales_stage || ''] || c.sales_stage || c.status || '-';
      h += '<div style="display:flex;align-items:flex-start;justify-content:space-between;gap:10px;padding:8px 0;border-bottom:1px solid #f1f5f9;cursor:pointer" onclick="openDrawer('+c.id+')" title="Click to view details">';
      h += '<div style="min-width:0"><div><span style="font-size:13px;font-weight:600;color:#334155">'+E(c.contact||'UnknownContact')+'</span>';
      if (rb[0]) h += '<span style="display:inline-block;margin-left:6px;background:'+rb[1]+';color:'+rb[2]+';padding:1px 6px;border-radius:8px;font-size:10px;font-weight:600">'+rb[0]+'</span>';
  h += '</div><div style="font-size:11px;color:#64748b;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;max-width:360px">'+E(c.title||'Title not set')+'</div>';
      if (c.source_channel || c.development_batch) h += '<div class="fs11 c6">'+E(c.source_channel||'')+(c.development_batch?' · '+E(c.development_batch):'')+'</div>';
      h += '</div>';
      h += '<div style="display:flex;align-items:center;gap:8px;flex-wrap:wrap;justify-content:flex-end;min-width:180px">';
      if (c.email) h += '<span style="font-size:10px;color:#64748b" title="'+E(c.email)+'">📧</span>';
      if (c.linkedin) h += '<a href="'+E(c.linkedin)+'" target="_blank" onclick="event.stopPropagation()" style="text-decoration:none;font-size:10px" title="LinkedIn">🔗</a>';
      if (c.phone) h += '<span style="font-size:10px;color:#64748b" title="'+E(c.phone)+'">📞</span>';
      h += '<span style="font-size:10px;background:#f0fdff;color:#0e7490;border:1px solid #a5f3fc;padding:1px 6px;border-radius:8px">'+E(st)+'</span>';
      if (c.linkedin_status === 'connected') h += '<span style="font-size:10px;color:#0A66C2">LinkedIn connected</span>';
      h += daysInfo;
      h += '</div></div>';
    });
    list.innerHTML = h;
    wireAddColleague();
  } catch(e) { /* silent — colleagues are optional */ }
}

function wireAddColleague(){
  var btn = document.getElementById('addColleagueBtn');
  if(!btn) return;
  btn.onclick = function(){
    var list = document.getElementById('colleagues-list');
    if(!list) return;
    var companyName = (dp && dp.company) || '';
    list.innerHTML = '<div style="padding:8px 0">'
      + '<div class="fs11 c6 mb2" style="color:#7c3aed">Add colleague to ' + E(companyName) + ':</div>'
      + '<div class="grid gcol2 g3 mb2">'
      + '<div><label class="fs11 c6">Contact*</label><input id="ac_contact" placeholder="Name" style="width:100%;padding:6px 8px;border:1px solid #d1d5db;border-radius:4px;font-size:12px"></div>'
      + '<div><label class="fs11 c6">Title</label><input id="ac_title" placeholder="e.g. Purchasing Manager" style="width:100%;padding:6px 8px;border:1px solid #d1d5db;border-radius:4px;font-size:12px"></div>'
      + '<div><label class="fs11 c6">Email</label><input id="ac_email" placeholder="name@company.com" style="width:100%;padding:6px 8px;border:1px solid #d1d5db;border-radius:4px;font-size:12px"></div>'
      + '<div><label class="fs11 c6">Phone</label><input id="ac_phone" style="width:100%;padding:6px 8px;border:1px solid #d1d5db;border-radius:4px;font-size:12px"></div>'
      + '<div><label class="fs11 c6">LinkedIn</label><input id="ac_linkedin" placeholder="linkedin.com/in/..." style="width:100%;padding:6px 8px;border:1px solid #d1d5db;border-radius:4px;font-size:12px"></div>'
      + '</div>'
      + '<button class="btn btn-sm" style="background:#16a34a;color:#fff" id="acSave">Save colleague</button> '
      + '<button class="btn btn-sm" style="background:#e5e7eb;color:#334155" id="acCancel">Cancel</button></div>';
    var saveBtn = document.getElementById('acSave');
    var cancelBtn = document.getElementById('acCancel');
    if(saveBtn) saveBtn.onclick = async function(){
      var contact = document.getElementById('ac_contact').value.trim();
      if(!contact){ T('Enter the contact name','#dc2626'); return; }
      var body = {
        company: companyName,
        parent_company: (dp && dp.parent_company) || '',
        contact: contact,
        title: document.getElementById('ac_title').value.trim(),
        email: document.getElementById('ac_email').value.trim(),
        phone: document.getElementById('ac_phone').value.trim(),
        linkedin: document.getElementById('ac_linkedin').value.trim(),
        source_channel: 'Existing Customer',
      };
      try{
        await api('/prospects/create', {method:'POST', body: body});
        T('Colleague added');
        if(dp && dp.id) loadColleagues(dp.id);
      }catch(e){ T('Add failed: '+(e.detail||e.message||''),'#dc2626'); }
    };
    if(cancelBtn) cancelBtn.onclick = function(){ if(dp && dp.id) loadColleagues(dp.id); };
  };
}

// ── TAB: Scoring ──
function renderDrawerCaseMatches(){
  var matches = Array.isArray(drCaseMatches) ? drCaseMatches : [];
  if(!matches.length) return '';
  var top = matches.slice(0,3);
  var h = '<div class="card p3 mb3" style="border:2px solid #dbeafe;background:#f0f4ff">';
  h += '<div class="flex jcs aic mb2"><div><span class="fs14 fwb" style="color:#1e3a8a">Similar Success CASES</span><span class="fs11 c6" style="margin-left:8px">Use these as outreach playbooks</span></div>';
  h += '<button class="btn btn-sm" style="background:#6366f1" data-open-caseintel="1">Open dashboard</button></div>';
  top.forEach(function(c){
    h += '<div style="background:#fff;border:1px solid #bfdbfe;border-radius:6px;padding:10px;margin-top:8px">';
    h += '<div class="flex jcs aic mb1"><strong class="fs13">'+E(c.title)+'</strong><span class="badge" style="background:'+(c.match_score>=50?'#dcfce7;color:#166534':'#f1f5f9;color:#475569')+'">match '+E(c.match_score)+'</span></div>';
    h += '<div class="flex fw g2 mb1">';
    if(c.profile) h += '<span class="badge" style="background:#e0e7ff;color:#3730a3">Profile '+E(c.profile)+'</span>';
    (c.channels||[]).forEach(function(ch){ h += '<span class="badge" style="background:#f8fafc;color:#334155">'+E(ch)+'</span>'; });
    (c.outcomes||[]).forEach(function(out){ h += '<span class="badge" style="background:#dcfce7;color:#166534">'+E(out)+'</span>'; });
    h += '</div>';
    if(c.match_reasons && c.match_reasons.length){
      h += '<div class="fs11 c6 mb1">'+E(c.match_reasons.join(' | '))+'</div>';
    }
    var play = c.playbook || [];
    if(play.length) h += '<div class="fs11" style="color:#475569;line-height:1.5">- '+E(play[0])+'</div>';
    h += '</div>';
  });
  return h + '</div>';
}

function DTScore(b){
  if(dp.ai_score){
    var total = dp.ai_score;
    var h = '<div class="p4 mb3" style="background:#f8fafc;border-radius:4px">';
    h += '<div class="flex aic g3 mb3"><span class="fs28 fwb" style="color:'+(total>=75?'#16a34a':total>=50?'#ca8a04':'#6b7280')+'">'+total+'</span><span class="fs14 c6">/100</span><span class="badge">'+(dp.value_level||'-')+' / '+(dp.profile_type||'-')+'</span></div>';
    h += '<p class="fs14 fwm mb3">'+E(dp.score_reason||'')+'</p>';
    if(dp.score_breakdown){ try{
      var bdObj = typeof dp.score_breakdown==='string' ? JSON.parse(dp.score_breakdown) : dp.score_breakdown;
      if(bdObj && typeof bdObj === 'object' && !Array.isArray(bdObj)) {
        var labels={companyProfileFit:'Profile match',scaleCapability:'Size / capability',purchaseIntent:'Purchase signal',geographicPriority:'Region value',contactability:'Reachability'}, maxS={companyProfileFit:30,scaleCapability:15,purchaseIntent:25,geographicPriority:15,contactability:15};
        for(var k in bdObj){ var item=bdObj[k];
          if(!item || typeof item !== 'object') continue;
          var sc=item.score||0,ms=maxS[k]||25,pc=Math.round(sc/ms*100);
          h += '<div class="p2 mb2"><div class="flex jcs aic"><span>'+(labels[k]||k)+'</span><span>'+sc+'/'+ms+'</span></div><div style="height:4px;background:#e5e7eb"><div style="height:4px;width:'+pc+'%;background:'+(pc>=70?'#16a34a':pc>=40?'#ca8a04':'#dc2626')+'"></div></div><p class="fs11 c6">'+E(item.reason||'')+'</p></div>'; }
      }
    }catch(e){console.error('Score breakdown render error:', e)} }
    h += '</div><div class="flex aic g2 mb2">'+renderModelSelector('model_score','Scoring model')+'<button class="btn" style="background:#9333ea" id="reScoreBtn">Rescore</button></div>';
    b.innerHTML = h;
  }else{ b.innerHTML = '<div class="flex aic g2">'+renderModelSelector('model_score','Scoring model')+'<button class="btn" style="background:#9333ea" id="reScoreBtn">Start scoring</button></div>'; }
  if(scrResult) b.innerHTML += '<pre class="mt3 p3">'+JSON.stringify(scrResult,null,2)+'</pre>';
  var rsBtn = b.querySelector('#reScoreBtn'); if(rsBtn) rsBtn.addEventListener('click', function(){ scoreOne(dp.id); });
}
async function scoreOne(id){
  T('Scoring...','#eab308');
  try{
    var r = await api('/ai/score/'+id, {method:'POST', body:{model_override: getPanelModel('model_score')}});
    if(r.success){
      scrResult = r.result;
      try { dp = await api('/prospects/'+id); } catch(e) {}
      var s = r.result;
      // Handle both old Gemini format and new DeepSeek format
      var total = s.totalScore || s.aiScore || s.ai_score || s.score || '?';
      var prof = s.profileType || s.profile_type || s.profile || '?';
      var level = s.valueLevel || s.value_level || '';
      var reason = s.scoreSummary || s.scoreReason || s.score_reason || s.reasoning || '';
  var detail = '['+(r.model||'?')+'] '+(prof!=='EXCLUDE'?prof:'Excluded')+' | '+total+' pts'+(level?' | '+level:'');
      if (reason) detail += '\n'+reason.substring(0,200);
      T(detail, '#16a34a', 6000);
      showNextStep('Scoring complete', 'Customer scored ('+total+' points). Contact high scorers first; sort the customer list by score.', 'Go to Customer List', 'list');
      loadList();
    }else{
      var errMsg = (r.error||JSON.stringify(r)).substring(0,300);
      T('Scoring failed: '+errMsg, '#dc2626', 10000);
    }
  }catch(e){
    var em = (e.detail||e.message||String(e)).substring(0,300);
    T('Scoring failed: '+em, '#dc2626', 10000);
  }
  if(drawerOpen) { try { renderDrawer(); } catch(e) {} }
}

// ── TAB: Deals ──
async function DTDeals(b){
  var deals = [];
  try { deals = await api('/deals?prospect_id='+dp.id); } catch(e) { deals = []; }
  var h = '<div class="flex jcs aic mb3"><span class="fs14 fwb">Deals ('+deals.length+')</span><button class="btn btn-sm" style="background:#34d399" id="drAddDealBtn">+ New Deal</button></div>';
  if(!deals.length){
    h += '<div class="tc" style="padding:24px;color:#64748b">No deals</div>';
  } else {
    var stages = ['First Contact','Requirements Confirmed','Proposal & Quote','Negotiating','Won','Lost'];
    var colors = ['#f97316','#3b82f6','#8b5cf6','#ec4899','#16a34a','#6b7280'];
    var legacyStages = {'需求确认':'Requirements Confirmed','方案报价':'Proposal & Quote','谈判中':'Negotiating','已成交':'Won'};
    deals.forEach(function(d){
      var st = legacyStages[d.stage] || d.stage;
      var sc = colors[stages.indexOf(st)] || '#6b7280';
      h += '<div class="card p3 mb2" style="border-left:4px solid '+sc+'">';
      h += '<div class="flex jcs aic mb2"><span class="fwm">'+E(d.name)+'</span><span class="badge" style="background:'+sc+';color:#fff">'+E(st)+'</span></div>';
      h += '<div class="flex g3 fs12 c6"><span>Amount: <b style="color:#16a34a">€'+(d.amount||0).toLocaleString()+'</b></span>';
      if(d.expected_date) h += '<span>Expected: '+E(d.expected_date)+'</span>';
      h += '</div>';
      if(d.note) h += '<p class="fs11 c6 mt2">'+E(d.note).substring(0,200)+'</p>';
  h += '<div class="mt2" style="display:flex;gap:4px"><button class="btn btn-sm" style="background:#3b82f6" data-dr-edit-deal="'+d.id+'">Edit</button><button class="btn btn-sm" style="background:#f87171" data-dr-del-deal="'+d.id+'">Delete</button></div>';
      h += '</div>';
    });
  }
  b.innerHTML = h;

  // Add deal
  bindSafe(b,'#drAddDealBtn','click',function(){ showDrDealForm(b, null); });

  // Edit
  b.querySelectorAll('[data-dr-edit-deal]').forEach(function(el){
    el.addEventListener('click',function(){ showDrDealForm(b, parseInt(el.dataset.drEditDeal)); });
  });

  // Delete
  b.querySelectorAll('[data-dr-del-deal]').forEach(function(el){
    el.addEventListener('click',function(){
      if(!confirm('Delete this deal?')) return;
      api('/deals/'+parseInt(el.dataset.drDelDeal),{method:'DELETE'}).then(function(){T('Deleted');DTDeals(b);}).catch(function(){T('Delete failed','#dc2626')});
    });
  });
}

function showDrDealForm(b, editId){
  var h = '<div class="card p3 mb3" style="border:2px solid #2563eb;border-radius:8px;background:#f8fafc">';
  h += '<p class="fs13 fwb mb3" style="color:#4f46e5">'+(editId?'Edit Deal':'New Deal')+'</p>';
  if(editId) h += '<input type="hidden" id="drDealEditId" value="'+editId+'">';
  h += '<div class="mb2"><label class="fs11 c6">Name</label><input id="drDealName" placeholder="DealsName"></div>';
  h += '<div class="mb2"><label class="fs11 c6">Amount (EUR)</label><input type="number" id="drDealAmt" value="0" step="0.01"></div>';
  h += '<div class="mb2"><label class="fs11 c6">Stage</label><select id="drDealStage">';
  ['First Contact','Requirements Confirmed','Proposal & Quote','Negotiating','Won','Lost'].forEach(function(s){ h += '<option value="'+s+'">'+s+'</option>'; });
  h += '</select></div>';
  h += '<div class="mb2"><label class="fs11 c6">Expected date</label><input type="date" id="drDealDate"></div>';
  h += '<div class="mb2"><label class="fs11 c6">Note</label><textarea id="drDealNote" rows="2"></textarea></div>';
  h += '<div class="flex g2"><button class="btn btn-sm" style="background:#6366f1" id="drDealSave">Save</button><button class="btn btn-sm" style="background:#e5e7eb;color:#334155" id="drDealCancel">Cancel</button></div>';
  h += '</div>';

  var formDiv = document.createElement('div');
  formDiv.id = 'drDealForm';
  formDiv.innerHTML = h;

  var addBtn = document.getElementById('drAddDealBtn');
  if(addBtn) addBtn.insertAdjacentElement('afterend', formDiv);

  if(editId){
    api('/deals/'+editId).then(function(d){
      var nm = document.getElementById('drDealName'); if(nm) nm.value = d.name||'';
      var am = document.getElementById('drDealAmt'); if(am) am.value = d.amount||0;
      var st = document.getElementById('drDealStage'); if(st) st.value = d.stage||'First Contact';
      var dt = document.getElementById('drDealDate'); if(dt) dt.value = d.expected_date||'';
      var nt = document.getElementById('drDealNote'); if(nt) nt.value = d.note||'';
    }).catch(function(){});
  }

  function closeForm(){ var f = document.getElementById('drDealForm'); if(f) f.remove(); }

  var cancelBtn = document.getElementById('drDealCancel');
  if(cancelBtn) cancelBtn.onclick = closeForm;

  var saveBtn = document.getElementById('drDealSave');
  if(saveBtn) saveBtn.onclick = function(){
    var body = {
      name: document.getElementById('drDealName').value.trim(),
      prospect_id: dp.id,
      amount: parseFloat(document.getElementById('drDealAmt').value)||0,
      stage: document.getElementById('drDealStage').value,
      expected_date: document.getElementById('drDealDate').value,
      note: document.getElementById('drDealNote').value.trim()
    };
    if(!body.name){ T('Enter a name','#dc2626'); return; }
    var url = editId ? '/deals/'+editId : '/deals';
    var method = editId ? 'PUT' : 'POST';
    api(url,{method:method,body:body}).then(function(){
      T(editId?'Updated':'Created');
      closeForm();
      DTDeals(b);
    }).catch(function(e){ T('Save failed: '+(e.detail||e.message||''),'#dc2626'); });
  };
}

// ── TAB: Intelligence ──
function DTIntel(b){
  var h = '';
  // ── Intent signals card（AI 评分优先信号）──
  var sigMap = {hiring:'Hiring expansion', trade_show:'Trade show', import_change:'Import changes / supplier switch', referral:'Referral'};
  var sigList = [];
  try { sigList = dp.intent_signals ? JSON.parse(dp.intent_signals) : []; } catch(e) { sigList = []; }
  h += '<div class="card p3 mb3" style="border:1px solid #d8b4fe;background:#faf5ff">';
  h += '<p class="fwm fs13 mb2" style="color:#6b21a8">Intent signals (hit means follow up first)</p>';
  h += '<div class="flex g2 fw mb2">';
  Object.keys(sigMap).forEach(function(t){
    var on = sigList.some(function(s){return s.type===t});
    h += '<button data-sig="'+t+'" class="btn btn-sm" style="'+(on?'background:#7c3aed;color:#fff;border:1px solid #7c3aed':'background:#fff;color:#6b21a8;border:1px solid #d8b4fe')+'">'+sigMap[t]+'</button>';
  });
  h += '</div>';
  h += '<div id="sigNotes" class="mb2"></div>';
  h += '<div class="flex g2 aic"><input id="sigNoteInput" placeholder="Note (e.g. hiring a purchasing manager / met at a trade show / existing customer referral)" style="flex:1;font-size:12px;padding:6px 10px;border:1px solid #d1d5db;border-radius:6px"><button class="btn btn-sm" style="background:#7c3aed;color:#fff;white-space:nowrap" id="sigSaveBtn">Save intent signal</button></div>';
  if (sigList.length) {
    h += '<div class="fs12 mt2" style="color:#6b21a8;line-height:1.7">';
    sigList.forEach(function(s){ h += '<div>• '+sigMap[s.type]+(s.note?' — '+E(s.note):'')+(s.at?' <span class="c6">('+E(s.at)+')</span>':'')+'</div>'; });
    h += '</div>';
  }
  h += '</div>';
  // ── Conversation ion panorama：汇总所有往来Email，AI points析Customer意图 ──
  h += '<div class="card p3 mb3" style="border:1px solid #ddd6fe;background:#faf5ff">';
  h += '<div class="flex jcs aic mb2"><p class="fwm fs13" style="color:#6d28d9">🧠 Conversation panorama</p><button class="btn btn-sm" style="background:#7c3aed;color:#fff" id="intelPanoramaBtn">Analyze all email history</button></div>';
  h += '<div id="intelPanoramaBox"></div>';
  h += '</div>';
  if (drIntel && (drIntel.last_auto_scraped_at || drIntel.change_flags || drIntel.website_key_points)) {
    h += '<div class="card p3 mb3" style="border:1px solid #bfdbfe;background:#f0f4ff">';
    h += '<div class="flex jcs aic mb2"><p class="fwm fs13" style="color:#4f46e5">Auto intelligence</p>';
    if (drIntel.last_auto_scraped_at) h += '<span class="fs11 c6">Latest run: '+E(String(drIntel.last_auto_scraped_at).substring(0,16))+'</span>';
    h += '</div>';
    if (drIntel.change_flags) h += '<div class="fs12 mb2" style="color:#92400e;background:#fffced;border:1px solid #fed7aa;border-radius:4px;padding:6px 8px">'+E(drIntel.change_flags)+'</div>';
    if (drIntel.website_key_points) {
      try {
        var kp = JSON.parse(drIntel.website_key_points);
        if (Array.isArray(kp) && kp.length) {
          h += '<div class="fs12" style="line-height:1.7">';
          kp.slice(0,6).forEach(function(x){ h += '<div>- '+E(x)+'</div>'; });
          h += '</div>';
        }
      } catch(e) {
        h += '<div class="fs12 c6">'+E(drIntel.website_key_points).substring(0,500)+'</div>';
      }
    }
    h += '</div>';
  }
  // ── Domain OSINT card ──
  if (drIntel && (drIntel.domain_registered_at || drIntel.domain_registrar)) {
    h += '<div class="card p3 mb3" style="border:1px solid #c7d2fe;background:#fafbff">';
    h += '<p class="fwm mb2 fs13" style="color:#4338ca">🌐 Domain info</p>';
    h += '<div style="font-size:12px;line-height:1.8">';
    if (drIntel.domain_registered_at) {
      var d = new Date(drIntel.domain_registered_at);
      h += '<span class="c6">Registered:</span> <b>'+d.toISOString().substring(0,10)+'</b>';
      var ageDays = Math.floor((new Date() - d) / 86400000);
      var ageYears = (ageDays / 365.25).toFixed(1);
      var ageColor = ageDays > 365*3 ? '#16a34a' : ageDays > 365 ? '#f59e0b' : '#dc2626';
      h += ' <span style="color:'+ageColor+';font-size:11px">('+ageYears+' years)</span><br>';
    }
    if (drIntel.domain_expires_at) {
      var ed = new Date(drIntel.domain_expires_at);
      h += '<span class="c6">Expires:</span> <b>'+ed.toISOString().substring(0,10)+'</b><br>';
    }
    if (drIntel.domain_registrar) {
      h += '<span class="c6">Registrar:</span> '+E(drIntel.domain_registrar)+'<br>';
    }
    h += '</div></div>';
  }
  // ── Patents card (from osint_report) ──
  if (drIntel && drIntel.osint_report) {
    try {
      var osint = typeof drIntel.osint_report === 'string' ? JSON.parse(drIntel.osint_report) : drIntel.osint_report;
      if (osint && osint.patents && osint.patents.patent_count > 0) {
        var pt = osint.patents;
        h += '<div class="card p3 mb3" style="border:1px solid #d1fae5;background:#f0fdf6">';
  h += '<p class="fwm mb2 fs13" style="color:#065f46">📜 Patents - '+pt.patent_count+' records found</p>';
        if (pt.ai_summary) h += '<p class="fs12 mb2" style="color:#059669;line-height:1.5">'+E(pt.ai_summary)+'</p>';
        if (pt.patents && pt.patents.length) {
          h += '<div style="font-size:11px;max-height:120px;overflow-y:auto">';
          pt.patents.slice(0,8).forEach(function(pat) {
            h += '<div style="padding:2px 0;border-bottom:1px solid #d1fae5">';
            h += '<a href="https://patents.google.com/patent/'+E(pat.patent_number)+'" target="_blank" style="color:#4f46e5">'+E(pat.patent_number)+'</a>';
            if (pat.title) h += ' - '+E(pat.title).substring(0,80);
            h += '</div>';
          });
          h += '</div>';
        }
        h += '</div>';
      }
      // ── FDA 510(k) card ──
      if (osint && osint.fda_510k && osint.fda_510k.total_count > 0) {
        var fd = osint.fda_510k;
        h += '<div class="card p3 mb3" style="border:1px solid #dbeafe;background:#f0f4ff">';
  h += '<p class="fwm mb2 fs13" style="color:#4f46e5">🏥 FDA 510(k) registrations - '+fd.total_count+' records';
        if (fd.has_regulatory_signal) h += ' <span style="color:#059669;font-size:11px">✅ regulatory signals found</span>';
        h += '</p>';
        if (fd.devices && fd.devices.length) {
          h += '<div style="font-size:11px;max-height:120px;overflow-y:auto">';
          fd.devices.slice(0,6).forEach(function(dev) {
            h += '<div style="padding:2px 0;border-bottom:1px solid #bfdbfe">';
            h += '<a href="https://www.accessdata.fda.gov/scripts/cdrh/cfdocs/cfpmn/pmn.cfm?ID='+E(dev.k_number||'')+'" target="_blank" style="color:#4f46e5">K'+E(dev.k_number||'')+'</a>';
            h += ' - '+E(dev.device_name||'').substring(0,80);
            if (dev.decision_date) h += ' <span class="c6" style="font-size:10px">'+E(dev.decision_date)+'</span>';
            h += '</div>';
          });
          h += '</div>';
        }
        h += '</div>';
      }
    } catch(e) {}
  }
  h += '<p class="fwm mb2 fs13">Website intelligence</p><div class="flex g2 mb2"><input value="'+E(dp.website||'')+'" id="srcUrl"><button class="btn btn-sm" style="background:#34d399" id="scrapeBtn">Scrape</button></div>';
  h += '<textarea id="it_web" rows="4" class="mb2">'+E(drIntel.website_content||'')+'</textarea>';
  h += '<p class="fwm mb1 fs12">LinkedIn content</p><textarea id="it_li" rows="4" class="mb2">'+E(drIntel.linkedin_content||'')+'</textarea>';
  h += '<p class="fwm mb1 fs12">Hiring info</p><textarea id="it_hr" rows="3" class="mb2">'+E(drIntel.hiring_content||'')+'</textarea>';
  // ── Screenshot upload area ──
  h += '<div class="card p3 mb3" style="border:2px dashed #c7d2fe;background:#fafbff">';
  h += '<p class="fwm mb2 fs13" style="color:#4338ca">Upload screenshot - AI analyzes it (for sites that cannot be scraped)</p>';
  h += '<div style="display:flex;gap:8px;margin-bottom:8px"><select id="ssType" style="width:auto;font-size:12px"><option value="linkedin_profile">LinkedIn profile</option><option value="company_page">LinkedIn Company page</option><option value="website_screenshot">Website screenshot</option><option value="other">Other screenshot</option></select>';
  h += '<input type="file" id="ssFile" accept="image/*" style="font-size:12px"><span class="fs11 c6" style="margin:0 2px">Vision model</span><select data-model-key="model_ss" style="font-size:10px;padding:1px 4px;border:1px solid #d1d5db;border-radius:4px;background:#fff;color:#64748b;cursor:pointer;max-width:50px" onchange="localStorage.setItem(\'model_ss\',this.value)"><option value="gemini">Gem</option><option value="auto" selected>Auto</option></select><button class="btn btn-sm" style="background:#7c3aed;color:#fff" id="ssAnalyzeBtn">Analyze screenshot</button></div>';
  h += '<div id="ssPreview" style="max-width:200px;margin-bottom:6px"></div>';
  // Show existing screenshot analyses
  if (drIntel.screenshot_analysis) {
  h += '<div class="card p3" style="background:#fff;border:1px solid #e2e8f0"><p class="fwm mb1 fs12" style="color:#4338ca">📋 Screenshot analysis history</p><pre style="font-size:12px;line-height:1.6;white-space:pre-wrap;max-height:300px;overflow-y:auto">'+E(drIntel.screenshot_analysis)+'</pre></div>';
  }
  h += '</div>';
  h += '<div class="flex g2 mb3">'+renderModelSelector('model_intel','Analysis model')+'<button class="btn" style="background:#6366f1" id="saveIntelBtn">Save</button><button class="btn" style="background:#9333ea" id="analyzeIntelBtn">AIAnalyze</button></div>';
  if(drIntel.icebreak_angles){ try{ JSON.parse(drIntel.icebreak_angles).forEach(function(a){h+='<div class="p2 mb2"><p class="fs13 fwm">'+E(a.angle||'')+'</p><p class="fs12 c6">'+E(a.why||'')+'</p></div>'}); }catch(e){} }
  b.innerHTML = h;
  // ── Conversation ion panorama：Generate + 自动加载 ──
  var intelPanBtn = document.getElementById('intelPanoramaBtn');
  if (intelPanBtn) intelPanBtn.addEventListener('click', function(){
    intelPanBtn.disabled = true; intelPanBtn.textContent = 'Analyzing...';
    api('/quote-history/panorama?prospect_id='+dp.id,{method:'POST'}).then(function(r){
  if(r && r.success){ renderPanorama(b, r.report, 'intelPanoramaBox'); T('Conversation panorama generated','#16a34a'); }
      else { T((r&&r.error)||'Analysis failed','#dc2626'); renderPanoramaBoxEmpty(b, (r&&r.error)||'', 'intelPanoramaBox'); }
    }).catch(function(e){ T('Analysis failed','#dc2626'); renderPanoramaBoxEmpty(b, (e&&e.detail)||'', 'intelPanoramaBox'); })
  .finally(function(){ if(intelPanBtn){ intelPanBtn.disabled = false; intelPanBtn.textContent = 'Analyze all email history'; } });
  });
  api('/quote-history/panorama?prospect_id='+dp.id).then(function(r){
    var box = document.getElementById('intelPanoramaBox');
    if (box) {
      if(r && r.exists && r.report){ renderPanorama(b, r.report, 'intelPanoramaBox'); }
      else { renderPanoramaBoxEmpty(b, '', 'intelPanoramaBox'); }
    }
  }).catch(function(){});
  // Restore screenshot preview from memory after tab switch
  var cachedSS = drIntel._ssPreview || (function(){ try { return localStorage.getItem('ss_preview_'+dp.id); } catch(e) { return null; } })();
  if (cachedSS) {
    if (!drIntel) drIntel = {};
    drIntel._ssPreview = cachedSS;
    var ssPrev = document.getElementById('ssPreview');
    if (ssPrev) ssPrev.innerHTML = '<img src="'+cachedSS+'" style="max-width:200px;border-radius:4px;border:1px solid #d1d5db">';
  }
  var scrapeBtn = document.getElementById('scrapeBtn');
  if(scrapeBtn) scrapeBtn.addEventListener('click',async function(){
    scrapeBtn.disabled = true; scrapeBtn.textContent = 'Scraping...'; scrapeBtn.style.background='#9ca3af';
    T('Scraping...');
    try{
      var r=await api('/ai/scrape/'+dp.id,{method:'POST'});
      if(r.success){
        var msg = 'Scrape complete';
        if (r.chars_scraped > 0) msg += ': '+r.chars_scraped+' characters';
        if (r.osint_steps && r.osint_steps.length > 0) {
          var stepNames = {whois_checked:'Domain',patents_checked:'Patents',fda_checked:'FDA',website_scraped:'Website',key_points_extracted:'AIAnalyze'};
          var done = r.osint_steps.filter(function(s){return stepNames[s]}).map(function(s){return stepNames[s]});
          if (done.length) msg += ' | '+done.join('+')+' checked';
        }
  if (r.patent_count) msg += ' | Patents '+r.patent_count+' records';
        if (r.fda_510k_count) msg += ' | FDA '+r.fda_510k_count+' records';
        if (r.website_error) msg = '⚠ WebsiteScrapeFailed: ' + r.website_error;
        T(msg, r.website_error ? '#f59e0b' : undefined);
        drIntel=await api('/intelligence/'+dp.id);
      }
    }catch(e){T('ScrapeFailed: '+(e.detail||e.message||'Network error'),'#dc2626')}
    scrapeBtn.disabled = false; scrapeBtn.textContent = 'Scrape'; scrapeBtn.style.background='#16a34a';
    renderDrawer();
  });
  // ── Intent signal toggles ──
  var _sigState = sigList.map(function(s){ return {type:s.type, note:s.note||'', at:s.at||''}; });
  function renderSigNotes(){
    var box = document.getElementById('sigNotes');
    if (!box) return;
    var html = '';
    _sigState.forEach(function(s){
      html += '<div class="flex aic g2 mb1" style="font-size:12px"><span style="color:#7c3aed;font-weight:600;width:96px">'+sigMap[s.type]+'</span><input data-sig-note="'+s.type+'" value="'+E(s.note)+'" placeholder="Note" style="flex:1;font-size:12px;padding:4px 8px;border:1px solid #e2e8f0;border-radius:4px"></div>';
    });
    box.innerHTML = html;
    box.querySelectorAll('[data-sig-note]').forEach(function(inp){
      inp.addEventListener('input', function(){
        var st = _sigState.find(function(s){return s.type===inp.dataset.sigNote;});
        if (st) st.note = inp.value;
      });
    });
  }
  renderSigNotes();
  b.querySelectorAll('[data-sig]').forEach(function(btn){
    btn.addEventListener('click', function(){
      var t = btn.dataset.sig;
      var idx = _sigState.findIndex(function(s){return s.type===t;});
      if (idx >= 0) {
        _sigState.splice(idx,1);
        btn.style.background='#fff'; btn.style.color='#6b21a8'; btn.style.border='1px solid #d8b4fe';
      } else {
        _sigState.push({type:t, note: ((document.getElementById('sigNoteInput')||{}).value||''), at:new Date().toISOString().substring(0,10)});
        btn.style.background='#7c3aed'; btn.style.color='#fff'; btn.style.border='1px solid #7c3aed';
      }
      renderSigNotes();
    });
  });
  var sigSaveBtn = document.getElementById('sigSaveBtn');
  if (sigSaveBtn) sigSaveBtn.addEventListener('click', async function(){
    sigSaveBtn.disabled = true; sigSaveBtn.textContent = 'Saving...';
    try {
      await api('/prospects/'+dp.id+'/intent-signals', {method:'PUT', body:{signals:_sigState}});
      T('Intent signal saved','#7c3aed');
      dp = await api('/prospects/'+dp.id);
      renderDrawer();
  } catch(e) { T('Save failed: '+(e.detail||e.message||''),'#dc2626'); sigSaveBtn.disabled=false; sigSaveBtn.textContent='Save intent signal'; }
  });
  var saveBtn = document.getElementById('saveIntelBtn');
  if(saveBtn) saveBtn.addEventListener('click',async function(){ await api('/intelligence/'+dp.id,{method:'PUT',body:{website_content:document.getElementById('it_web').value,linkedin_content:document.getElementById('it_li').value,hiring_content:document.getElementById('it_hr').value}}); T('Saved'); });
  var analyzeBtn = document.getElementById('analyzeIntelBtn');
  if(analyzeBtn) analyzeBtn.addEventListener('click',async function(){ await api('/intelligence/'+dp.id,{method:'PUT',body:{website_content:document.getElementById('it_web').value,linkedin_content:document.getElementById('it_li').value,hiring_content:document.getElementById('it_hr').value}}); T('Analyzing...'); try{var aiBody={};var aiModel=getPanelModel('model_intel');if(aiModel!=='auto')aiBody.model_override=aiModel;await api('/ai/analyze-intelligence/'+dp.id,{method:'POST',body:aiBody});drIntel=await api('/intelligence/'+dp.id);T('AnalyzeDone')}catch(e){T('Analysis failed')} renderDrawer(); });

  // Screenshot upload + preview (with compression)
  var ssFile = document.getElementById('ssFile');
  if (ssFile) ssFile.addEventListener('change', function() {
    var file = ssFile.files[0];
    if (!file) return;

    // Compress large images before sending to Gemini Vision
    var MAX_W = 1200;
    var MAX_H = 1600;
    var reader = new FileReader();
    reader.onload = function(e) {
      var img = new Image();
      img.onload = function() {
        var w = img.width, h = img.height;
        // Only resize if larger than max
        if (w > MAX_W || h > MAX_H) {
          var ratio = Math.min(MAX_W / w, MAX_H / h);
          w = Math.round(w * ratio);
          h = Math.round(h * ratio);
        }
        var canvas = document.createElement('canvas');
        canvas.width = w; canvas.height = h;
        var ctx = canvas.getContext('2d');
        ctx.drawImage(img, 0, 0, w, h);
        var compressed = canvas.toDataURL('image/jpeg', 0.75);
        var preview = document.getElementById('ssPreview');
        if (preview) preview.innerHTML = '<img src="'+compressed+'" style="max-width:200px;border-radius:4px;border:1px solid #d1d5db"><div style="font-size:10px;color:#64748b;margin-top:2px">Original '+Math.round(file.size/1024)+'KB -> compressed ~'+Math.round(compressed.length*0.75/1024)+'KB</div>'; if (!drIntel) drIntel = {}; drIntel._ssPreview = compressed; try { localStorage.setItem('ss_preview_'+dp.id, compressed); } catch(e) {}
      };
      img.src = e.target.result;
    };
    reader.readAsDataURL(file);
  });

  // Screenshot analyze button
  var ssBtn = document.getElementById('ssAnalyzeBtn');
  if (ssBtn) ssBtn.addEventListener('click', async function() {
    var preview = document.getElementById('ssPreview');
    var img = preview ? preview.querySelector('img') : null;
    if (!img) { T('Choose a screenshot file first', '#dc2626'); return; }
    var imageB64 = img.src; // already data:...;base64,...
    ssBtn.disabled = true;
    ssBtn.textContent = 'Analyzing...';
    T('AI is analyzing the screenshot...');
    try {
      var imageType = document.getElementById('ssType').value;
      var ssBody = {image_b64: imageB64, image_type: imageType};
      var ssModel = getPanelModel('model_ss');
      if (ssModel !== 'auto') ssBody.model_override = ssModel;
      var r = await api('/ai/analyze-screenshot/'+dp.id, {method:'POST', body: ssBody});
      if (r.success) {
        T('Screenshot analysis complete', '#16a34a');
        drIntel = await api('/intelligence/'+dp.id);
        renderDrawer();
      } else {
        T('Analysis failed: '+(r.error||'Unknown'), '#dc2626');
      }
    } catch(e) {
      T('Request failed: '+(e.detail||e.message||''), '#dc2626');
    }
    ssBtn.disabled = false;
    ssBtn.textContent = 'Analyze screenshot';
  });
}

// ── TAB: Message Generation ──
let msgChatHistory = [];
let msgCurrentType = 'cold_email';
let msgCurrentTone = 'human';

function DTMsg(b){
  var h = '';
  // ── Section 1: Conversation ion history summary (collapsible) ──
  var hasHistory = (drInts.length > 0 || drSeqs.length > 0);
  h += '<div class="card p3 mb3" style="background:#f8fafc;border:1px solid #e2e8f0">';
  h += '<div class="flex jcs aic" style="cursor:pointer" id="msgToggleHist">';
  h += '<span class="fwm fs12">Conversation history ('+drInts.length+' interactions / '+drSeqs.length+'plan steps)</span>';
  h += '<span id="msgHistArrow" style="font-size:10px;color:#64748b">▼</span></div>';
  h += '<div id="msgHistBody" style="margin-top:6px;max-height:200px;overflow-y:auto;font-size:11px;line-height:1.6">';
  if(hasHistory){
    drSeqs.forEach(function(s){
      h += '<div style="padding:2px 4px;margin-bottom:2px;background:#f0f4ff;border-left:3px solid #3b82f6;border-radius:2px">';
      h += '<span style="color:#64748b">['+fd(s.scheduled_date)+']</span> <b style="color:#4f46e5">Outbound '+E(s.channel||'')+'</b>: '+E(htmlToPlain(s.content||s.subject||'').substring(0,80))+'</div>';
    });
    drInts.forEach(function(i){
      var isIn = i.direction === 'inbound';
      h += '<div style="padding:2px 4px;margin-bottom:2px;background:'+(isIn?'#f0fdf4':'#eff6ff')+';border-left:3px solid '+(isIn?'#16a34a':'#3b82f6')+';border-radius:2px">';
      h += '<span style="color:#64748b">['+fd(i.interacted_at)+']</span> <b style="color:'+(isIn?'#16a34a':'#2563eb')+'">'+(isIn?'Customer':'Outbound')+' '+E(i.channel||'')+'</b>: '+E(htmlToPlain(i.content||i.subject||'').substring(0,80));
      if(i.reply_intent) h += ' <span style="background:#fefce8;border-radius:2px;padding:0 3px;font-size:10px;color:#854d0e">'+E(i.reply_intent)+'</span>';
      h += '</div>';
    });
  } else { h += '<span style="color:#64748b">No history yet</span>'; }
  h += '</div></div>';

  // ── Section 2: Action buttons ──
  h += '<div style="display:flex;gap:8px;margin-bottom:12px">';
  h += '<button class="btn" style="background:#f59e0b;color:#fff;flex:1" id="followupSingleBtn">Smart follow-up (draft email)</button>';
  h += '<button class="btn" style="background:#7c3aed;color:#fff;flex:1" id="brainstormBtn">Analyze conversation and suggest reply angles</button>';
  h += '<button class="btn" style="background:#059669;color:#fff;flex:1" id="proposalBtn">Generate proposal-style quote</button>';
  h += '</div>';
  h += '<div style="display:flex;gap:6px;margin-bottom:8px;align-items:center">';
  h += '<span class="fs11 c6">Model:</span>';
  h += renderModelSelector('model_followup', 'Follow-up');
  h += renderModelSelector('model_brainstorm', 'Ideas');
  h += renderModelSelector('model_generate', 'Generate');
  h += '</div>';
  h += '<div id="approachesR"></div>';

  // ── Section 3: Draft result area ──
  h += '<div id="msgDraftR"></div>';
  b.innerHTML = h;

  // Toggle history collapse
  var toggleBtn = document.getElementById('msgToggleHist');
  var histBody = document.getElementById('msgHistBody');
  var histArrow = document.getElementById('msgHistArrow');
  if(toggleBtn) toggleBtn.addEventListener('click', function(){
    if(histBody.style.display === 'none'){ histBody.style.display = 'block'; histArrow.textContent = '▼'; }
    else { histBody.style.display = 'none'; histArrow.textContent = '▶'; }
  });

  // Single-client smart followup button
  var fuBtn = document.getElementById('followupSingleBtn');
  if(fuBtn) fuBtn.addEventListener('click', async function(){
  if(!dp.email && !dp.dm_email){ T('This customer has no email; cannot generate a follow-up', '#dc2626'); return; }
    fuBtn.disabled = true; fuBtn.textContent = 'AI drafting...';
    try {
      var followupBody = {};
      var fuModel = getPanelModel('model_followup');
      if(fuModel !== 'auto') followupBody.model_override = fuModel;
      var res = await api('/ai/followup/'+dp.id, {method:'POST', body:followupBody});
      if(res.success){
        showDraftHint('AI drafted the follow-up email');
        try { await loadEmail(); } catch(e) {}
      } else {
        T('Failed: '+(res.error||'Unknown'), '#dc2626');
      }
    } catch(e) {
      T('Request failed: '+(e.detail||e.message||e), '#dc2626');
    }
    fuBtn.disabled = false; fuBtn.textContent = 'Smart follow-up (draft email)';
  });

  // Brainstorm button
  var bsBtn = document.getElementById('brainstormBtn');
  if(bsBtn) bsBtn.addEventListener('click', async function(){
    bsBtn.disabled = true; bsBtn.textContent = 'AI analyzing...';
    try {
      var bsBody = {};
      var bsModel = getPanelModel('model_brainstorm');
      if(bsModel !== 'auto') bsBody.model_override = bsModel;
      var res = await api('/ai/brainstorm-reply-approaches/'+dp.id, {method:'POST', body:bsBody});
      console.log('Brainstorm result:', res);
      if(!res.success){ T('Analysis failed: '+(res.error||'').substring(0,80), '#dc2626'); bsBtn.disabled = false; bsBtn.textContent = 'Analyze conversation and suggest reply angles'; return; }
      var approaches = res.approaches || [];
      if(!approaches.length){ T('AI returned no usable ideas', '#dc2626'); bsBtn.disabled = false; bsBtn.textContent = 'Analyze conversation and suggest reply angles'; return; }
      renderApproaches(approaches, b);
      bsBtn.disabled = false; bsBtn.textContent = 'Analyze again';
    } catch(e) {
      T('Analysis failed: '+(e.detail||e.message||String(e)).substring(0,80), '#dc2626');
      bsBtn.disabled = false; bsBtn.textContent = 'Analyze conversation and suggest reply angles';
    }
  });

  // Proposal button — generate structured cooperation proposal
  var propBtn = document.getElementById('proposalBtn');
  if(propBtn) propBtn.addEventListener('click', async function(){
    propBtn.disabled = true; propBtn.textContent = 'Generating...';
    try {
      var deal = dp.deals && dp.deals.length > 0 ? dp.deals[dp.deals.length - 1] : null;
      var note = deal ? (deal.note || '') : '';
      var amount = deal ? (deal.amount || '') : '';
      var propBody2 = { spec_note: note, target_price: String(amount) };
      var genModel = getPanelModel('model_generate');
      if(genModel !== 'auto') propBody2.model_override = genModel;
      var res = await api('/ai/generate-proposal/'+dp.id, {method:'POST', body:propBody2});
      if(!res.success){ T('Generation failed: '+(res.error||'').substring(0,80), '#dc2626'); propBtn.disabled = false; propBtn.textContent = 'Generate proposal-style quote'; return; }
      renderProposal(res.proposal, b);
      propBtn.disabled = false; propBtn.textContent = 'Regenerate quote proposal';
    } catch(e) {
      T('Generation failed: '+(e.detail||e.message||String(e)).substring(0,80), '#dc2626');
      propBtn.disabled = false; propBtn.textContent = 'Generate proposal-style quote';
    }
  });
}

function renderApproaches(approaches, b){
  var arDiv = document.getElementById('approachesR');
  if(!arDiv) return;
  var h = '<p class="fwm fs12 mb2">Choose a reply direction (' + approaches.length + ' ideas）</p>';
  approaches.forEach(function(a, idx){
    var toneColors = {warm:'#ec4899', technical:'#6366f1', formal:'#475569', human:'#f59e0b'};
    var tc = toneColors[a.tone] || '#64748b';
    h += '<div class="card p3 mb2 approach-card" data-approach="'+idx+'" style="cursor:pointer;border:1px solid #e2e8f0;transition:border-color .15s" onmouseover="this.style.borderColor=\'#7c3aed\'" onmouseout="this.style.borderColor=\'#e2e8f0\'">';
    h += '<div class="flex jcs aic mb1"><b class="fs13" style="color:#334155">'+E(a.label||'Approach '+(idx+1))+'</b><span style="font-size:10px;background:'+tc+';color:#fff;padding:1px 6px;border-radius:8px">'+E(a.tone||'warm')+'</span></div>';
    h += '<p class="fs11 c6 mb1">'+E(a.angle||'')+'</p>';
    if(a.keyPoints && a.keyPoints.length){
      h += '<div class="fs10 c6 mb1">';
      a.keyPoints.forEach(function(kp){ h += '<span style="background:#f8fafc;padding:1px 4px;border-radius:2px;margin-right:4px">'+E(kp)+'</span>'; });
      h += '</div>';
    }
    if(a.suggestedSubject) h += '<p class="fs10" style="color:#4f46e5">Subject: '+E(a.suggestedSubject)+'</p>';
    if(a.openingLine) h += '<p class="fs10" style="color:#16a34a;font-style:italic">Opening: '+E(a.openingLine)+'</p>';
    h += '</div>';
  });
  arDiv.innerHTML = h;

  // Click approach → generate full draft
  arDiv.querySelectorAll('.approach-card').forEach(function(card){
    card.addEventListener('click', async function(){
      var idx = parseInt(card.dataset.approach);
      var a = approaches[idx];
      if(!a) return;
      // Highlight selected
      arDiv.querySelectorAll('.approach-card').forEach(function(c){ c.style.borderColor = '#e2e8f0'; });
      card.style.borderColor = '#7c3aed'; card.style.background = '#f5f3ff';

      T('AI writing the full email...', '#7c3aed');
      try {
        // Use the existing generate-message endpoint with approach context
        var genMsgBody = {
          message_type: 'cold_email',
          tone: a.tone || 'warm',
          additional_context: 'APPROACH: '+(a.label||'')+'\nANGLE: '+(a.angle||'')+'\nKEY POINTS: '+(a.keyPoints||[]).join(', ')+'\nOPENING LINE: '+(a.openingLine||'')+'\nSUGGESTED SUBJECT: '+(a.suggestedSubject||'')
        };
        var genModel = getPanelModel('model_generate');
        if(genModel !== 'auto') genMsgBody.model_override = genModel;
        var genR = await api('/ai/generate-message/'+dp.id, {method:'POST', body: genMsgBody});
        if(genR.success){
          msgResult = genR.result;
          showMessageResultSimple(b, a);
          T('GenerateDone', '#16a34a');
        } else {
          T('Generation failed: '+(genR.error||'').substring(0,60), '#dc2626');
        }
      } catch(e) {
        T('Generation failed: '+(e.detail||e.message||String(e)).substring(0,80), '#dc2626');
      }
    });
  });
}

function showMessageResultSimple(b, approach){
  var r = msgResult;
  var draftDiv = document.getElementById('msgDraftR');
  if(!draftDiv) return;
  // Handle various AI response key names
  var subj = r.subject || r.title || r.Subject || (approach ? approach.suggestedSubject : '') || '';
  var body = r.body || r.content || r.message || r.Body || r.text || '';
  var mr = '<div class="card p3 mt3" style="border:2px solid #7c3aed;border-radius:8px;background:#fefce8">';
  mr += '<div class="flex jcs aic mb2"><span class="fs12 fwb" style="color:#5b21b6">Draft — '+(approach?E(approach.label||'Reply'):'Reply')+'</span>';
  mr += '<span style="display:flex;gap:4px">';
  mr += '<button class="btn btn-sm" onclick="var eb=document.getElementById(\'editBody2\');if(eb)navigator.clipboard.writeText(eb.value);T(\'Copied\')">Copy</button>';
  mr += '<button class="btn btn-sm" style="background:#6366f1" onclick="var eb=document.getElementById(\'editBody2\');if(eb){var sig='+JSON.stringify(getProfileSignature(dp && dp.profile_type))+';eb.value=eb.value+\'\\n\\n\'+sig;T(\'Signed\')}">+Sign</button>';
  mr += '<button class="btn btn-sm" style="background:#34d399" onclick="var s=document.getElementById(\'editSubj2\').value;var bd=document.getElementById(\'editBody2\').value;authFetch(\'/api/email/queue\',{method:\'POST\',headers:{\'Content-Type\':\'application/json\'},body:JSON.stringify({prospect_id:'+dp.id+',to_email:\''+E(dp.email||dp.dm_email||'')+'\',subject:s||\'\',body:bd,status:\'draft\'})}).then(function(r){return r.json()}).then(function(){showDraftHint(\'Reply draft saved\');loadEmail()})">Save draft</button>';
  mr += '</span></div>';
  mr += '<label class="fs11 c6">Subject</label><input id="editSubj2" value="'+E(subj)+'" style="font-size:12px;margin-bottom:6px">';
  mr += '<label class="fs11 c6">Body</label><textarea id="editBody2" rows="10" style="font-size:13px;line-height:1.6">'+E(body)+'</textarea>';
  mr += '</div>';
  draftDiv.innerHTML = mr;
}

// ── TAB: Quote History ──
async function DTQuotes(b){
  var quotes = [];
  try { quotes = await api('/quote-history?prospect_id='+dp.id); } catch(e) { quotes = []; }
  var h = '<div class="flex jcs aic mb3"><span class="fs14 fwb">Quote History ('+quotes.length+')</span>';
  h += '<div style="display:flex;gap:4px"><button class="btn btn-sm" style="background:#34d399" id="drQuoteAdd">+ New quote</button>';
  h += '<button class="btn btn-sm" style="background:#6366f1" id="drQuoteAi">🤖 AI extract</button>';
  h += '<button class="btn btn-sm" style="background:#7c3aed" id="drPanorama">🧠 Conversation ion panorama</button></div></div>';
  h += '<div id="drPanoramaBox" style="margin-bottom:10px"></div>';
  if(!quotes.length){
  h += '<div class="card tc" style="padding:20px;color:#64748b">No quote history<br><span class="fs11">Use AI extract to pull from emails, or add manually</span></div>';
  } else {
    quotes.forEach(function(q){
      var isAi = q.ai_extracted === 1;
      var isInquiry = q.direction === 'inquiry';
      var typeColor = isInquiry ? '#f97316' : '#2563eb';
      var typeLabel = isInquiry ? 'Inquiry from customer' : 'Our quote';
      h += '<div class="card p3 mb2" style="border-left:4px solid '+typeColor+'">';
      h += '<div class="flex jcs aic mb2"><span class="fwm">'+(q.quote_date||'-')+(q.product?' · '+E(q.product):'')+'</span>';
      h += '<div style="display:flex;gap:4px;align-items:center">';
      h += '<span class="badge" style="background:'+typeColor+';color:#fff">'+typeLabel+'</span>';
  h += isAi ? '<span class="badge" style="background:#f59e0b;color:#fff">AI draft</span>' : '<span class="badge" style="background:#16a34a;color:#fff">Confirmed</span>';
      h += '</div></div>';
      var line = [];
      if(q.unit_price) line.push(isInquiry ? 'Target price <b>'+E(q.unit_price)+'</b>' : 'Unit price <b>'+E(q.unit_price)+'</b>');
      if(q.qty) line.push('Qty '+E(q.qty));
      if(q.total) line.push('Total <b style="color:#16a34a">'+E(q.total)+'</b>');
      if(q.currency && !isInquiry) line.push(E(q.currency));
      if(line.length) h += '<div class="fs12 mb1">'+line.join(' · ')+'</div>';
      if(q.spec) h += '<p class="fs11 c6 mb1">Spec: '+E(q.spec)+'</p>';
      if(q.terms) h += '<p class="fs11 c6 mb1"> Terms: '+E(q.terms)+'</p>';
      if(q.summary) h += '<p class="fs11 c6 mb1" style="color:#475569">'+E(q.summary)+'</p>';
      if(q.source_subject) h += '<p class="fs10 c6 mt1">Source: '+E(q.source_subject).substring(0,80)+'</p>';
      h += '<div class="mt2" style="display:flex;gap:4px;flex-wrap:wrap"><button class="btn btn-sm" style="background:#0ea5e9" data-dr-orig-quote="'+q.id+'">View original</button><button class="btn btn-sm" style="background:#3b82f6" data-dr-edit-quote="'+q.id+'">Confirm / Edit</button><button class="btn btn-sm" style="background:#f87171" data-dr-del-quote="'+q.id+'">Delete</button></div>';
      h += '<div id="drQuoteOrig-'+q.id+'" style="display:none;margin-top:8px;border:1px solid #e2e8f0;background:#f8fafc;border-radius:6px;padding:8px;font-size:11px;line-height:1.6;color:#334155;white-space:pre-wrap;max-height:280px;overflow-y:auto">'+(q.source_content?E(q.source_content):'<span class="c6">(no original text)</span>')+'</div>';
      h += '</div>';
    });
  }
  b.innerHTML = h;

  bindSafe(b,'#drQuoteAdd','click',function(){ showDrQuoteForm(b, null); });
  bindSafe(b,'#drQuoteAi','click',function(){
    var btn = document.getElementById('drQuoteAi');
    if(btn){ btn.disabled = true; btn.textContent = 'Extracting...'; }
    api('/quote-history/extract?prospect_id='+dp.id,{method:'POST'}).then(function(r){
      T('AI extracted - added '+r.added+' quote records','#16a34a');
      DTQuotes(b);
    }).catch(function(){ T('Extraction failed','#dc2626'); DTQuotes(b); });
  });
  bindSafe(b,'#drPanorama','click',function(){
    var btn = document.getElementById('drPanorama');
    if(btn){ btn.disabled = true; btn.textContent = 'Analyzing...'; }
    api('/quote-history/panorama?prospect_id='+dp.id,{method:'POST'}).then(function(r){
      if(r && r.success){
        renderPanorama(b, r.report);
        T('Conversation panorama generated','#16a34a');
      } else {
        T((r&&r.error)||'Analysis failed','#dc2626');
        renderPanoramaBoxEmpty(b, (r&&r.error)||'');
      }
    }).catch(function(e){ T('Analysis failed','#dc2626'); renderPanoramaBoxEmpty(b, (e&&e.detail)||''); })
    .finally(function(){ if(btn){ btn.disabled = false; btn.textContent = '🧠 Conversation ion panorama'; } });
  });

  // 自动加载已Generate的全景
  api('/quote-history/panorama?prospect_id='+dp.id).then(function(r){
    if(r && r.exists && r.report){
      renderPanorama(b, r.report);
    } else {
      renderPanoramaBoxEmpty(b, '');
    }
  }).catch(function(){ renderPanoramaBoxEmpty(b, ''); });

  b.querySelectorAll('[data-dr-edit-quote]').forEach(function(el){
    el.addEventListener('click',function(){ showDrQuoteForm(b, parseInt(el.dataset.drEditQuote)); });
  });
  b.querySelectorAll('[data-dr-orig-quote]').forEach(function(el){
    el.addEventListener('click',function(){
      var box = document.getElementById('drQuoteOrig-'+el.dataset.drOrigQuote);
      if(box){ box.style.display = box.style.display === 'none' ? 'block' : 'none'; }
    });
  });
  b.querySelectorAll('[data-dr-del-quote]').forEach(function(el){
    el.addEventListener('click',function(){
      if(!confirm('Delete this quote record?')) return;
      api('/quote-history/'+parseInt(el.dataset.drDelQuote),{method:'DELETE'}).then(function(){T('Deleted');DTQuotes(b);}).catch(function(){T('Delete failed','#dc2626')});
    });
  });
}

function showDrQuoteForm(b, editId){
  var h = '<div class="card p3 mb3" style="border:2px solid #2563eb;border-radius:8px;background:#f8fafc">';
  h += '<p class="fs13 fwb mb3" style="color:#4f46e5">'+(editId?'Edit quote':'New quote')+'</p>';
  if(editId) h += '<input type="hidden" id="drQuoteEditId" value="'+editId+'">';
  h += '<div class="mb2"><label class="fs11 c6">Quote date</label><input type="date" id="drQuoteDate"></div>';
  h += '<div class="mb2"><label class="fs11 c6">Type</label><select id="drQuoteDir"><option value="quote">Our quote</option><option value="inquiry">Inquiry from customer</option></select></div>';
  h += '<div class="mb2"><label class="fs11 c6">Product</label><input id="drQuoteProduct" placeholder="e.g. product model / part number from your catalog"></div>';
  h += '<div class="mb2"><label class="fs11 c6">Spec</label><input id="drQuoteSpec" placeholder="e.g. +/-0.01mm, >=97% transmission"></div>';
  h += '<div class="flex g2 mb2"><div style="flex:1"><label class="fs11 c6">Qty</label><input id="drQuoteQty" placeholder="e.g. 500 pcs"></div>';
  h += '<div style="flex:1"><label class="fs11 c6">Unit price / target</label><input id="drQuotePrice" placeholder="e.g. $8.00"></div></div>';
  h += '<div class="flex g2 mb2"><div style="flex:1"><label class="fs11 c6">Total</label><input id="drQuoteTotal" placeholder="e.g. $4000"></div>';
  h += '<div style="flex:1"><label class="fs11 c6">Currency</label><input id="drQuoteCur" placeholder="USD/EUR/CNY"></div></div>';
  h += '<div class="mb2"><label class="fs11 c6">Terms / Note</label><textarea id="drQuoteTerms" rows="2" placeholder="FOB, 30% deposit, 4-week lead time"></textarea></div>';
  h += '<div class="mb2"><label class="fs11 c6">Summary</label><input id="drQuoteSummary" placeholder="One-line summary of this quote"></div>';
  h += '<div class="flex g2"><button class="btn btn-sm" style="background:#6366f1" id="drQuoteSave">Save</button><button class="btn btn-sm" style="background:#e5e7eb;color:#334155" id="drQuoteCancel">Cancel</button></div>';
  h += '</div>';

  var formDiv = document.createElement('div');
  formDiv.id = 'drQuoteForm';
  formDiv.innerHTML = h;
  var addBtn = document.getElementById('drQuoteAdd');
  if(addBtn) addBtn.insertAdjacentElement('afterend', formDiv);

  if(editId){
    api('/quote-history?prospect_id='+dp.id).then(function(all){
      var q = all.find(function(x){ return x.id === editId; });
      if(!q) return;
      var f = document.getElementById('drQuoteDate'); if(f) f.value = q.quote_date||'';
      var d = document.getElementById('drQuoteDir'); if(d) d.value = q.direction||'quote';
      var p = document.getElementById('drQuoteProduct'); if(p) p.value = q.product||'';
      var s = document.getElementById('drQuoteSpec'); if(s) s.value = q.spec||'';
      var qt = document.getElementById('drQuoteQty'); if(qt) qt.value = q.qty||'';
      var pr = document.getElementById('drQuotePrice'); if(pr) pr.value = q.unit_price||'';
      var t = document.getElementById('drQuoteTotal'); if(t) t.value = q.total||'';
      var c = document.getElementById('drQuoteCur'); if(c) c.value = q.currency||'';
      var tm = document.getElementById('drQuoteTerms'); if(tm) tm.value = q.terms||'';
      var sm = document.getElementById('drQuoteSummary'); if(sm) sm.value = q.summary||'';
    }).catch(function(){});
  }

  function closeForm(){ var f = document.getElementById('drQuoteForm'); if(f) f.remove(); }
  var cancelBtn = document.getElementById('drQuoteCancel');
  if(cancelBtn) cancelBtn.onclick = closeForm;
  var saveBtn = document.getElementById('drQuoteSave');
  if(saveBtn) saveBtn.onclick = function(){
    var body = {
      prospect_id: dp.id,
      direction: document.getElementById('drQuoteDir').value,
      quote_date: document.getElementById('drQuoteDate').value,
      product: document.getElementById('drQuoteProduct').value.trim(),
      spec: document.getElementById('drQuoteSpec').value.trim(),
      qty: document.getElementById('drQuoteQty').value.trim(),
      unit_price: document.getElementById('drQuotePrice').value.trim(),
      total: document.getElementById('drQuoteTotal').value.trim(),
      currency: document.getElementById('drQuoteCur').value.trim(),
      terms: document.getElementById('drQuoteTerms').value.trim(),
      summary: document.getElementById('drQuoteSummary').value.trim()
    };
    var url = editId ? '/quote-history/'+editId : '/quote-history';
    var method = editId ? 'PUT' : 'POST';
    api(url,{method:method,body:body}).then(function(){ T('Saved','#16a34a'); DTQuotes(b); }).catch(function(){ T('Save failed','#dc2626'); });
  };
}

function renderPanoramaBoxEmpty(b, msg, boxId){
  var box = document.getElementById(boxId || 'drPanoramaBox');
  if(!box) return;
  if(msg){
    box.innerHTML = '<div class="card p3" style="border:1px solid #fca5a5;background:#fef2f2;color:#b91c1c;font-size:12px">'+E(msg)+'</div>';
  } else {
    box.innerHTML = '<div class="card p3 tc" style="border:1px dashed #c4b5fd;background:#faf5ff;color:#7c3aed;font-size:12px;padding:16px">🧠 Click Conversation panorama to analyze the latest 20 emails; AI summarizes needs, price, status and next steps.</div>';
  }
}

function renderPanorama(b, report, boxId){
  var box = document.getElementById(boxId || 'drPanoramaBox');
  if(!box || !report) return;
  var h = '<div class="card p3" style="border:1px solid #ddd6fe;background:#f5f3ff;font-size:12px;line-height:1.7">';
  h += '<div class="flex jcs aic mb2"><span class="fwm fs13" style="color:#5b21b6">🧠 AI Conversation ion panorama</span><span class="fs10 c6">Comprehensive email understanding</span></div>';
  if(report.overview) h += '<p class="mb2"><b style="color:#4c1d95">Overview: </b>'+E(report.overview)+'</p>';
  if(report.price_flow) h += '<p class="mb2"><b style="color:#4c1d95">Price flow: </b>'+E(report.price_flow)+'</p>';
  if(report.status) h += '<p class="mb2"><b style="color:#4c1d95">Current status: </b>'+E(report.status)+'</p>';
  if(report.products && report.products.length){
    h += '<div class="mb2"><b style="color:#4c1d95">Products ('+report.products.length+'):</b></div>';
    report.products.forEach(function(pd){
      var bits = [];
      if(pd.name) bits.push(E(pd.name));
      if(pd.spec) bits.push('Spec '+E(pd.spec));
      if(pd.qty) bits.push('Qty '+E(pd.qty));
      if(pd.price_note) bits.push('Price: '+E(pd.price_note));
      if(pd.extra) bits.push('Requirement: '+E(pd.extra));
      h += '<div style="padding:4px 8px;margin-bottom:4px;background:#fff;border:1px solid #e9e5ff;border-radius:6px">'+bits.join(' · ')+'</div>';
    });
  }
  if(report.requirements && report.requirements.length){
    h += '<div class="mb2"><b style="color:#4c1d95">Customer requirements ('+report.requirements.length+'):</b></div>';
    report.requirements.forEach(function(r){ h += '<div style="padding:2px 0">📌 '+E(r)+'</div>'; });
  }
  if(report.open_questions && report.open_questions.length){
    h += '<div class="mb2"><b style="color:#b45309">Open questions ('+report.open_questions.length+'):</b></div>';
    report.open_questions.forEach(function(r){ h += '<div style="padding:2px 0">❓ '+E(r)+'</div>'; });
  }
  if(report.commitments && report.commitments.length){
    h += '<div class="mb2"><b style="color:#0f766e">Our commitments ('+report.commitments.length+'):</b></div>';
    report.commitments.forEach(function(r){ h += '<div style="padding:2px 0">🤝 '+E(r)+'</div>'; });
  }
  if(report.signals && report.signals.length){
    h += '<div class="mb2"><b style="color:#4c1d95">Key signals:</b></div>';
    report.signals.forEach(function(s){ h += '<div style="padding:2px 0">⚡ '+E(s)+'</div>'; });
  }
  if(report.next_action) h += '<div class="mt2" style="background:#ede9fe;border:1px solid #c4b5fd;border-radius:6px;padding:8px"><b style="color:#4c1d95">Next step: </b> '+E(report.next_action)+'</div>';
  h += '</div>';
  box.innerHTML = h;
}

function renderProposal(proposal, b){
  var draftDiv = document.getElementById('msgDraftR');
  if(!draftDiv) return;
  var sec = proposal.sections || {};
  var sectionNames = {
    '1_specs': '1. Product Specifications', '2_packaging': '2. Packaging',
    '3_lead_time': '3. Lead Time', '4_sample_policy': '4. Sample Policy',
    '5_payment_terms': '5. Payment Terms', '6_key_selling_points': '6. Key Selling Points',
    '7_channel_fit': '7. Channel Fit', '8_next_step': '8. Next Step'
  };
  var h = '<div class="card p4 mt3" style="border:2px solid #059669;border-radius:8px;background:#f0fdf6">';
  h += '<div class="flex jcs aic mb3"><span class="fs14 fwb" style="color:#065f46">Proposal — ' + E(proposal.proposal_title || 'Cooperation Proposal') + '</span>';
  h += '<span style="display:flex;gap:4px">';
  h += '<button class="btn btn-sm" id="propCopyBtn">Copy</button>';
  h += '<button class="btn btn-sm" style="background:#6366f1" id="propSignBtn">+Sign</button>';
  h += '<button class="btn btn-sm" style="background:#34d399" id="propQueueBtn">Save draft</button>';
  h += '</span></div>';
  if(proposal.subject) h += '<p class="fs12 c6 mb3">Subject: ' + E(proposal.subject) + '</p>';
  for(var key in sectionNames){
    var content = sec[key] || '';
    if(!content) continue;
    h += '<div class="mb3"><span class="fwb fs13" style="color:#059669">' + sectionNames[key] + '</span>';
    h += '<p class="fs13 mt1" style="line-height:1.7;white-space:pre-wrap">' + E(content) + '</p></div>';
  }
  if(proposal.total_estimated_value) h += '<div class="p2 mb2" style="background:#d1fae5;border-radius:4px"><span class="fwb fs13">Estimated Order Value: </span><span class="fs13">' + E(proposal.total_estimated_value) + '</span></div>';
  if(proposal.notes) h += '<div class="p2" style="background:#fefce8;border-radius:4px"><span class="fwb fs12" style="color:#92400e">Notes: </span><span class="fs12">' + E(proposal.notes) + '</span></div>';
  h += '</div>';
  draftDiv.innerHTML = h;

  var cpBtn = document.getElementById('propCopyBtn');
  if(cpBtn) cpBtn.onclick = function(){
    var text = (proposal.subject || 'Proposal') + '\n\n';
    for(var key in sectionNames){ if(sec[key]) text += sectionNames[key] + '\n' + sec[key] + '\n\n'; }
    if(proposal.total_estimated_value) text += 'Estimated Order Value: ' + proposal.total_estimated_value + '\n\n';
    if(proposal.notes) text += 'Notes: ' + proposal.notes;
    navigator.clipboard.writeText(text);
    T('Proposal copied');
  };

  var sigBtn = document.getElementById('propSignBtn');
  if(sigBtn) sigBtn.onclick = function(){
    var sig = getProfileSignature(dp && dp.profile_type);
    if(proposal.notes) proposal.notes += '\n\n' + sig;
    else proposal.notes = sig;
    renderProposal(proposal, b);
    T('Signed');
  };

  var qBtn = document.getElementById('propQueueBtn');
  if(qBtn) qBtn.onclick = function(){
    var body = (proposal.subject || 'Proposal') + '\n\n';
    for(var key in sectionNames){ if(sec[key]) body += sectionNames[key] + '\n' + sec[key] + '\n\n'; }
    if(proposal.total_estimated_value) body += 'Estimated Order Value: ' + proposal.total_estimated_value + '\n\n';
    if(proposal.notes) body += 'Notes: ' + proposal.notes;
    api('/email/queue',{method:'POST',body:{prospect_id:dp.id,to_email:dp.email||dp.dm_email||'',subject:proposal.subject||'Proposal — {{COMPANY}}',body:body,status:'draft',sender_key:getSenderKey('email_sender')}}).then(function(){ showDraftHint('Proposal saved to drafts'); loadEmail(); });
  };
}

// ── TAB: Intel + Report（合并展示：先情报Analyze，再Background report，内容与逻辑不变）──
function DTIntelCombined(b){
  DTIntel(b);
  var tmp = document.createElement('div');
  try { DTReport(tmp); } catch(e) { tmp.innerHTML = ''; }
  b.insertAdjacentHTML('beforeend', '<div style="height:1px;background:#e4e9f2;margin:22px 0 24px"></div>' + tmp.innerHTML);
}

// ── TAB: Report ──
function DTReport(b){
  var gNews = 'https://www.google.com/search?q='+encodeURIComponent((dp.company||'')+' lawsuit OR litigation OR fraud OR bankruptcy OR acquisition');
  var gCompany = 'https://www.google.com/search?q='+encodeURIComponent((dp.company||'')+' linkedin');
  var gDomain = 'https://www.whois.com/whois/'+encodeURIComponent(dp.website||'');
  var h='<div class="card p4" style="border:2px solid #2563eb;border-radius:8px;background:#f0f9ff">';
  h+='<p class="fs16 fwb mb3" style="color:#4f46e5">'+E(dp.company)+' - Background report</p>';
  h+='<p class="fs13 fwb mb2">Basic info</p><table class="mb3" style="font-size:12px"><tbody>';
  [['Company',dp.company],['Country',dp.country],['Size',dp.size],['Industry',dp.industry],['Website',dp.website],['Email',dp.email||dp.dm_email],['LinkedIn',dp.linkedin],['Status',dp.status]].forEach(function(r){if(r[1])h+='<tr><td class="c6" style="width:120px">'+r[0]+'</td><td>'+E(r[1])+'</td></tr>';});
  h+='</tbody></table>';
  if(dp.ai_score){var sc=dp.ai_score,scC=sc>=75?'#16a34a':sc>=50?'#ca8a04':'#dc2626';h+='<p class="fs13 fwb mb2">AI Score</p><div class="p3 mb3" style="background:#fff;border:1px solid #e2e8f0;border-radius:6px"><span class="fs24 fwb" style="color:'+scC+'">'+sc+'</span><span class="fs14 c6">/100</span><span class="badge">'+dp.value_level+' / '+dp.profile_type+'</span><p class="fs13 mt1">'+E(dp.score_reason||'')+'</p></div>';}else{h+='<div class="p3 mb3" style="background:#fefce8;border:1px solid #fef08a;border-radius:6px;font-size:13px;color:#854d0e">Not scored yet</div>';}
  var hi=drIntel&&(drIntel.website_content||drIntel.linkedin_content);h+='<p class="fs13 fwb mb2">Website intelligence</p><div class="p3 mb3" style="background:#fff;border:1px solid #e2e8f0;border-radius:6px;font-size:12px">';if(hi){if(drIntel.website_content)h+='<p class="mb2"><span class="fwm">Website:</span> '+E(drIntel.website_content).substring(0,300)+'</p>';if(drIntel.linkedin_content)h+='<p><span class="fwm">LinkedIn:</span> '+E(drIntel.linkedin_content).substring(0,200)+'</p>';}else{h+='<span class="c6">No data yet</span>';}h+='</div>';
  // Domain whois in report
  if(drIntel && drIntel.domain_registered_at){
    var ddom = new Date(drIntel.domain_registered_at);
    var domDays = Math.floor((new Date() - ddom) / 86400000);
    var domYears = (domDays / 365.25).toFixed(1);
    var domColor = domDays > 365*3 ? '#16a34a' : domDays > 365 ? '#ca8a04' : '#dc2626';
    h+='<p class="fs13 fwb mb2">Domain info</p><div class="p3 mb3" style="background:#fff;border:1px solid #e2e8f0;border-radius:6px;font-size:12px">';
    h+='<span class="fwm">Registered:</span> '+ddom.toISOString().substring(0,10)+' <span style="color:'+domColor+';font-weight:600">('+domYears+' years)</span>';
    if(drIntel.domain_expires_at){ var edom = new Date(drIntel.domain_expires_at); h+='<br><span class="fwm">Expires:</span> '+edom.toISOString().substring(0,10); }
    if(drIntel.domain_registrar) h+='<br><span class="fwm">Registrar:</span> '+E(drIntel.domain_registrar);
    h+='</div>';
  }
  if(dp.red_flags){try{var rf=typeof dp.red_flags==='string'?JSON.parse(dp.red_flags):dp.red_flags;if(rf&&rf.length){h+='<p class="fs13 fwb mb2 cr">Risk flags</p><div class="p3 mb3" style="background:#fef5f5;border:1px solid #fecaca;border-radius:6px">';rf.forEach(function(f){h+='<p class="fs12" style="color:#991b1b">'+E(f)+'</p>'});h+='</div>';}}catch(e){}}
  h+='<p class="fs13 fwb mb2">Quick research</p><div class="flex g2 fw mb3" style="font-size:11px"><a href="'+gNews+'" target="_blank" class="btn btn-sm" style="background:#f87171">News / lawsuits</a><a href="'+gDomain+'" target="_blank" class="btn btn-sm" style="background:#4b5563">Domain registration</a><a href="'+gCompany+'" target="_blank" class="btn btn-sm" style="background:#ea4335">Search company</a></div>';
  var v=dp.ai_score&&hi?(sc>=75?'High match and good intelligence; follow up first.':sc>=50?'Valuable; improve intelligence, then follow up.':'Higher risk; proceed carefully.'):'Intelligence incomplete; scrape the website and score first.';
  h+='<div class="p3" style="background:#e0f2fe;border:1px solid #bae6fd;border-radius:8px"><p class="fs13 fwb mb1" style="color:#0369a1">Overall assessment</p><p class="fs13">'+v+'</p></div></div>';
  b.innerHTML=h;
}

// ── TAB: Interactions ──

// ── TAB: Interactions (V2) ──
function DTInt(b){
  var h = '';

  // 公司时间线：同一家公司只加载一次，切换Customer时重新拉
  if (window._companyIntsKey !== dp.id) {
    window._companyIntsKey = dp.id;
    window._companyInts = null;
    api('/interactions/company/' + dp.id).then(function(list){
      window._companyInts = Array.isArray(list) ? list : [];
      DTInt(b);
    }).catch(function(){ window._companyInts = []; DTInt(b); });
  }

  // ═══ TOP: 录入区 ═══
  h += '<div class="card p3 mb3" style="background:#f8fafc;border:1px solid #e2e8f0">';
  h += '<p class="fwm fs13 mb2">Log interaction</p>';

  // Auto-detect toggle + rule hint
  h += '<div class="flex aic g2 mb2" style="font-size:12px">';
  h += '<label class="flex aic g2" style="cursor:pointer"><input type="checkbox" id="intAutoDetect" checked><span style="color:#334155;margin-left:4px">Auto-detect signals</span></label>';
  h += '<span id="intDetectHint" style="color:#64748b;font-size:11px">(only customer replies trigger signals; samples and address detection)</span>';
  h += '</div>';

  // Channel tag group
  var channels = [
    {id:'linkedin', label:'LinkedIn', icon:'💼'},
    {id:'whatsapp', label:'WhatsApp', icon:'📱'},
    {id:'phone', label:'Phone', icon:'📞'},
    {id:'email', label:'Email', icon:'📧'},
    {id:'meeting', label:'Meeting', icon:'🤝'},
    {id:'note', label:'Note', icon:'📋'},
    {id:'other', label:'Other', icon:'📌'}
  ];
  h += '<div id="intChTags" class="flex g2 mb2" style="flex-wrap:wrap">';
  channels.forEach(function(ch){
    h += '<label style="cursor:pointer;font-size:12px;padding:5px 12px;border:1px solid #d1d5db;border-radius:16px;background:#fff;transition:all .15s" data-ch="'+ch.id+'">';
    h += '<input type="radio" name="intCh" value="'+ch.id+'" style="display:none">'+ch.icon+' '+ch.label;
    h += '</label>';
  });
  h += '</div>';

  // Paste textarea
  h += '<textarea id="intPaste" rows="5" placeholder="Paste the conversation directly..." style="width:100%;padding:10px 12px;border:1px solid #d1d5db;border-radius:6px;font-size:13px;line-height:1.6;resize:vertical;font-family:monospace"></textarea>';
  h += '<div id="intDetect" style="margin-top:6px;font-size:12px;min-height:20px;color:#64748b"></div>';

  // Date + Save
  h += '<div class="flex g2 aic mt2">';
  h += '<input id="intDate" type="date" style="padding:6px 10px;border:1px solid #d1d5db;border-radius:6px;font-size:12px" value="'+new Date().toISOString().substring(0,10)+'">';
  h += '<button class="btn" style="background:#34d399;color:#fff;font-size:13px;padding:7px 20px;font-weight:600;border-radius:6px" id="intSaveBtn">💾 Save record</button>';
  h += '</div>';
  h += '</div>';

  // ═══ BOTTOM: 时间轴 ═══
  var useCompany = window._companyInts && window._companyInts.length > 0;
  var baseInts = useCompany ? window._companyInts : (drInts || []);
  var sorted = baseInts.length ? baseInts.slice().sort(function(a,b){
    var da = a.interacted_at || a.created_at || '';
    var db = b.interacted_at || b.created_at || '';
    return db.localeCompare(da);
  }) : [];
  var totalCount = sorted.length;

  // Filter state
  var activeFilter = window._intFilter || 'all';
  var activeDirFilter = window._intDirFilter || 'all';

  // Header with count + filters
  h += '<div class="flex jcs aic mb2">';
  var scopeLabel = useCompany
    ? '🧭 Company timeline (all company '+totalCount+' times · each record tagged by contact)'
    : '📋 interaction timeline ('+totalCount+' records, newest first)';
  h += '<span class="fwm" style="font-size:14px;color:#1f2937">'+scopeLabel+'</span>';
  h += '<div class="flex g2">';
  // Channel filter
  h += '<select id="intFilterCh" style="font-size:11px;padding:3px 8px;border:1px solid #d1d5db;border-radius:4px">';
  h += '<option value="all"'+ (activeFilter==='all'?' selected':'') +'>All channels</option>';
  h += '<option value="email"'+ (activeFilter==='email'?' selected':'') +'>Email</option>';
  h += '<option value="linkedin"'+ (activeFilter==='linkedin'?' selected':'') +'>LinkedIn</option>';
  h += '<option value="whatsapp"'+ (activeFilter==='whatsapp'?' selected':'') +'>WhatsApp</option>';
  h += '<option value="phone"'+ (activeFilter==='phone'?' selected':'') +'>Phone</option>';
  h += '<option value="meeting"'+ (activeFilter==='meeting'?' selected':'') +'>Meeting</option>';
  h += '<option value="note"'+ (activeFilter==='note'?' selected':'') +'>Note</option>';
  h += '</select>';
  // Direction filter
  h += '<select id="intFilterDir" style="font-size:11px;padding:3px 8px;border:1px solid #d1d5db;border-radius:4px">';
  h += '<option value="all"'+ (activeDirFilter==='all'?' selected':'') +'>All directions</option>';
  h += '<option value="outbound"'+ (activeDirFilter==='outbound'?' selected':'') +'>Outbound</option>';
  h += '<option value="inbound"'+ (activeDirFilter==='inbound'?' selected':'') +'>Customer reply</option>';
  h += '</select>';
  h += '</div></div>';

  // Apply filters
  var filtered = sorted.filter(function(i){
    var chMatch = activeFilter==='all' || i.channel===activeFilter;
    var dirMatch = activeDirFilter==='all' || i.direction===activeDirFilter;
    return chMatch && dirMatch;
  });

  if (!filtered.length) {
    h += '<div class="card tc" style="color:#64748b;padding:30px;font-size:13px">No interactionss</div>';
  } else {
    filtered.forEach(function(i, idx) {
      var isLast = idx === filtered.length - 1;
      var d = i.interacted_at || i.created_at || '';
      var dFull = d ? String(d).substring(0,19) : '';
      var chIcon = {email:'📧',linkedin:'💼',whatsapp:'📱',phone:'📞',wechat:'💬',meeting:'🤝',note:'📋',other:'📌'}[i.channel] || '📋';
      var chLabel = {email:'Email',linkedin:'LinkedIn',whatsapp:'WhatsApp',phone:'Phone',wechat:'WeChat',meeting:'Meeting',note:'Note',other:'Other'}[i.channel] || i.channel;
      var dirIcon = i.direction==='inbound'?'📥':'📤';
      var dirColor = i.direction==='inbound'?'#ea580c':'#2563eb';
      var dirBg = i.direction==='inbound'?'#fff7ed':'#eff6ff';
      var dirLabel = i.direction==='inbound'?'Customer reply':'Outbound';
      var hasContent = i.content && i.content.length > 0;
      var isLong = hasContent && i.content.length > 400;
      var contentId = 'intC'+i.id;

      h += '<div style="display:flex;margin-bottom:14px">';
      h += '<div style="width:24px;display:flex;flex-direction:column;align-items:center;flex-shrink:0">';
      h += '<div style="width:12px;height:12px;border-radius:50%;background:'+dirColor+';border:3px solid '+dirBg+';box-shadow:0 0 0 2px #fff;margin-top:4px"></div>';
      if (!isLast) h += '<div style="flex:1;width:2px;background:#e2e8f0;margin-top:4px"></div>';
      h += '</div>';
      h += '<div class="card p3" style="flex:1;min-width:0;border:1px solid #e2e8f0;border-left:3px solid '+dirColor+';box-shadow:0 1px 2px rgba(15,23,42,.04)">';

      // ── Row 1: Metadata bar ──
      h += '<div class="flex jcs aic mb2">';
      h += '<div class="flex aic g2">';
      h += '<span style="font-weight:700;color:'+dirColor+';font-size:13px">'+dirIcon+' '+dirLabel+'</span>';
      h += '<span style="font-size:12px;color:#64748b">'+chIcon+' '+chLabel+'</span>';
      if (i.contact) h += '<span style="font-size:11px;font-weight:600;color:#4f46e5;background:#eef2ff;padding:1px 6px;border-radius:4px">'+E(i.contact)+'</span>';
      if (dFull) h += '<span style="font-size:11px;color:#64748b">'+E(dFull)+'</span>';
      if (i.reply_intent) {
        var riColors = {SAMPLE_ADDRESS:'#dc2626',SAMPLE:'#ea580c',QUOTE_REQUEST:'#16a34a',HOT_LEAD:'#dc2626',hot_lead:'#dc2626',positive:'#16a34a',interested:'#16a34a',neutral:'#6b7280',negative:'#dc2626',question:'#2563eb'};
        var riC = riColors[i.reply_intent] || '#6b7280';
        var riLabels = {SAMPLE_ADDRESS:'Shipping address',SAMPLE:'Sample interest',QUOTE_REQUEST:'Quote request',HOT_LEAD:'Hot signal',hot_lead:'Hot signal',positive:'Positive',interested:'Interested',neutral:'Neutral',negative:'Negative',question:'Question'};
        var riL = riLabels[i.reply_intent] || (i.reply_intent||'');
        h += '<span style="font-size:10px;padding:2px 8px;border-radius:10px;background:'+riC+';color:#fff;font-weight:600">'+riL+'</span>';
      }
      h += '</div>';
      h += '<div class="flex g2">';
      h += '<button class="btn btn-sm" style="background:#f1f5f9;color:#334155;font-size:10px;padding:2px 8px" data-int-del="'+i.id+'">🗑</button>';
      h += '</div></div>';

      // ── Row 2: Content body ──
      if (hasContent) {
        var contentHtml = (i.channel==='email' && i.direction==='inbound') ? formatEmailBody(i.content) : E(i.content);
        h += '<div id="'+contentId+'" class="fs13" style="color:#334155;line-height:1.7;'+(isLong?'max-height:120px;overflow-y:hidden;':'')+'">'+contentHtml+'</div>';
        if (isLong) {
          h += '<button class="btn btn-sm mt1" style="background:#fff;color:#4f46e5;font-size:11px;border:1px solid #d1d5db" data-int-toggle="'+contentId+'">' + 'Expand' + '</button>';
        }
      }
      if (i.subject) h += '<div style="font-size:11px;color:#64748b;margin-top:4px">📌 '+E(i.subject)+'</div>';
      try {
        var atts = JSON.parse(i.attachment_files || 'null');
        if (atts && atts.length) {
          h += '<div style="margin-top:6px;padding:6px 8px;background:#f8fafc;border:1px solid #e2e8f0;border-radius:6px">';
          h += '<div style="font-size:11px;color:#64748b;font-weight:600;margin-bottom:4px">Attachments ('+atts.length+')</div>';
          atts.forEach(function(a){
            var sz = a.size != null ? Math.max(1, Math.round(a.size/1024)) + ' KB' : '';
            h += '<div style="margin:2px 0"><a href="/attachments/'+encodeURIComponent((a.path||'').replace('attachments/',''))+'" download style="color:#4f46e5;text-decoration:none;font-weight:500;font-size:12px" target="_blank">📎 '+E(a.filename||'Attachment')+'</a> <span style="color:#64748b;font-size:11px">'+sz+'</span></div>';
          });
          h += '</div>';
        }
      } catch(e) {}

      // ── Row 3: Follow-up suggestion ──
      if (i.ai_suggested_timing) {
        h += '<div class="mt2 p2 flex aic g2" style="background:#f0fdf6;border:1px solid #bbf7d0;border-radius:6px">';
        h += '<span style="font-size:12px;color:#166534;font-weight:600">Suggested follow-up: '+E(i.ai_suggested_timing)+'</span>';
        h += '</div>';
      }

      // ── Row 4: AI analysis area ──
      var hasAI = i.ai_suggested_action || i.ai_draft_suggestion;
      // Always show AI area for every interaction
      h += '<div class="mt2" style="background:'+(i.direction==='inbound'?'#eef2ff':'#f9fafb')+';border-radius:6px;padding:8px 12px;font-size:12px;line-height:1.6">';
      if (i.ai_suggested_action) {
        h += '<div style="margin-bottom:4px"><b style="color:#4338ca">Analysis: </b>'+E(i.ai_suggested_action)+'</div>';
      }
      if (i.ai_draft_suggestion) {
        h += '<div style="margin-bottom:4px"><b style="color:#4f46e5">Suggested copy: </b>'+E(i.ai_draft_suggestion)+'</div>';
      }
      if (i.ai_suggested_timing) {
        h += '<div style="margin-bottom:4px;background:#f0fdf6;padding:4px 8px;border-radius:4px"><b style="color:#166534">Suggested follow-up: </b>'+E(i.ai_suggested_timing)+'</div>';
      }
      // No-reply hint only for outbound without reply
      if (!i.reply_intent && i.direction==='outbound') {
        h += '<div style="color:#64748b;font-size:11px;margin-bottom:4px">No customer reply yet; judged from sent content, no hot signal triggered</div>';
      }
      // Action buttons — always visible
      h += '<div class="flex g2 mt1" style="flex-wrap:wrap">';
      h += '<button class="btn btn-sm" style="background:#fff;color:#4f46e5;font-size:11px;border:1px solid #bfdbfe" data-int-follow="'+i.id+'">Analyze outreach progress</button>';
      h += '<button class="btn btn-sm" style="background:#fff;color:#7c3aed;font-size:11px;border:1px solid #ddd6fe" data-int-quote="'+i.id+'">Proposal-style quote</button>';
      if (hasContent) {
        h += '<button class="btn btn-sm" style="background:#fff;color:#059669;font-size:11px;border:1px solid #a7f3d0" data-int-reply="'+i.id+'" data-int-txt="'+E(i.content||'').replace(/"/g,'&quot;')+'" data-int-dir="'+i.direction+'">Reply suggestion</button>';
      }
      h += '</div>';
      h += '</div>';

      h += '</div>';
      h += '</div>';
    });
  }

  // ── AI Chat panel (always visible, full-width like DTSeq) ──
  h += '<div style="border:1px solid #c7d2fe;border-radius:8px;overflow:hidden;margin-top:16px">';
  h += '<div style="padding:10px 14px;background:#eef2ff;border-bottom:1px solid #c7d2fe;display:flex;justify-content:space-between;align-items:center"><span style="font-size:13px;font-weight:600;color:#4338ca">AI analysis - interactions</span><div style="display:flex;gap:4px"><button class="btn btn-sm" style="background:#6366f1;color:#fff;font-size:10px" id="intChatRefresh">Analyze again</button><button class="btn btn-sm" style="background:#e5e7eb;color:#334155;font-size:10px" id="intChatClear">Clear</button></div></div>';
  h += '<div id="intAIChatMsgs" style="max-height:420px;overflow-y:auto;padding:12px 16px;font-size:13px;min-height:80px;background:#fafbff;line-height:1.7">';
  if (_intChatSaved) {
    h += _intChatSaved;
  } else {
    h += '<div style="color:#64748b;text-align:center;padding:10px;font-size:11px">I have the profile, history and intelligence here. Tell me what to analyze and I will help with strategy and copy.</div>';
  }
  h += '</div>';
  h += '<div style="display:flex;padding:6px 10px;gap:6px;border-top:1px solid #e5e7eb;background:#fff">';
  h += '<input id="intAIChatInput" placeholder="Analyze this customer progress / write a follow-up email / create a proposal..." style="flex:1;font-size:12px;padding:6px 10px;border-radius:6px">';
  h += '<button class="btn btn-sm" style="background:#6366f1;white-space:nowrap" id="intAIChatSend">Send</button>';
  h += renderModelSelector('model_intel');
  h += '</div></div>';

  b.innerHTML = h;

  // ═══ CHANNEL TAG CLICK ═══
  b.querySelectorAll('#intChTags label').forEach(function(lbl){
    lbl.addEventListener('click', function(){
      b.querySelectorAll('#intChTags label').forEach(function(l){ l.style.background='#fff'; l.style.borderColor='#d1d5db'; l.style.color='#374151'; });
      lbl.style.background='#eff6ff'; lbl.style.borderColor='#2563eb'; lbl.style.color='#2563eb';
      var radio = lbl.querySelector('input');
      if (radio) radio.checked = true;
    });
  });

  // ═══ AUTO-DETECT FUNCTION ═══
  function detectInteraction(text) {
    var t = text.toLowerCase();
    var result = {channel:'other', direction:'inbound'};
    var chatPattern = t.match(/^\d{1,2}:\d{2}\s*$/m) || t.match(/\d{4}-\d{1,2}-\d{1,2}/);
    var hasEmailHeaders = t.indexOf('from:')!==-1 || t.indexOf('to:')!==-1 || t.indexOf('subject:')!==-1 || t.indexOf('sent:')!==-1 || t.indexOf('cc:')!==-1;
    if (t.indexOf('linkedin.com')!==-1 || t.indexOf('inmail')!==-1) result.channel='linkedin';
    else if (hasEmailHeaders) result.channel='email';
    else if (t.indexOf('wechat')!==-1 || t.indexOf('WeChat')!==-1) result.channel='wechat';
    else if (chatPattern && !hasEmailHeaders) result.channel='whatsapp';
    else result.channel='other';
    var outSignals = ['we specialize','our factory','we are a manufacturer','we mainly do','we can support','i will send','i have attached','we do oem','our service',"we don't provide","we're using",'from our factory','just wanted to',"i'm reaching out",'we met at',"i've already sent","i've reserved",'let me know if','please let me know'];
    var inSignals = ['good afternoon','good morning','do you produce','do you have','what types','what is','how much','price for','can you send','do you suggest',"i'm interested",'thank you for','thanks for','i understand','my question is','sadly','ok','strange','not in the mail','in spam too',"i'll check","i haven't checked",'we have purchased','we need','looking for','could you','do you offer','do you manufacture','how many','are they','does this','is the','is it','are there','i looked','i was told','at the moment'];
    var outScore = 0, inScore = 0;
    outSignals.forEach(function(p){ if(t.indexOf(p)!==-1) outScore++; });
    inSignals.forEach(function(p){ if(t.indexOf(p)!==-1) inScore++; });
    if (outScore > inScore) result.direction = 'outbound';
    else if (inScore > outScore) result.direction = 'inbound';
    else result.direction = 'inbound';
    return result;
  }

  // ═══ REAL-TIME DETECTION ═══
  var pasteArea = b.querySelector('#intPaste');
  var detectDiv = b.querySelector('#intDetect');
  var detectTimer = null;
  if (pasteArea) {
    pasteArea.addEventListener('input', function() {
      clearTimeout(detectTimer);
      var text = pasteArea.value.trim();
      if (text.length < 10) { detectDiv.innerHTML = ''; return; }
      detectTimer = setTimeout(function() {
        var d = detectInteraction(text);
        detectDiv.innerHTML = '<span style="color:#6366f1">⏳ Auto-detecting...</span>';
        setTimeout(function() {
          var chLabel = {email:'📧 Email',linkedin:'💼 LinkedIn',whatsapp:'📱 WhatsApp',phone:'📞 Phone',wechat:'💬 WeChat',meeting:'🤝 Meeting',note:'📋 Note',other:'📌 Other'}[d.channel]||d.channel;
          var dirLabel = d.direction==='inbound'?'From customer':'📤 Outbound';
          detectDiv.innerHTML = '<span style="color:#166534;font-weight:600">Detected: '+dirLabel+' · '+chLabel+'</span>';
        }, 300);
      }, 600);
    });
  }

  // ═══ GET SELECTED CHANNEL ═══
  function getSelectedChannel() {
    var radio = b.querySelector('input[name="intCh"]:checked');
    if (radio) return radio.value;
    return null;
  }

  // ═══ SAVE BUTTON ═══
  var saveBtn = b.querySelector('#intSaveBtn');
  if (saveBtn) saveBtn.onclick = async function() {
    var text = pasteArea.value.trim();
    if (!text) { T('Paste something first'); return; }
    var intDate = b.querySelector('#intDate').value;
    saveBtn.disabled = true;
    saveBtn.textContent = 'Saving...';

    var manualCh = getSelectedChannel();
    var detected = detectInteraction(text);
    var channel = manualCh || detected.channel;
    var chLabel = {email:'Email',linkedin:'LinkedIn',whatsapp:'WhatsApp',phone:'Phone',wechat:'WeChat',meeting:'Meeting',note:'Note',other:'Other'}[channel]||channel;
    var dirLabel = detected.direction==='inbound'?'From customer':'Outbound';

    try {
      var subjMatch = text.match(/^Subject:\s*(.+)$/im) || text.match(/^Re:\s*(.+)$/im);
      var body = {prospect_id: dp.id, direction: detected.direction, channel: channel, content: text, subject: subjMatch ? subjMatch[1].trim() : ''};
      if (intDate) body.interacted_at = intDate;
      await api('/interactions', {method:'POST', body: body});
      pasteArea.value = '';
      detectDiv.innerHTML = '<span style="color:#166534;font-weight:600">✅ Saved — '+dirLabel+' · '+chLabel+'</span>';
      try { var r = await api('/interactions/'+dp.id); drInts = Array.isArray(r) ? r : []; } catch(e) {}
      window._companyIntsKey = null;
      DTInt(b);
      T('Saved');
    } catch(e) {
      T('Save failed: '+(e.detail||e.message||String(e)), '#dc2626');
    }
    saveBtn.disabled = false;
    saveBtn.textContent = 'Save record';
  };

  // ═══ CHANNEL FILTER ═══
  var filterCh = b.querySelector('#intFilterCh');
  if (filterCh) filterCh.addEventListener('change', function(){
    window._intFilter = this.value;
    DTInt(b);
  });

  // ═══ CONTENT TOGGLE ═══
  b.querySelectorAll('[data-int-toggle]').forEach(function(btn){
    btn.addEventListener('click', function(){
      var targetId = btn.dataset.intToggle;
      var el = document.getElementById(targetId);
      if (!el) return;
      if (el.style.maxHeight) {
        el.style.maxHeight = '';
        btn.textContent = 'Collapse';
      } else {
        el.style.maxHeight = '120px';
        btn.textContent = 'Expand';
      }
    });
  });

  // ═══ DIRECTION FILTER ═══
  var filterDir = b.querySelector('#intFilterDir');
  if (filterDir) filterDir.addEventListener('change', function(){
    window._intDirFilter = this.value;
    DTInt(b);
  });

  // ═══ DELETE ═══
  b.querySelectorAll('[data-int-del]').forEach(function(btn) {
    btn.onclick = async function() {
      var iid = parseInt(btn.dataset.intDel);
      if (!confirm('Delete this interaction?')) return;
      try {
        await api('/interactions/'+iid, {method:'DELETE'});
        T('Deleted');
        try { var r = await api('/interactions/'+dp.id); drInts = Array.isArray(r) ? r : []; } catch(e) {}
        window._companyIntsKey = null;
        DTInt(b);
      } catch(e) { T('Delete failed', '#dc2626'); }
    };
  });

  // ═══ REPLY SUGGESTION ═══
  b.querySelectorAll('[data-int-reply]').forEach(function(btn) {
    btn.onclick = async function() {
      var txt = btn.dataset.intTxt;
      var dir = btn.dataset.intDir;
      var msgsDiv = b.querySelector('#intAIChatMsgs'); b.querySelector('#intAIChatMsgs').scrollIntoView({behavior:'smooth'});
      msgsDiv.innerHTML = '<div style="color:#64748b;font-size:11px;margin-bottom:4px">Based on'+(dir==='inbound'?'Customer':'Outbound')+' message:</div><div style="background:#f1f5f9;padding:8px 12px;border-radius:6px;font-size:11px;white-space:pre-wrap;max-height:80px;overflow-y:auto;margin-bottom:8px">'+E(txt).substring(0,500)+'</div><div style="color:#6366f1;font-size:11px">⏳ Generating...</div>';
      b.scrollIntoView({behavior:'smooth'});
      try {
        var intModel = getPanelModel('model_intel');
        var body = {prompt:'You are the export sales assistant of {{COMPANY}}. Judge this customer intent and write an English reply (plain and professional).\n\nMessage:\n'+txt.substring(0,2000)+'\n\nCustomer: '+E(dp.company)+' | '+E(dp.country)+' | Profile '+E(dp.profile_type), prospect_id: dp.id, voice: (window._intChatVoice||"human")};
        if (intModel !== 'auto') body.model_override = intModel;
        var res = await api('/ai/chat', {method:'POST', body: body});
        if (res && res.success) {
          msgsDiv.innerHTML = '<div style="color:#64748b;font-size:11px;margin-bottom:4px">Based on'+(dir==='inbound'?'Customer':'Outbound')+' message:</div><div style="background:#f1f5f9;padding:8px 12px;border-radius:6px;font-size:11px;white-space:pre-wrap;max-height:80px;overflow-y:auto;margin-bottom:8px">'+E(txt).substring(0,500)+'</div><div style="background:#eef2ff;padding:8px 12px;border-radius:6px;font-size:12px;line-height:1.6"><b style="color:#4338ca">AI:</b><br>'+cleanAiHtml(res.reply||res.result||'')+'</div>';
        }
      } catch(e) {}
    };
  });

  // ═══ points析开发节奏 ═══
  b.querySelectorAll('[data-int-follow]').forEach(function(btn) {
    btn.onclick = async function() {
      var iid = parseInt(btn.dataset.intFollow);
      btn.disabled = true; btn.textContent = 'Analyzing...';
      try {
        var intModel = getPanelModel('model_intel');
        var body = {prompt:'Analyze this customer outreach progress, assess the sales stage, and suggest the next step.Customer: '+E(dp.company)+' | '+E(dp.country)+' | Profile '+E(dp.profile_type), prospect_id: dp.id, voice: "human"};
        if (intModel !== 'auto') body.model_override = intModel;
        var res = await api('/ai/chat', {method:'POST', body: body});
        if (res && res.success) {
          var msgsDiv = b.querySelector('#intAIChatMsgs'); b.querySelector('#intAIChatMsgs').scrollIntoView({behavior:'smooth'});
          msgsDiv.innerHTML = '<div style="background:#eef2ff;padding:8px 12px;border-radius:6px;font-size:12px;line-height:1.6"><b style="color:#4338ca">Outreach progress analysis:</b><br>'+cleanAiHtml(res.reply||res.result||'')+'</div>';
          b.scrollIntoView({behavior:'smooth'});
        }
      } catch(e) { T('Analysis failed', '#dc2626'); }
      btn.disabled = false; btn.textContent = 'Analyze outreach progress';
    };
  });

  // ═══ 方案型报价 ═══
  b.querySelectorAll('[data-int-quote]').forEach(function(btn) {
    btn.onclick = async function() {
      var iid = parseInt(btn.dataset.intQuote);
      btn.disabled = true; btn.textContent = 'Generating...';
      try {
        var intModel = getPanelModel('model_intel');
        var body = {prompt:'You are the export sales team of {{COMPANY}}. Draft a proposal-style quote for this customer (not a formal quote; focus on their pain points, technical solution, price range and next step).Customer: '+E(dp.company)+' | '+E(dp.country)+' | Profile '+E(dp.profile_type)+' | Products: use knowledge base specs; do not invent parameters', prospect_id: dp.id, voice: "human"};
        if (intModel !== 'auto') body.model_override = intModel;
        var res = await api('/ai/chat', {method:'POST', body: body});
        if (res && res.success) {
          var msgsDiv = b.querySelector('#intAIChatMsgs'); b.querySelector('#intAIChatMsgs').scrollIntoView({behavior:'smooth'});
          msgsDiv.innerHTML = '<div style="background:#f5f3ff;padding:8px 12px;border-radius:6px;font-size:12px;line-height:1.6"><b style="color:#7c3aed">Proposal-style quote：</b><br>'+cleanAiHtml(res.reply||res.result||'')+'</div>';
          b.scrollIntoView({behavior:'smooth'});
        }
      } catch(e) { T('Generation failed', '#dc2626'); }
      btn.disabled = false; btn.textContent = 'Proposal-style quote';
    };
  });


  // ═══ AI CHAT REFRESH + CLEAR ═══
  var refBtn = b.querySelector('#intChatRefresh');
  var clrBtn = b.querySelector('#intChatClear');
  var mdRef = b.querySelector('#intAIChatMsgs');
  if (refBtn && mdRef) {
    refBtn.onclick = async function(){
      mdRef.innerHTML = '<div style="color:#6366f1;font-size:11px;text-align:center;padding:10px">⏳ Re-analyzing...</div>';
      try {
        var intModelR = getPanelModel('model_intel');
        var profileInfo = (dp.profile_summary||'') + ' ' + (dp.profile_type||'') + ' ' + (dp.pain_points||'') + ' ' + (dp.profile_refined||'');
        var interactionsSummary = (drInts||[]).map(function(i){return (i.direction==='inbound'?'Customer':'Outbound')+': '+ (i.content||'').substring(0,300);}).join('\n').substring(0,3000);
        var bodyR = {prompt:'Customer: '+E(dp.company)+' | '+E(dp.country)+' | Profile '+E(dp.profile_type)+'\nProfile: '+profileInfo.substring(0,800)+'\n\nInteraction history:\n'+interactionsSummary+'\n\nAnalyze: 1) current outreach pace and stage 2) recommended next action (email follow-up / proposal quote / channel switch / other) 3) a draft message if suitable. Reply in English with points 1,2,3.', prospect_id: dp.id, voice: 'human'};
        if (intModelR !== 'auto') bodyR.model_override = intModelR;
        var resR = await api('/ai/chat', {method:'POST', body: bodyR});
        if (resR && resR.success) {
          mdRef.innerHTML = '<div style="background:#eef2ff;padding:10px 14px;border-radius:6px;font-size:13px;line-height:1.7"><b style="color:#4338ca">AI analysis:</b><br><br>'+E(resR.reply||resR.result||'').replace(/\n/g,'<br>')+'</div>';
        }
      } catch(e) { mdRef.innerHTML = '<div style="color:#dc2626;text-align:center">Analysis failed: '+(e.detail||e.message||'')+'</div>'; }
    };
  }
  if (clrBtn && mdRef) {
    clrBtn.onclick = function(){
      _intChatSaved = '';
      mdRef.innerHTML = '<div style="color:#64748b;text-align:center;padding:10px;font-size:11px">I have the profile, history and intelligence here. Tell me what to analyze and I will help with strategy and copy.</div>';
    };
  }
  // ═══ AI CHAT FOLLOW-UP ═══
  var cs = b.querySelector('#intAIChatSend');
  var ci = b.querySelector('#intAIChatInput');
  if (cs && ci) {
    cs.onclick = async function() {
      var msg = ci.value.trim(); if (!msg) return;
      var md = b.querySelector('#intAIChatMsgs');
      md.innerHTML += '<div style="background:#f1f5f9;padding:6px 10px;border-radius:6px;font-size:11px;margin-top:6px"><b>You:</b> '+E(msg)+'</div>';
      ci.value = '';
      var ld = document.createElement('div'); ld.style.cssText='color:#6366f1;font-size:11px;margin-top:4px'; ld.textContent='⏳ ...'; md.appendChild(ld);
      try {
        var intModel2 = getPanelModel('model_intel');
        var body2 = {prompt:msg, prospect_id:dp.id, voice:(window._intChatVoice||'human')};
        if (intModel2 !== 'auto') body2.model_override = intModel2;
        var res2 = await api('/ai/chat', {method:'POST', body:body2});
        ld.remove();
        if (res2 && res2.success) { md.innerHTML += '<div style="background:#eef2ff;padding:8px 12px;border-radius:6px;font-size:12px;margin-top:6px;line-height:1.6"><b style="color:#4338ca">AI:</b><br>'+E(res2.reply||res2.result||'')+'</div>'; md.scrollTop=md.scrollHeight; }
      } catch(e) { ld.remove(); }
    };
    ci.addEventListener('keydown', function(e) { if (e.key==='Enter') { e.preventDefault(); cs.click(); } });
  }
}






// ── TAB: Sample Tracking ──
function DTSample(b){
  var h = '';
  var stLabels = {requested:'Address given / awaiting send',sent:'Sent',received:'Customer signed',testing:'Testing',feedback:'Feedback',trial_order:'Trial order',completed:'Done',dead:'Sample failed'};
  var stColors = {requested:'#f97316',sent:'#2563eb',received:'#8b5cf6',testing:'#ec4899',feedback:'#16a34a',trial_order:'#059669',completed:'#64748b',dead:'#dc2626'};
  var stIcons = {requested:'📦',sent:'✈️',received:'📬',testing:'🔬',feedback:'💬',trial_order:'📋',completed:'✅',dead:'❌'};

  // Add new event form
  h += '<div class="card p3 mb3" style="background:#f8fafc;border:1px solid #e2e8f0">';
  h += '<p class="fwm fs13 mb2">+ Add sample event</p>';
  h += '<div class="flex g2 mb2" style="flex-wrap:wrap">';
  h += '<select id="smpStage" style="font-size:12px;padding:5px 10px;border:1px solid #d1d5db;border-radius:6px">';
  Object.keys(stLabels).forEach(function(k){ h += '<option value="'+k+'">'+stIcons[k]+' '+stLabels[k]+'</option>'; });
  h += '</select>';
  h += '<input id="smpDate" type="date" style="font-size:12px;padding:5px 8px;border:1px solid #d1d5db;border-radius:6px;width:130px" value="'+new Date().toISOString().substring(0,10)+'">';
  h += '<button class="btn btn-sm" style="background:#34d399;color:#fff;font-weight:600" id="smpAdd">Add</button>';
  h += '</div>';
  h += '<textarea id="smpNote" placeholder="Note (test purpose, quantity, or draft the notification)" style="width:100%;font-size:12px;padding:8px 10px;border:1px solid #d1d5db;border-radius:6px;margin-top:6px;min-height:40px;resize:vertical" rows="2"></textarea>';
  // Contextual fields — show different inputs based on stage
  h += '<div id="smpStageFields" style="display:none" class="mt1">';
  // sent: carrier + tracking + ETA
  h += '<div id="smpFieldsSent" style="display:none" class="flex g2">';
  h += '<select id="smpCarrier" style="font-size:11px;padding:3px 6px;border:1px solid #d1d5db;border-radius:4px"><option value="">Courier</option><option value="DHL">DHL</option><option value="FedEx">FedEx</option><option value="UPS">UPS</option><option value="TNT">TNT</option><option value="SF">SF Express</option><option value="other">Other</option></select>';
  h += '<input id="smpTracking" placeholder="Tracking number" style="font-size:11px;padding:3px 8px;border:1px solid #d1d5db;border-radius:4px;width:180px">';
  h += '<input id="smpArrival" type="date" placeholder="Expected arrival" style="font-size:11px;padding:3px 6px;border:1px solid #d1d5db;border-radius:4px;width:130px">';
  h += '</div>';
  // received: signed_date
  h += '<div id="smpFieldsReceived" style="display:none" class="flex g2">';
  h += '<input id="smpSignedDate" type="date" placeholder="Signed date" style="font-size:11px;padding:3px 8px;border:1px solid #d1d5db;border-radius:4px;width:130px">';
  h += '</div>';
  // testing: test_purpose
  h += '<div id="smpFieldsTesting" style="display:none" class="flex g2">';
  h += '<input id="smpTestPurpose" placeholder="Test purpose / what they are testing" style="font-size:11px;padding:3px 8px;border:1px solid #d1d5db;border-radius:4px;width:320px">';
  h += '</div>';
  h += '</div>';
  h += '</div>';

  // Stage filter pills
  h += '<div class="flex g2 mb3" style="flex-wrap:wrap; align-items:center">';
  h += '<button class="btn btn-sm smpFilter active" data-smp-filter="all" style="background:#6366f1;color:#fff;font-size:11px;padding:3px 10px;border-radius:12px">All</button>';
  Object.keys(stLabels).forEach(function(k){
    h += '<button class="btn btn-sm smpFilter" data-smp-filter="'+k+'" style="background:#f1f5f9;color:#334155;font-size:11px;padding:3px 10px;border-radius:12px">'+stIcons[k]+' '+stLabels[k]+'</button>';
  });
  h += '<span style="flex:1"></span>';
  h += '<button class="btn btn-sm" style="background:#6366f1;color:#fff;font-size:11px;padding:3px 10px;border-radius:12px;font-weight:600" id="smpRefreshTracking">Refresh logistics</button>';
  h += '</div>';

  // Event list
  if (drSample && drSample.length) {
    var filter = window._smpFilter || 'all';
    var events = drSample.slice().sort(function(a,b){ return (a.event_date||a.created_at||'') < (b.event_date||b.created_at||'') ? 1 : -1; });
    var filtered = filter==='all' ? events : events.filter(function(e){ return e.stage===filter; });

    if (!filtered.length) {
      h += '<div class="card tc" style="color:#64748b;padding:20px;font-size:13px">No records at this stage</div>';
    }

    filtered.forEach(function(ev, idx){
      var stC = stColors[ev.stage] || '#64748b';
      var stI = stIcons[ev.stage] || '📌';
      var stL = stLabels[ev.stage] || ev.stage;
      var d = ev.event_date || ev.created_at || '';
      var dShort = d ? String(d).substring(0,10) : '';

      h += '<div class="card p3 mb2" style="border-left:4px solid '+stC+'">';
      // Header bar
      h += '<div class="flex jcs aic mb2">';
      h += '<div class="flex aic g2">';
      h += '<span style="font-weight:700;color:'+stC+';font-size:13px">'+stI+' '+stL+'</span>';
      if (dShort) h += '<span style="font-size:11px;color:#64748b">'+E(dShort)+'</span>';
      // Notification status badge — show channel icon
      if (ev.notified_at) {
        var chIconMap = {email:'📧', linkedin:'💼', whatsapp:'💬', wechat:'🟢', phone:'📞'};
        var chLabelMap = {email:'Email notified', linkedin:'LinkedIn notified', whatsapp:'WhatsApp notified', wechat:'WeChat notified', phone:'PhoneNotified'};
        var chIcon = chIconMap[ev.notified_channel] || '✅';
        var chLabel = chLabelMap[ev.notified_channel] || 'Notified';
        h += '<span style="font-size:10px;background:#dcfce7;color:#166534;padding:1px 6px;border-radius:8px;font-weight:600;margin-left:4px">'+chIcon+' '+chLabel+'</span>';
      } else {
        h += '<span style="font-size:10px;background:#fffced;color:#92400e;padding:1px 6px;border-radius:8px;font-weight:600;margin-left:4px" title="Customer not notified at this stage">To notify</span>';
      }
      h += '</div>';
      h += '<div class="flex g1">';
      h += '<button class="btn btn-sm" style="background:#f1f5f9;color:#334155;font-size:10px;padding:2px 6px" data-smp-edit="'+ev.id+'">✏️</button>';
      h += '<button class="btn btn-sm" style="background:#fef5f5;color:#dc2626;font-size:10px;padding:2px 6px" data-smp-del="'+ev.id+'">🗑</button>';
      h += '</div></div>';

      // Content
      if (ev.tracking_number) {
        h += '<div style="font-size:12px;color:#334155;margin-bottom:4px">📦 '+E(ev.carrier||'Courier')+' '+E(ev.tracking_number);
        if (ev.tracking_url) h += ' <a href="'+E(ev.tracking_url)+'" target="_blank" style="color:#4f46e5;font-size:11px">Track shipment</a>';
        h += '</div>';
      }
      if (ev.expected_arrival) h += '<div style="font-size:11px;color:#64748b;margin-bottom:4px">📅 Expected arrival: '+E(ev.expected_arrival)+'</div>';
      if (ev.test_purpose) h += '<div style="font-size:11px;color:#64748b;margin-bottom:4px">Test purpose: '+E(ev.test_purpose)+'</div>';
      if (ev.note) h += '<div style="font-size:12px;color:#334155;line-height:1.6;white-space:pre-wrap">'+E(ev.note)+'</div>';
      if (ev.ai_followup_prompt) {
        h += '<div class="mt2 p2" style="background:#eef2ff;border-radius:4px;font-size:11px;line-height:1.6;color:#3730a3">'+E(ev.ai_followup_prompt)+'</div>';
      }
      // Notification actions per event
      var stKey = ev.stage || '';
      var notifyLabels = {
        sent: 'Notify customer: sample sent',
        received: 'Confirm customer signed',
        testing: 'Check testing progress',
        feedback: 'Respond to customer feedback',
        trial_order: 'Push trial order',
        completed: 'Follow-up care',
        requested: 'Confirm shipping details'
      };
      var notifyLabel = notifyLabels[stKey] || 'Notify customer';
      var customerEmail = dp.email || dp.dm_email || '';
      var customerLinkedIn = dp.linkedin || '';
      var customerPhone = dp.phone || '';
      var customerWeChat = dp.wechat || dp.note_wechat || '';
      h += '<div class="flex g2 mt2" style="flex-wrap:wrap;padding-top:6px;border-top:1px solid #f1f5f9">';
      // Auto-generated AI draft badge
      if (ev.followup_draft_id) {
        h += '<button class="btn btn-sm" style="background:#fffced;color:#92400e;font-size:10px;padding:3px 8px;font-weight:600;border:1px solid #f59e0b" data-smp-open-draft="'+ev.followup_draft_id+'" title="AI auto-generated the email draft">📧 AI draft</button>';
      }
      h += '<span style="font-size:10px;color:#64748b;line-height:26px">Notify customer:</span>';
      if (customerEmail) {
        h += '<button class="btn btn-sm" style="background:#6366f1;color:#fff;font-size:10px;padding:3px 8px" data-smp-notify-email="'+ev.id+'">📧 Email</button>';
      } else {
        h += '<button class="btn btn-sm" style="background:#e5e7eb;color:#64748b;font-size:10px;padding:3px 8px" disabled title="No email set">No email</button>';
      }
      if (customerLinkedIn) {
        h += '<button class="btn btn-sm" style="background:#0A66C2;color:#fff;font-size:10px;padding:3px 8px" data-smp-notify-linkedin="'+ev.id+'">💼 LinkedIn</button>';
      } else {
        h += '<button class="btn btn-sm" style="background:#e5e7eb;color:#64748b;font-size:10px;padding:3px 8px" disabled title="No LinkedIn set">No LinkedIn</button>';
      }
      if (customerPhone) {
        h += '<button class="btn btn-sm" style="background:#25D366;color:#fff;font-size:10px;padding:3px 8px" data-smp-notify-whatsapp="'+ev.id+'">💬 WhatsApp</button>';
      } else {
        h += '<button class="btn btn-sm" style="background:#e5e7eb;color:#64748b;font-size:10px;padding:3px 8px" disabled title="No phone set">No WhatsApp</button>';
      }
      if (customerWeChat) {
        h += '<button class="btn btn-sm" style="background:#07C160;color:#fff;font-size:10px;padding:3px 8px" data-smp-notify-wechat="'+ev.id+'">🟢 WeChat</button>';
      } else {
        h += '<button class="btn btn-sm" style="background:#e5e7eb;color:#64748b;font-size:10px;padding:3px 8px" disabled title="No WeChat set">No WeChat</button>';
      }
      // Quick stage advance button — show next logical stage
      var nextStageMap = {requested:'sent', sent:'received', received:'testing', testing:'feedback', feedback:'trial_order', trial_order:'completed'};
      var nextStage = nextStageMap[stKey];
      if (nextStage) {
        var nextLabel = stLabels[nextStage] || nextStage;
        var nextIcon = stIcons[nextStage] || '▶️';
        h += '<div style="margin-top:6px;padding-top:6px;border-top:1px solid #f1f5f9">';
        h += '<button class="btn btn-sm" style="background:'+(stColors[nextStage]||'#2563eb')+';color:#fff;font-size:11px;padding:4px 12px;font-weight:600" data-smp-advance="'+ev.id+'" data-next="'+nextStage+'">'+nextIcon+' Advance to: '+nextLabel+'</button>';
        if (stKey === 'sent') {
          h += '<button class="btn btn-sm" style="background:#8b5cf6;color:#fff;font-size:11px;padding:4px 12px;margin-left:4px;font-weight:600" data-smp-advance="'+ev.id+'" data-next="received">📬 Customer signed (delivered)</button>';
        }
        h += '</div>';
      }
      h += '</div>';
      h += '</div>';
    });
  } else {
    h += '<div class="card tc" style="color:#64748b;padding:30px;font-size:13px">No sample records<br><span style="font-size:11px">AddStep  sample event to start tracking</span></div>';
  }

  b.innerHTML = h;

  // Stage select shows stage-specific fields
  var stSel = b.querySelector('#smpStage');
  var stageFields = b.querySelector('#smpStageFields');
  if (stSel && stageFields) {
    var updateStageFields = function(){
      var v = stSel.value;
      stageFields.style.display = (v==='sent'||v==='received'||v==='testing') ? 'block' : 'none';
      var divs = stageFields.querySelectorAll('div[id^="smpFields"]');
      divs.forEach(function(d){ d.style.display = 'none'; });
      var target = stageFields.querySelector('#smpFields' + v.charAt(0).toUpperCase() + v.slice(1));
      if (target) target.style.display = 'flex';
    };
    stSel.addEventListener('change', updateStageFields);
    // Run on init — if stage is already 'sent' etc from previous selection
    updateStageFields();
  }

  // Filter pills
  b.querySelectorAll('.smpFilter').forEach(function(btn){
    btn.addEventListener('click', function(){
      window._smpFilter = btn.dataset.smpFilter;
      b.querySelectorAll('.smpFilter').forEach(function(x){ x.style.background='#f3f4f6'; x.style.color='#374151'; });
      btn.style.background='#2563eb'; btn.style.color='#fff';
      DTSample(b);
    });
  });

  // Refresh logistics tracking
  var smpRefreshBtn = b.querySelector('#smpRefreshTracking');
  if (smpRefreshBtn) {
    smpRefreshBtn.addEventListener('click', async function(){
      smpRefreshBtn.disabled = true;
      smpRefreshBtn.textContent = 'Checking...';
      try {
        var ckR = await api('/sample-tracking/check-tracking', {method:'POST'});
        if (ckR.updated > 0) {
          T('Logistics updated: ' + ckR.checked + ' tracking numbers, ' + ckR.updated + ' changed');
          try { var r = await api('/sample-tracking/'+dp.id); drSample = Array.isArray(r) ? r : []; } catch(e) {}
          DTSample(b);
        } else {
          T('Checked ' + ckR.checked + ' tracking numbers - no changes');
        }
      } catch(e) {
        T('Logistics check failed: '+(e.detail||e.message||''), '#dc2626');
      }
      smpRefreshBtn.disabled = false;
      smpRefreshBtn.textContent = 'Refresh logistics';
    });
  }

  // Add event
  try {
    var smpAddBtn = b.querySelector('#smpAdd');
    if (smpAddBtn) {
      smpAddBtn.addEventListener('click', async function(e){
        e.preventDefault();
        var stageEl = b.querySelector('#smpStage');
        var noteEl = b.querySelector('#smpNote');
        var dateEl = b.querySelector('#smpDate');
        if (!stageEl) { T('Page element lost - refresh and retry', '#dc2626'); return; }
        var stage = stageEl.value;
        var note = noteEl ? noteEl.value.trim() : '';
        var date = dateEl ? dateEl.value : '';
        if (!stage) { T('Select a stage'); return; }
        var body = {stage:stage};
        if (note) body.note = note;
        if (date) body.event_date = date;
        if (stage === 'sent') {
          var carrierEl = b.querySelector('#smpCarrier');
          var trackingEl = b.querySelector('#smpTracking');
          var arrivalEl = b.querySelector('#smpArrival');
          if (carrierEl && carrierEl.value) body.carrier = carrierEl.value;
          if (trackingEl && trackingEl.value.trim()) body.tracking_number = trackingEl.value.trim();
          if (arrivalEl && arrivalEl.value) body.expected_arrival = arrivalEl.value;
        }
        if (stage === 'received') {
          var signedEl = b.querySelector('#smpSignedDate');
          if (signedEl && signedEl.value) body.signed_date = signedEl.value;
        }
        if (stage === 'testing') {
          var purposeEl = b.querySelector('#smpTestPurpose');
          if (purposeEl && purposeEl.value.trim()) body.test_purpose = purposeEl.value.trim();
        }
        try {
          await api('/sample-tracking/'+dp.id, {method:'POST', body:body});
          T('Added');
          if (noteEl) noteEl.value = '';
          var trkEl2 = b.querySelector('#smpTracking');
          if (trkEl2) trkEl2.value = '';
          // Reset filter to 'all' so the newly added event is visible
          window._smpFilter = 'all';
          try { var r = await api('/sample-tracking/'+dp.id); drSample = Array.isArray(r) ? r : []; } catch(e) {}
          try { var pr = await api('/prospects/'+dp.id); dp = pr; ed = Object.assign({}, dp); } catch(e) {}
          DTSample(b);
        } catch(e) { T('Add failed: '+(e.detail||e.message||''), '#dc2626'); }
      });
    }
  } catch(e) { console.error('[DTSample] smpAdd bind error:', e); }

  // Delete event
  b.querySelectorAll('[data-smp-del]').forEach(function(btn){
    btn.onclick = async function(){
      var eid = parseInt(btn.dataset.smpDel);
      if (!confirm('Delete this sample record?')) return;
      try {
        await api('/sample-tracking/'+dp.id+'/'+eid, {method:'DELETE'});
        T('Deleted');
        try { var r = await api('/sample-tracking/'+dp.id); drSample = Array.isArray(r) ? r : []; } catch(e) {}
        DTSample(b);
      } catch(e) { T('Delete failed', '#dc2626'); }
    };
  });

  // Quick stage advance
  b.querySelectorAll('[data-smp-advance]').forEach(function(btn){
    btn.onclick = async function(){
      console.log('[DTSample] advance clicked, eid:', btn.dataset.smpAdvance, 'next:', btn.dataset.next);
      var eid = parseInt(btn.dataset.smpAdvance);
      var nextStage = btn.dataset.next;
      btn.disabled = true; btn.textContent = 'Advancing...';
      try {
        await api('/sample-tracking/'+dp.id+'/'+eid, {method:'PUT', body:{stage:nextStage}});
        T('Advanced to: ' + nextStage);
        try { var r = await api('/sample-tracking/'+dp.id); drSample = Array.isArray(r) ? r : []; } catch(e) {}
        try { var pr = await api('/prospects/'+dp.id); dp = pr; ed = Object.assign({}, dp); } catch(e) {}
        DTSample(b);
        // Auto-open the draft if one was generated
        var advanced = drSample.find(function(e){ return e.id === eid; });
        if (advanced && advanced.followup_draft_id) {
          setTimeout(function(){
            var draftBtn = b.querySelector('[data-smp-open-draft="'+advanced.followup_draft_id+'"]');
            if (draftBtn) draftBtn.click();
          }, 300);
        }
      } catch(e) { T('Advance failed: '+(e.detail||e.message||''), '#dc2626'); btn.disabled = false; }
    };
  });

  // Edit event (inline stage change)
  b.querySelectorAll('[data-smp-edit]').forEach(function(btn){
    btn.onclick = async function(){
      var eid = parseInt(btn.dataset.smpEdit);
      var newStage = prompt('ReviseStage (requested/sent/received/testing/feedback/trial_order/completed/dead):');
      if (!newStage) return;
      try {
        await api('/sample-tracking/'+dp.id+'/'+eid, {method:'PUT', body:{stage:newStage}});
        T('Updated');
        try { var r = await api('/sample-tracking/'+dp.id); drSample = Array.isArray(r) ? r : []; } catch(e) {}
        DTSample(b);
      } catch(e) { T('Update failed: '+(e.detail||e.message||e.status||''), '#dc2626'); }
    };
  });

  // Open auto-generated AI draft
  b.querySelectorAll('[data-smp-open-draft]').forEach(function(btn){
    btn.onclick = async function(){
      var draftId = parseInt(btn.dataset.smpOpenDraft);
      T('Loading draft...');
      try {
        var eq = await api('/email/queue?prospect_id='+dp.id);
        var draft = Array.isArray(eq) ? eq.find(function(e){ return e.id === draftId; }) : null;
        if (!draft) { T('Draft not found; it may have been deleted', '#dc2626'); return; }
        
        var oldM = document.getElementById('smpNotifyMsk'); if(oldM) oldM.remove();
        var oldC = document.getElementById('smpNotifyWrap'); if(oldC) oldC.remove();
        var h = '<div class="mask" style="z-index:80" id="smpNotifyMsk"></div>';
        h += '<div id="smpNotifyWrap" class="card" style="position:fixed;top:5%;left:50%;transform:translateX(-50%);width:600px;max-width:92vw;max-height:85vh;overflow-y:auto;z-index:90;padding:24px;background:#fff">';
        h += '<div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:12px"><b style="font-size:15px">AI auto-generated email draft</b><button style="border:none;background:none;font-size:22px;cursor:pointer;color:#64748b" id="smpNotifyClose">&times;</button></div>';
        h += '<div style="font-size:11px;color:#64748b;margin-bottom:8px">Recipient: <b>'+E(draft.to_email||'')+'</b> | Status: '+E(draft.status||'draft')+'</div>';
        h += '<label style="font-size:11px;color:#64748b;display:block;margin-bottom:2px">Subject</label><input id="smpNotifySubj" value="'+E(draft.subject||'').replace(/"/g,'&quot;')+'" style="margin-bottom:8px;font-size:13px">';
        h += '<label style="font-size:11px;color:#64748b;display:block;margin-bottom:2px">Body</label><textarea id="smpNotifyBody" rows="12" style="font-size:13px;line-height:1.6;margin-bottom:8px">'+E(draft.body||'')+'</textarea>';
        h += '<div style="flex:1;display:flex;gap:6px;align-items:center;flex-wrap:wrap">';
        h += renderModelSelector('model_sample','Model');
        h += renderSenderSelector('email_sender','Sender', dp && dp.sender_key);
        h += '<button class="btn" style="background:#f87171;color:#fff;font-weight:600" id="smpNotifySend">Send now</button>';
        h += '<button class="btn btn-sm" style="background:#6366f1;color:#fff" id="smpNotifySave">Update draft</button>';
        h += '<button class="btn btn-sm" style="background:#6366f1" id="smpNotifyPolish">AI polish</button>';
        h += '<button class="btn btn-sm" style="background:#f59e0b" id="smpNotifyCopy">Copy body</button>';
        h += '</div><div id="smpNotifyPolishHint" style="margin-top:6px"><input id="smpPolishInst" placeholder="Tell AI how to revise" style="font-size:12px;margin-bottom:4px"><button class="btn btn-sm" style="background:#eab308;color:#fff" id="smpPolishGo">Revise</button></div>';
        h += '</div></div>';
        document.body.insertAdjacentHTML('beforeend', h);
        
        var msk = document.getElementById('smpNotifyMsk');
        var wrap = document.getElementById('smpNotifyWrap');
        var closeFn = function(){ msk.remove(); wrap.remove(); };
        msk.onclick = closeFn;
        document.getElementById('smpNotifyClose').onclick = closeFn;
        
        document.getElementById('smpNotifyCopy').onclick = function(){
          navigator.clipboard.writeText(document.getElementById('smpNotifyBody').value);
          T('CopiedBody');
        };
        
        document.getElementById('smpNotifySend').onclick = async function(){
          var subj = document.getElementById('smpNotifySubj').value;
          var body = document.getElementById('smpNotifyBody').value;
          if (!body.trim()) { T('Body cannot be empty'); return; }
          var btn = document.getElementById('smpNotifySend');
          btn.disabled = true; btn.textContent = 'Sending...';
          try {
            // Update draft body first
            await api('/email/queue/'+draftId, {method:'PUT', body:{subject:subj, body:body, status:'pending', sender_key:getSenderKey('email_sender')}});
            // Send immediately
            await api('/email/send-one/'+draftId, {method:'POST'});
            T('Email sent');
            closeFn();
          } catch(e) { T('Send failed', '#dc2626'); btn.disabled = false; btn.textContent = 'Send now'; }
        };
        
        document.getElementById('smpNotifySave').onclick = async function(){
          var subj = document.getElementById('smpNotifySubj').value;
          var body = document.getElementById('smpNotifyBody').value;
          if (!body.trim()) { T('Body cannot be empty'); return; }
          try {
            await api('/email/queue/'+draftId, {method:'PUT', body:{subject:subj, body:body, sender_key:getSenderKey('email_sender')}});
            T('Draft updated');
            closeFn();
          } catch(e) {
            if (e.status === 400 || e.status === 404) {
              try {
                await authFetch('/api/email/queue',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({prospect_id:dp.id,to_email:(dp.email||dp.dm_email||''),subject:subj,body:body,status:'draft',sender_key:getSenderKey('email_sender')})});
                showDraftHint('New email draft created');
                closeFn();
              } catch(e2) { T('Update failed: '+(e2.detail||e2.message||''), '#dc2626'); }
            } else { T('Update failed: '+(e.detail||e.message||e.status||''), '#dc2626'); }
          }
        };
        
        document.getElementById('smpNotifyPolish').onclick = function(){
          document.getElementById('smpNotifyPolishHint').style.display = 'block';
        };
        document.getElementById('smpPolishGo').onclick = async function(){
          var inst = document.getElementById('smpPolishInst').value;
          if (!inst.trim()) { T('Enter polish instructions'); return; }
          T('AI is polishing...');
          try {
            var revR = await api('/ai/revise-message/'+dp.id, {method:'POST', body:{current_subject:document.getElementById('smpNotifySubj').value, current_body:document.getElementById('smpNotifyBody').value, instruction:inst, message_type:'cold_email', tone:'human'}});
            if (revR.success && revR.result) {
              if (revR.result.body) document.getElementById('smpNotifyBody').value = revR.result.body;
              if (revR.result.subject) document.getElementById('smpNotifySubj').value = revR.result.subject;
              document.getElementById('smpPolishInst').value = '';
              T('Polished');
            } else { T('Polish failed', '#dc2626'); }
          } catch(e) { T('Polish failed', '#dc2626'); }
        };
        document.getElementById('smpNotifyPolishHint').style.display = 'none';
        T('Draft loaded');
      } catch(e) { T('Load draft failed: '+(e.detail||e.message||''), '#dc2626'); }
    };
  });

  // Email notification — AI generate + save draft
  b.querySelectorAll('[data-smp-notify-email]').forEach(function(btn){
    btn.onclick = async function(){
      var eid = parseInt(btn.dataset.smpNotifyEmail);
      var ev = drSample.find(function(e){ return e.id === eid; });
      if (!ev) return;
      var stage = ev.stage || '';
      var stageLabels = {requested:'Sample pending',sent:'Sample sent',received:'Customer signed',testing:'Testing',feedback:'Feedback',trial_order:'Trial order',completed:'Done',dead:'Sample failed'};
      var stageLabel = stageLabels[stage] || stage;

      // Build context for AI
      var ctx = 'Customer: '+E(dp.company)+' | '+E(dp.country)+' | Profile '+E(dp.profile_type||'')+'\n';
      ctx += 'Sample stage: '+stageLabel+'\n';
      if (ev.note) ctx += 'Note: '+E(ev.note)+'\n';
      if (ev.tracking_number) ctx += 'Courier: '+E(ev.carrier||'')+' '+E(ev.tracking_number)+'\n';
      if (ev.tracking_url) ctx += 'Tracking link: '+E(ev.tracking_url)+'\n';
      if (ev.expected_arrival) ctx += 'Expected arrival: '+E(ev.expected_arrival)+'\n';
      if (ev.test_purpose) ctx += 'Test purpose: '+E(ev.test_purpose)+'\n';
      if (ev.ai_followup_prompt) ctx += 'AI follow-up suggestion: '+E(ev.ai_followup_prompt)+'\n';

      T('AI is generating the email...');
      try {
        console.log('[SMP-NOTIFY-EMAIL] Starting for event', eid, 'stage', stage);
        var genBody = {
          message_type: 'cold_email',
          tone: 'human',
          additional_context: 'SAMPLE NOTIFICATION — client sample in stage: '+stageLabel+'\n'+ctx+'\nGenerate a professional email in Chinese notifying the client about the sample status. Be warm and helpful, not pushy. Include the tracking/arrival details if available.'
        };
        var genModel = getPanelModel('model_sample');
        if (genModel !== 'auto') genBody.model_override = genModel;
        var genR = await api('/ai/generate-message/'+dp.id, {method:'POST', body: genBody});
        if (!genR.success) { T('AIGeneration failed', '#dc2626'); return; }

        var subj = genR.result.subject || 'Sample update — '+E(dp.company);
        var body = genR.result.body || genR.result.content || '';

        // Show compose panel
        var oldM = document.getElementById('smpNotifyMsk'); if(oldM) oldM.remove();
        var oldC = document.getElementById('smpNotifyWrap'); if(oldC) oldC.remove();
        var h = '<div class="mask" style="z-index:80" id="smpNotifyMsk"></div>';
        h += '<div id="smpNotifyWrap" class="card" style="position:fixed;top:5%;left:50%;transform:translateX(-50%);width:600px;max-width:92vw;max-height:85vh;overflow-y:auto;z-index:90;padding:24px;background:#fff">';
        h += '<div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:12px"><b style="font-size:15px">Email notification - '+E(stageLabel)+'</b><button style="border:none;background:none;font-size:22px;cursor:pointer;color:#64748b" id="smpNotifyClose">&times;</button></div>';
        var toEmail = dp.email || dp.dm_email || '';
        h += '<div style="font-size:11px;color:#64748b;margin-bottom:8px">Recipient: <b>'+E(toEmail)+'</b></div>';
        h += '<label style="font-size:11px;color:#64748b;display:block;margin-bottom:2px">Subject</label><input id="smpNotifySubj" value="'+E(subj).replace(/"/g,'&quot;')+'" style="margin-bottom:8px;font-size:13px">';
        h += '<label style="font-size:11px;color:#64748b;display:block;margin-bottom:2px">Body</label><textarea id="smpNotifyBody" rows="10" style="font-size:13px;line-height:1.6;margin-bottom:8px">'+E(body)+'</textarea>';
        h += '<div style="flex:1;display:flex;gap:6px;align-items:center;flex-wrap:wrap">';
        h += renderModelSelector('model_sample','Model');
        h += renderSenderSelector('email_sender','Sender', dp && dp.sender_key);
        h += '<button class="btn" style="background:#f87171;color:#fff;font-weight:600" id="smpNotifySend">Send now</button>';
        h += '<button class="btn" style="background:#34d399" id="smpNotifySave">Save to drafts</button>';
        h += '<button class="btn btn-sm" style="background:#6366f1" id="smpNotifyPolish">AI polish</button>';
        h += '<button class="btn btn-sm" style="background:#f59e0b" id="smpNotifyCopy">Copy body</button>';
        h += '</div><div id="smpNotifyPolishHint" style="margin-top:6px"><input id="smpPolishInst" placeholder="Tell AI how to revise (e.g. warmer, add a testing nudge, write in German)" style="font-size:12px;margin-bottom:4px"><button class="btn btn-sm" style="background:#eab308;color:#fff" id="smpPolishGo">Revise</button></div>';
        h += '</div></div>';
        document.body.insertAdjacentHTML('beforeend', h);

        var msk = document.getElementById('smpNotifyMsk');
        var wrap = document.getElementById('smpNotifyWrap');
        var closeFn = function(){ msk.remove(); wrap.remove(); };
        msk.onclick = closeFn;
        document.getElementById('smpNotifyClose').onclick = closeFn;

        document.getElementById('smpNotifyCopy').onclick = function(){
          navigator.clipboard.writeText(document.getElementById('smpNotifyBody').value);
          T('CopiedBody');
        };

        // Send now — save as pending and send immediately
        document.getElementById('smpNotifySend').onclick = async function(){
          var s = document.getElementById('smpNotifySubj').value;
          var bd = document.getElementById('smpNotifyBody').value;
          if (!bd.trim()) { T('Body cannot be empty'); return; }
          var btn = document.getElementById('smpNotifySend');
          btn.disabled = true; btn.textContent = 'Sending...';
          try {
            // Step 1: create queue entry as pending
            var qr = await authFetch('/api/email/queue',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({prospect_id:dp.id,to_email:(dp.email||dp.dm_email||''),subject:s,body:bd,status:'pending',sender_key:getSenderKey('email_sender')})});
            var qd = await qr.json();
            if (!qr.ok) { T('Failed to create email', '#dc2626'); btn.disabled = false; btn.textContent = 'Send now'; return; }
            var qid = qd.id;
            // Step 2: send immediately
            await api('/email/send-one/'+qid, {method:'POST'});
            // Mark as notified
            try { await api('/sample-tracking/'+dp.id+'/'+eid, {method:'PUT', body:{notified_at: new Date().toISOString().substring(0,16).replace('T',' '), notified_channel: 'email'}}); } catch(e) {}
            // Also save as interaction
            try { await api('/interactions', {method:'POST', body:{prospect_id:dp.id, channel:'email', direction:'outbound', content:bd, interacted_at:new Date().toISOString().substring(0,10)}}); } catch(e) {}
            T('Email sent - marked notified');
            try { var r = await api('/sample-tracking/'+dp.id); drSample = Array.isArray(r) ? r : []; } catch(e) {}
            try { var r2 = await api('/interactions/'+dp.id); drInts = Array.isArray(r2) ? r2 : []; } catch(e) {}
            DTSample(document.getElementById('dbody') || b);
            closeFn();
          } catch(e) { T('SendFailed: '+(e.detail||e.message||''), '#dc2626'); btn.disabled = false; btn.textContent = 'Send now'; }
        };

        document.getElementById('smpNotifySave').onclick = async function(){
          var s = document.getElementById('smpNotifySubj').value;
          var bd = document.getElementById('smpNotifyBody').value;
          if (!bd.trim()) { T('Body cannot be empty'); return; }
          try {
            await authFetch('/api/email/queue',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({prospect_id:dp.id,to_email:(dp.email||dp.dm_email||''),subject:s,body:bd,status:'draft',sender_key:getSenderKey('email_sender')})});
            // Mark sample event as notified
            try { await api('/sample-tracking/'+dp.id+'/'+eid, {method:'PUT', body:{notified_at: new Date().toISOString().substring(0,16).replace('T',' '), notified_channel: 'email'}}); } catch(e) {}
  showDraftHint('Email saved to drafts - marked notified');
            try { var r = await api('/sample-tracking/'+dp.id); drSample = Array.isArray(r) ? r : []; } catch(e) {}
            DTSample(document.getElementById('dbody') || b);
            closeFn();
          } catch(e) { T('Save draft failed', '#dc2626'); }
        };

        var polishBtn = document.getElementById('smpNotifyPolish');
        polishBtn.onclick = function(){
          document.getElementById('smpNotifyPolishHint').style.display = 'block';
        };

        document.getElementById('smpPolishGo').onclick = async function(){
          var inst = document.getElementById('smpPolishInst').value;
          if (!inst.trim()) { T('Enter polish instructions'); return; }
          T('AI is polishing...');
          try {
            var revR = await api('/ai/revise-message/'+dp.id, {method:'POST', body:{current_subject:document.getElementById('smpNotifySubj').value, current_body:document.getElementById('smpNotifyBody').value, instruction:inst, message_type:'cold_email', tone:'human'}});
            if (revR.success && revR.result) {
              if (revR.result.body) document.getElementById('smpNotifyBody').value = revR.result.body;
              if (revR.result.subject) document.getElementById('smpNotifySubj').value = revR.result.subject;
              document.getElementById('smpPolishInst').value = '';
              T('Polished');
            } else { T('Polish failed', '#dc2626'); }
          } catch(e) { T('Polish failed', '#dc2626'); }
        };
        document.getElementById('smpNotifyPolishHint').style.display = 'none';
        T('Email draft generated');
      } catch(e) { console.error('[SMP-NOTIFY-EMAIL] Failed:', e); T('Generation failed: '+(e.detail||e.message||''), '#dc2626'); }
    };
  });

  // LinkedIn notification — generate message + copy
  b.querySelectorAll('[data-smp-notify-linkedin]').forEach(function(btn){
    btn.onclick = async function(){
      var eid = parseInt(btn.dataset.smpNotifyLinkedin);
      var ev = drSample.find(function(e){ return e.id === eid; });
      if (!ev) return;
      var stage = ev.stage || '';
      var stageLabels = {requested:'Sample pending',sent:'Sample sent',received:'Customer signed',testing:'Testing',feedback:'Feedback',trial_order:'Trial order',completed:'Done',dead:'Sample failed'};
      var stageLabel = stageLabels[stage] || stage;

      var ctx = 'Client: '+E(dp.company)+' | '+E(dp.country)+' | Profile '+E(dp.profile_type||'')+'\n';
      ctx += 'Sample stage: '+stageLabel+'\n';
      if (ev.tracking_number) ctx += 'Carrier: '+E(ev.carrier||'')+' '+E(ev.tracking_number)+'\n';
      if (ev.tracking_url) ctx += 'Tracking URL: '+E(ev.tracking_url)+'\n';
      if (ev.expected_arrival) ctx += 'Expected arrival: '+E(ev.expected_arrival)+'\n';
      if (ev.test_purpose) ctx += 'Test purpose: '+E(ev.test_purpose)+'\n';
      if (ev.ai_followup_prompt) ctx += 'AI followup prompt: '+E(ev.ai_followup_prompt)+'\n';

      T('AI is generating a LinkedIn message...');
      try {
        var genBody = {
          message_type: 'linkedin_connection_note',
          tone: 'warm',
          additional_context: 'LinkedIn DM to notify client about sample status: '+stageLabel+'\n'+ctx+'\nShort, friendly LinkedIn DM in Chinese. 2-3 sentences max. Include tracking details if available. Professional but casual tone.'
        };
        var genModel = getPanelModel('model_sample');
        if (genModel !== 'auto') genBody.model_override = genModel;
        var genR = await api('/ai/generate-message/'+dp.id, {method:'POST', body: genBody});
        if (!genR.success) { T('AIGeneration failed', '#dc2626'); return; }

        var text = genR.result.body || genR.result.content || genR.result.message || '';
        if (!text) { T('Generated content is empty', '#dc2626'); return; }

        // Show preview + copy
        var oldM = document.getElementById('smpNotifyMsk'); if(oldM) oldM.remove();
        var oldC = document.getElementById('smpNotifyWrap'); if(oldC) oldC.remove();
        var h = '<div class="mask" style="z-index:80" id="smpNotifyMsk"></div>';
        h += '<div id="smpNotifyWrap" class="card" style="position:fixed;top:15%;left:50%;transform:translateX(-50%);width:520px;max-width:90vw;max-height:70vh;overflow-y:auto;z-index:90;padding:24px;background:#fff">';
        h += '<div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:12px"><b style="font-size:15px">LinkedIn message - '+E(stageLabel)+'</b><button style="border:none;background:none;font-size:22px;cursor:pointer;color:#64748b" id="smpNotifyClose">&times;</button></div>';
        h += '<div style="font-size:11px;color:#64748b;margin-bottom:8px">Recipient: <b>'+E(dp.company||'')+'</b> · <a href="'+E(customerLinkedIn)+'" target="_blank" style="color:#0A66C2">Open LinkedIn</a></div>';
        h += '<textarea id="smpLIBody" rows="6" style="font-size:13px;line-height:1.6;margin-bottom:8px;width:100%;padding:10px;border:1px solid #d1d5db;border-radius:6px;resize:vertical" spellcheck="false">'+E(text)+'</textarea>';
        h += '<div style="display:flex;gap:6px">';
        h += '<button class="btn" style="background:#0A66C2" id="smpLICopy">Copy to clipboard</button>';
        h += '<button class="btn btn-sm" style="background:#6366f1" id="smpLIPolish">AI polish</button>';
        h += '<button class="btn btn-sm" style="background:#f59e0b" id="smpLISaveInt">Save to Interactionsns</button>';
        h += '</div><div id="smpLIPolishHint" style="margin-top:6px"><input id="smpLIPolishInst" placeholder="Tell AI how to revise..." style="font-size:12px;margin-bottom:4px"><button class="btn btn-sm" style="background:#eab308;color:#fff" id="smpLIPolishGo">Revise</button></div>';
        h += '</div></div>';
        document.body.insertAdjacentHTML('beforeend', h);

        var msk2 = document.getElementById('smpNotifyMsk');
        var wrap2 = document.getElementById('smpNotifyWrap');
        var closeFn2 = function(){ msk2.remove(); wrap2.remove(); };
        msk2.onclick = closeFn2;
        document.getElementById('smpNotifyClose').onclick = closeFn2;

        document.getElementById('smpLICopy').onclick = function(){
          navigator.clipboard.writeText(document.getElementById('smpLIBody').value);
          T('LinkedIn message copied');
          closeFn2();
        };

        document.getElementById('smpLISaveInt').onclick = async function(){
          var txt = document.getElementById('smpLIBody').value;
          if (!txt.trim()) return;
          try {
            await api('/interactions', {method:'POST', body:{prospect_id:dp.id, channel:'linkedin', direction:'outbound', content:txt, interacted_at:new Date().toISOString().substring(0,10)}});
            // Mark sample event as notified
            try { await api('/sample-tracking/'+dp.id+'/'+eid, {method:'PUT', body:{notified_at: new Date().toISOString().substring(0,16).replace('T',' '), notified_channel: 'linkedin'}}); } catch(e) {}
            T('Saved to interactions · marked notified');
            try { var r = await api('/interactions/'+dp.id); drInts = Array.isArray(r) ? r : []; } catch(e) {}
            try { var r2 = await api('/sample-tracking/'+dp.id); drSample = Array.isArray(r2) ? r2 : []; } catch(e) {}
            DTSample(document.getElementById('dbody') || b);
            closeFn2();
          } catch(e) { T('Save failed', '#dc2626'); }
        };

        var polishBtn2 = document.getElementById('smpLIPolish');
        polishBtn2.onclick = function(){
          document.getElementById('smpLIPolishHint').style.display = 'block';
        };

        document.getElementById('smpLIPolishGo').onclick = async function(){
          var inst = document.getElementById('smpLIPolishInst').value;
          if (!inst.trim()) { T('Enter polish instructions'); return; }
          T('AI is polishing...');
          try {
            var revR = await api('/ai/revise-message/'+dp.id, {method:'POST', body:{current_subject:'', current_body:document.getElementById('smpLIBody').value, instruction:inst, message_type:'linkedin_connection_note', tone:'warm'}});
            if (revR.success && revR.result) {
              if (revR.result.body) document.getElementById('smpLIBody').value = revR.result.body;
              document.getElementById('smpLIPolishInst').value = '';
              T('Polished');
            } else { T('Polish failed', '#dc2626'); }
          } catch(e) { T('Polish failed', '#dc2626'); }
        };
        document.getElementById('smpLIPolishHint').style.display = 'none';
        T('LinkedIn message generated');
      } catch(e) { console.error('[SMP-NOTIFY-EMAIL] Failed:', e); T('Generation failed: '+(e.detail||e.message||''), '#dc2626'); }
    };
  });

  // WhatsApp notification — generate + save as interaction
  b.querySelectorAll('[data-smp-notify-whatsapp]').forEach(function(btn){
    btn.onclick = async function(){
      var eid = parseInt(btn.dataset.smpNotifyWhatsapp);
      var ev = drSample.find(function(e){ return e.id === eid; });
      if (!ev) return;
      var stage = ev.stage || '';
      var stageLabels = {requested:'Sample pending',sent:'Sample sent',received:'Customer signed',testing:'Testing',feedback:'Feedback',trial_order:'Trial order',completed:'Done',dead:'Sample failed'};
      var stageLabel = stageLabels[stage] || stage;

      var ctx = 'Client: '+E(dp.company)+' | '+E(dp.country)+' | Profile '+E(dp.profile_type||'')+'\nSample stage: '+stageLabel+'\n';
      if (ev.tracking_number) ctx += 'Tracking: '+E(ev.carrier||'')+' '+E(ev.tracking_number)+'\n';
      if (ev.expected_arrival) ctx += 'ETA: '+E(ev.expected_arrival)+'\n';
      if (ev.ai_followup_prompt) ctx += 'AI prompt: '+E(ev.ai_followup_prompt)+'\n';

      T('AI is generating a WhatsApp message...');
      try {
        var genBody = {
          message_type: 'cold_email',
          tone: 'warm',
          additional_context: 'Short WhatsApp message to client about sample: '+stageLabel+'\n'+ctx+'\nVERY short (2-3 lines max), friendly, in Chinese. WhatsApp style — casual but professional.'
        };
        var genModel = getPanelModel('model_sample');
        if (genModel !== 'auto') genBody.model_override = genModel;
        var genR = await api('/ai/generate-message/'+dp.id, {method:'POST', body: genBody});
        if (!genR.success) { T('AIGeneration failed', '#dc2626'); return; }

        var text = genR.result.body || genR.result.content || '';
        if (!text) { T('Generated content is empty', '#dc2626'); return; }

        var oldM = document.getElementById('smpNotifyMsk'); if(oldM) oldM.remove();
        var oldC = document.getElementById('smpNotifyWrap'); if(oldC) oldC.remove();
        var h = '<div class="mask" style="z-index:80" id="smpNotifyMsk"></div>';
        h += '<div id="smpNotifyWrap" class="card" style="position:fixed;top:15%;left:50%;transform:translateX(-50%);width:480px;max-width:90vw;max-height:70vh;overflow-y:auto;z-index:90;padding:24px;background:#fff">';
        h += '<div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:12px"><b style="font-size:15px">💬 WhatsApp — '+E(stageLabel)+'</b><button style="border:none;background:none;font-size:22px;cursor:pointer;color:#64748b" id="smpNotifyClose">&times;</button></div>';
        h += '<div style="font-size:11px;color:#64748b;margin-bottom:8px">Send to: <b>'+E(dp.company||'')+'</b> · '+E(dp.phone||'')+'</div>';
        h += '<textarea id="smpWABody" rows="5" style="font-size:13px;line-height:1.6;margin-bottom:8px;width:100%;padding:10px;border:1px solid #d1d5db;border-radius:6px;resize:vertical" spellcheck="false">'+E(text)+'</textarea>';
        h += '<div style="display:flex;gap:6px">';
        h += '<button class="btn" style="background:#25D366" id="smpWACopy">Copy to clipboard</button>';
        h += '<button class="btn btn-sm" style="background:#6366f1" id="smpWAI">AI rewrite</button>';
        h += '<button class="btn btn-sm" style="background:#f59e0b" id="smpWASaveInt">Save to Interactionsns</button>';
        h += '</div></div></div>';
        document.body.insertAdjacentHTML('beforeend', h);

        var msk = document.getElementById('smpNotifyMsk'), wrap = document.getElementById('smpNotifyWrap');
        var closeFn = function(){ msk.remove(); wrap.remove(); };
        msk.onclick = closeFn;
        document.getElementById('smpNotifyClose').onclick = closeFn;

        document.getElementById('smpWACopy').onclick = function(){
          navigator.clipboard.writeText(document.getElementById('smpWABody').value);
          T('Copied - paste into WhatsApp to send');
          closeFn();
        };

        document.getElementById('smpWASaveInt').onclick = async function(){
          var txt = document.getElementById('smpWABody').value;
          if (!txt.trim()) return;
          try {
            await api('/interactions', {method:'POST', body:{prospect_id:dp.id, channel:'whatsapp', direction:'outbound', content:txt, interacted_at:new Date().toISOString().substring(0,10)}});
            try { await api('/sample-tracking/'+dp.id+'/'+eid, {method:'PUT', body:{notified_at: new Date().toISOString().substring(0,16).replace('T',' '), notified_channel: 'whatsapp'}}); } catch(e) {}
            T('Saved to interactions · marked notified');
            try { var r = await api('/interactions/'+dp.id); drInts = Array.isArray(r) ? r : []; } catch(e) {}
            try { var r2 = await api('/sample-tracking/'+dp.id); drSample = Array.isArray(r2) ? r2 : []; } catch(e) {}
            DTSample(document.getElementById('dbody') || b);
            closeFn();
          } catch(e) { T('Save failed', '#dc2626'); }
        };

        document.getElementById('smpWAI').onclick = async function(){
          T('AI rewriting...');
          try {
            var revR = await api('/ai/revise-message/'+dp.id, {method:'POST', body:{current_body:document.getElementById('smpWABody').value, instruction:'Make it more conversational and warmer, in Chinese, WhatsApp style', message_type:'cold_email', tone:'warm'}});
            if (revR.success && revR.result && revR.result.body) {
              document.getElementById('smpWABody').value = revR.result.body;
              T('Rewritten');
            } else { T('Rewrite failed', '#dc2626'); }
          } catch(e) { T('Rewrite failed', '#dc2626'); }
        };
        T('WhatsApp message generated');
      } catch(e) { console.error('[SMP-NOTIFY-EMAIL] Failed:', e); T('Generation failed: '+(e.detail||e.message||''), '#dc2626'); }
    };
  });

  // WeChat notification — generate + save as interaction
  b.querySelectorAll('[data-smp-notify-wechat]').forEach(function(btn){
    btn.onclick = async function(){
      var eid = parseInt(btn.dataset.smpNotifyWechat);
      var ev = drSample.find(function(e){ return e.id === eid; });
      if (!ev) return;
      var stage = ev.stage || '';
      var stageLabels = {requested:'Sample pending',sent:'Sample sent',received:'Customer signed',testing:'Testing',feedback:'Feedback',trial_order:'Trial order',completed:'Done',dead:'Sample failed'};
      var stageLabel = stageLabels[stage] || stage;

      var ctx = 'Client: '+E(dp.company)+' | '+E(dp.country)+' | Profile '+E(dp.profile_type||'')+'\nSample stage: '+stageLabel+'\n';
      if (ev.tracking_number) ctx += 'Tracking: '+E(ev.carrier||'')+' '+E(ev.tracking_number)+'\n';
      if (ev.expected_arrival) ctx += 'ETA: '+E(ev.expected_arrival)+'\n';
      if (ev.ai_followup_prompt) ctx += 'AI prompt: '+E(ev.ai_followup_prompt)+'\n';

      T('AI is generating a WeChat message...');
      try {
        var genBody = {
          message_type: 'cold_email',
          tone: 'warm',
          additional_context: 'WeChat message to client about sample: '+stageLabel+'\n'+ctx+'\nShort (2-4 lines), friendly, in Chinese. WeChat style — casual, natural, like talking to a business friend.'
        };
        var genModel = getPanelModel('model_sample');
        if (genModel !== 'auto') genBody.model_override = genModel;
        var genR = await api('/ai/generate-message/'+dp.id, {method:'POST', body: genBody});
        if (!genR.success) { T('AIGeneration failed', '#dc2626'); return; }

        var text = genR.result.body || genR.result.content || '';
        if (!text) { T('Generated content is empty', '#dc2626'); return; }

        var oldM = document.getElementById('smpNotifyMsk'); if(oldM) oldM.remove();
        var oldC = document.getElementById('smpNotifyWrap'); if(oldC) oldC.remove();
        var h = '<div class="mask" style="z-index:80" id="smpNotifyMsk"></div>';
        h += '<div id="smpNotifyWrap" class="card" style="position:fixed;top:15%;left:50%;transform:translateX(-50%);width:480px;max-width:90vw;max-height:70vh;overflow-y:auto;z-index:90;padding:24px;background:#fff">';
        h += '<div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:12px"><b style="font-size:15px">WeChat notification - '+E(stageLabel)+'</b><button style="border:none;background:none;font-size:22px;cursor:pointer;color:#64748b" id="smpNotifyClose">&times;</button></div>';
        h += '<div style="font-size:11px;color:#64748b;margin-bottom:8px">Send to: <b>'+E(dp.company||'')+'</b> · WeChat: '+E(dp.wechat||'')+'</div>';
        h += '<textarea id="smpWXBody" rows="5" style="font-size:13px;line-height:1.6;margin-bottom:8px;width:100%;padding:10px;border:1px solid #d1d5db;border-radius:6px;resize:vertical" spellcheck="false">'+E(text)+'</textarea>';
        h += '<div style="display:flex;gap:6px">';
        h += '<button class="btn" style="background:#07C160;color:#fff" id="smpWXCopy">Copy to WeChat</button>';
        h += '<button class="btn btn-sm" style="background:#6366f1" id="smpWXAI">AI rewrite</button>';
        h += '<button class="btn btn-sm" style="background:#f59e0b" id="smpWXSaveInt">Save to Interactionsns</button>';
        h += '</div></div></div>';
        document.body.insertAdjacentHTML('beforeend', h);

        var msk = document.getElementById('smpNotifyMsk'), wrap = document.getElementById('smpNotifyWrap');
        var closeFn = function(){ msk.remove(); wrap.remove(); };
        msk.onclick = closeFn;
        document.getElementById('smpNotifyClose').onclick = closeFn;

        document.getElementById('smpWXCopy').onclick = function(){
          navigator.clipboard.writeText(document.getElementById('smpWXBody').value);
          T('Copied - paste into WeChat to send');
          closeFn();
        };

        document.getElementById('smpWXSaveInt').onclick = async function(){
          var txt = document.getElementById('smpWXBody').value;
          if (!txt.trim()) return;
          try {
            await api('/interactions', {method:'POST', body:{prospect_id:dp.id, channel:'wechat', direction:'outbound', content:txt, interacted_at:new Date().toISOString().substring(0,10)}});
            try { await api('/sample-tracking/'+dp.id+'/'+eid, {method:'PUT', body:{notified_at: new Date().toISOString().substring(0,16).replace('T',' '), notified_channel: 'wechat'}}); } catch(e) {}
            T('Saved to interactions · marked notified');
            try { var r = await api('/interactions/'+dp.id); drInts = Array.isArray(r) ? r : []; } catch(e) {}
            try { var r2 = await api('/sample-tracking/'+dp.id); drSample = Array.isArray(r2) ? r2 : []; } catch(e) {}
            DTSample(document.getElementById('dbody') || b);
            closeFn();
          } catch(e) { T('Save failed', '#dc2626'); }
        };

        document.getElementById('smpWXAI').onclick = async function(){
          T('AI rewriting...');
          try {
            var revR = await api('/ai/revise-message/'+dp.id, {method:'POST', body:{current_body:document.getElementById('smpWXBody').value, instruction:'Make it more conversational and natural in Chinese, WeChat style', message_type:'cold_email', tone:'warm'}});
            if (revR.success && revR.result && revR.result.body) {
              document.getElementById('smpWXBody').value = revR.result.body;
              T('Rewritten');
            } else { T('Rewrite failed', '#dc2626'); }
          } catch(e) { T('Rewrite failed', '#dc2626'); }
        };
        T('WeChat message generated');
      } catch(e) { console.error('[SMP-NOTIFY-EMAIL] Failed:', e); T('Generation failed: '+(e.detail||e.message||''), '#dc2626'); }
    };
  });
}



// ── TAB: Sequence ──
function DTSeq(b){
  var hasInteractions = drInts && drInts.length > 0;
  var aiScheduledCount = drSeqs ? drSeqs.filter(function(s){ return (s.subject||'').startsWith('[AI') && s.status==='pending'; }).length : 0;

  // Channel definitions
  var channels = [
    {id:'linkedin', label:'LinkedIn', icon:'💼', color:'#0A66C2', avail: !!(dp.linkedin && dp.linkedin.trim())},
    {id:'whatsapp', label:'WhatsApp', icon:'💬', color:'#25D366', avail: !!(dp.phone && dp.phone.trim())},
    {id:'phone',    label:'Phone',    icon:'📞', color:'#f97316', avail: !!(dp.phone && dp.phone.trim())},
    {id:'email',    label:'Email',    icon:'📧', color:'#3b82f6', avail: !!(dp.email && dp.email.trim())},
  ];

  // Default active channel: first one with steps, or first available
  var activeChannel = (window._seqActiveCh && channels.find(function(c){return c.id===window._seqActiveCh;}))
    ? window._seqActiveCh
    : (function(){
      // 默认优先Email，方便直接看到/EditEmail内容
      var preferred = ['email','linkedin','whatsapp','phone'];
      for (var i=0;i<preferred.length;i++) {
        var ch = preferred[i];
        if (drSeqs.some(function(s){ return s.channel===ch && s.status==='pending'; })) return ch;
      }
      for (var j=0;j<preferred.length;j++) { if (drSeqs.some(function(s){ return s.channel===preferred[j]; })) return preferred[j]; }
      return channels.find(function(c){return c.avail;}) ? channels.find(function(c){return c.avail;}).id : 'email';
    })();
  window._seqActiveCh = activeChannel;

  function stepWho(s){
    if (s.to_email) return s.to_email;
    if (s.channel==='phone') return 'Phone';
    var m = /^(LinkedIn to|Call|Phone)\s*([^:\n，]+)/.exec(s.content || '');
    if (m && m[2]) return m[2].trim();
    return dp.contact || 'this customer';
  }

  // 与后端一致：主记录 = 有决策人的最早记录；否则公共Email；否则最早创建
  function companyMainOf(list){
    var sorted = (list || []).slice().sort(function(a,b){ return (a.id||0)-(b.id||0); });
    for (var i=0;i<sorted.length;i++){ if (sorted[i].decision_maker) return sorted[i]; }
    for (var j=0;j<sorted.length;j++){
      var em = String(sorted[j].email || '').toLowerCase();
      if (em.indexOf('info@') === 0 || em.indexOf('einkauf@') === 0 || em.indexOf('purchase') >= 0) return sorted[j];
    }
    return sorted[0] || null;
  }

  var h = '';

  // ── 期说明：Planned send / Actual send / 下次跟踪（带逾期警示）──
  (function(){
    var today = new Date().toISOString().substring(0,10);
    var nfd = dp.next_follow_date ? String(dp.next_follow_date).substring(0,10) : '';
    var nfHtml = 'Not set';
    if (nfd) {
      var diff = Math.ceil((new Date(nfd+'T00:00:00') - new Date(today+'T00:00:00')) / 86400000);
      var col, bg, txt;
      if (diff < 0) { col='#dc2626'; bg='#fef2f2'; txt='Overdue '+Math.abs(diff)+' days'; }
      else if (diff === 0) { col='#f97316'; bg='#fff7ed'; txt='Today'; }
      else if (diff <= 3) { col='#f59e0b'; bg='#fffbeb'; txt=diff+' days'; }
      else { col='#16a34a'; bg='#f0fdf4'; txt=diff+' days'; }
      nfHtml = E(nfd)+' <span style="background:'+bg+';color:'+col+';padding:1px 6px;border-radius:8px;font-weight:700">'+txt+'</span>';
    }
    h += '<div style="display:flex;gap:14px;margin-bottom:10px;flex-wrap:wrap;align-items:center;font-size:11px;color:#64748b">';
  h += '<span style="display:inline-flex;align-items:center;gap:4px">📤 <b style="color:#334155">Planned send</b> = scheduled send time for not-yet-sent steps (editable)</span>';
  h += '<span style="display:inline-flex;align-items:center;gap:4px">✅ <b style="color:#334155">Actual send</b> = real send date of completed steps</span>';
    h += '<span style="display:inline-flex;align-items:center;gap:4px">📅 <b style="color:#334155">Next follow-up</b>: '+nfHtml+'</span>';
    h += '</div>';
  })();

  // Status banners
  if (drIntel && drIntel.change_flags) {
    h += '<div class="card p3 mb3" style="background:#fffced;border:1px solid #f59e0b"><div style="display:flex;align-items:center;gap:6px"><span style="font-size:16px">🔔</span><div><p style="font-size:13px;font-weight:600;color:#b45309">Intelligence change</p><p style="font-size:12px;color:#92400e;line-height:1.5">'+E(drIntel.change_flags)+'</p></div></div></div>';
  }

  // ── Next action reminder: find the soonest pending step across ALL channels ──
  (function(){
    var today = new Date().toISOString().substring(0,10);
    var pendingSteps = drSeqs.filter(function(s){ return s.status==='pending' && s.scheduled_date; }).sort(function(a,b){ return (a.scheduled_date||'') < (b.scheduled_date||'') ? -1 : 1; });
    if (pendingSteps.length > 0) {
      var next = pendingSteps[0];
      var chLabels = {email:'📧Email', linkedin:'💼LinkedIn', whatsapp:'💬WhatsApp', phone:'📞Phone'};
      var isToday = next.scheduled_date === today;
      var daysAway = Math.ceil((new Date(next.scheduled_date+'T00:00:00') - new Date(today+'T00:00:00')) / 86400000);
      var urgencyColor = isToday ? '#dc2626' : daysAway <= 2 ? '#f59e0b' : '#0891b2';
      var urgencyBg = isToday ? '#fef2f2' : daysAway <= 2 ? '#fffbeb' : '#ecfeff';
      var labelText = isToday ? '⚠️ Execute today' : daysAway > 0 ? '📅 '+daysAway+' days' : '⏰ Overdue '+Math.abs(daysAway)+' days';
      h += '<div class="card p2 mb3" style="background:'+urgencyBg+';border-left:4px solid '+urgencyColor+'">';
      h += '<span style="font-size:13px;font-weight:600;color:'+urgencyColor+'">'+labelText+'</span>';
      h += '<span style="font-size:11px;color:#64748b;margin-left:8px">'+(chLabels[next.channel]||next.channel)+' Step '+next.step_number+' · Planned send '+E(next.scheduled_date)+'</span>';
      h += '</div>';
    } else if (drSeqs.length > 0) {
  h += '<div class="card p3 mb3" style="background:#f0fdf6;border:1px solid #10b981"><p style="font-size:13px;font-weight:600;color:#166534">✅ All steps done</p><p style="font-size:12px;color:#166534">Click Generate next step to continue, or tick Cold outreach done so AI can suggest another channel.</p></div>';
    }
  })();

  // ── 开发顺序：一眼看到Step 几步、联系谁 ──
  if (drSeqs && drSeqs.length) {
    var orderedAll = drSeqs.slice().sort(function(a,b){ return (a.step_number||0)-(b.step_number||0); });
    var pendingAll = orderedAll.filter(function(s){ return s.status==='pending'; });
    if (pendingAll.length) {
      var chIcons2 = {email:'📧',linkedin:'💼',whatsapp:'💬',phone:'📞'};
      var chipHtml = pendingAll.map(function(s){
        var who = stepWho(s);
        var dt = s.scheduled_date ? String(s.scheduled_date).substring(5) : 'Pending';
        return '<span style="display:inline-flex;align-items:center;gap:3px;background:#eef2ff;color:#3730a3;border:1px solid #c7d2fe;padding:3px 9px;border-radius:12px;font-size:11px;font-weight:600">'+(chIcons2[s.channel]||'')+' Step '+s.step_number+' '+E(who)+' '+E(dt)+'</span>';
      }).join('<span style="color:#a5b4fc;font-weight:700;font-size:13px;margin:0 2px">→</span>');
      h += '<div class="card p2 mb3" style="background:#f8fafc;border:1px solid #e2e8f0">';
      h += '<div style="font-size:12px;font-weight:600;color:#334155;margin-bottom:5px">Outreach sequence</div>';
      h += '<div style="display:flex;gap:6px;flex-wrap:wrap">'+chipHtml+'</div>';
      h += '<div style="font-size:10px;color:#94a3b8;margin-top:5px">Only move to the next step if the previous one got no reply - complete flow, no repeated contacts.</div>';
      h += '</div>';
    }
  }

  // ── AI 智能Development Plan：按决策链Generate完整流程 ──
  h += '<div class="card p3 mb3" style="background:#f5f3ff;border:1px solid #ddd6fe">';
  h += '<div class="flex jcs aic" style="gap:10px;flex-wrap:wrap">';
  h += '<div style="flex:1;min-width:220px">';
  h += '<p style="font-size:13px;font-weight:600;color:#4c1d95">AI smart outreach plan</p>';
  h += '<p style="font-size:11px;color:#6d28d9;line-height:1.5;margin-top:2px">Automatically analyze this company  contacts and builds a full decision-chain flow: who to contact first, when, and via which channel. After generation, every step can be edited, saved or added to drafts.</p>';
  h += '</div>';
  h += '<div class="flex aic g2" style="flex-wrap:wrap">'+renderModelSelector('model_devplan','Model')+'<button class="btn" id="smartPlanBtn" style="background:#7c3aed;color:#fff;white-space:nowrap">'+(drSeqs && drSeqs.length ? 'Regenerate smart plan' : 'Generate smart outreach plan')+'</button></div>';
  h += '</div></div>';

  if (!drSeqs || !drSeqs.length) {
    h += '<div id="mainPlanHint" class="mb3"></div>';
  }

  if (hasInteractions && aiScheduledCount > 0) {
    h += '<div class="card p3 mb3" style="background:#f3e8ff;border:1px solid #c4b5fd"><p style="font-size:13px;font-weight:600;color:#7c3aed">Outreach plan in progress</p><p style="font-size:12px;color:#6d28d9;line-height:1.5">This customer has '+drInts.length+' interactions. Finish the existing plan; AI also offers follow-up suggestions.</p></div>';
  } else if (hasInteractions) {
    h += '<div class="card p3 mb3" style="background:#fffced;border:1px solid #fcd34d"><p style="font-size:13px;font-weight:600;color:#b45309">Existing interactions</p><p style="font-size:12px;color:#92400e;line-height:1.5">This customer has '+drInts.length+' interactions. Continue executing the remaining plan steps.</p></div>';
  }

  // ── Channel tabs ──
  h += '<div style="display:flex;gap:6px;margin-bottom:10px;flex-wrap:wrap;align-items:center">';
  channels.forEach(function(ch){
    var steps = drSeqs.filter(function(s){ return s.channel===ch.id; });
    var pendingCount = steps.filter(function(s){ return s.status==='pending'; }).length;
    var hasSteps = steps.length > 0;
    var isActive = ch.id === activeChannel;
    h += '<button class="seqChTab" data-seq-ch="'+ch.id+'" style="'
      + 'padding:6px 12px;border-radius:6px;font-size:12px;font-weight:600;cursor:pointer;position:relative;border:2px solid '
      + (isActive ? ch.color : '#e5e7eb')+';background:'+(isActive ? ch.color+'15' : ch.avail ? '#fff' : '#f3f4f6')
      + ';color:'+(ch.avail ? (isActive ? ch.color : '#374151') : '#9ca3af')+';'
      + (!ch.avail ? 'opacity:0.5' : '')
      + '">';
    h += '<span style="font-size:14px">'+ch.icon+'</span> '+ch.label;
    if (pendingCount > 0) h += '<span style="position:absolute;top:-4px;right:-4px;width:10px;height:10px;border-radius:50%;background:#10b981;display:inline-block" title="'+pendingCount+' pending"></span>';
    if (hasSteps && pendingCount === 0) h += '<span style="position:absolute;top:-4px;right:-4px;width:10px;height:10px;border-radius:50%;background:#9ca3af;display:inline-block" title="'+steps.length+' steps, all done"></span>';
    if (!hasSteps && ch.avail) h += '<span style="position:absolute;top:-4px;right:-4px;width:10px;height:10px;border-radius:50%;background:#d1d5db;display:inline-block"></span>';
    h += '</button>';
  });
  // ═══ AI CHAT for Development Plan ═══
  var seqCs = b.querySelector('#seqChatSend');
  var seqCi = b.querySelector('#seqChatInput');
  if (seqCs && seqCi) {
    seqCs.onclick = async function() {
      var msg = seqCi.value.trim(); if (!msg) return;
      var md = b.querySelector('#seqChatMsgs');
      md.innerHTML += '<div style="background:#f1f5f9;padding:6px 10px;border-radius:6px;font-size:11px;margin-top:6px"><b>You:</b> '+E(msg)+'</div>';
      seqCi.value = '';
      var ld = document.createElement('div'); ld.style.cssText='color:#6366f1;font-size:11px;margin-top:4px'; ld.textContent='⏳ ...'; md.appendChild(ld);
      try {
        var seqModel = getPanelModel('model_devplan');
        var body2 = {prompt:msg, prospect_id:dp.id, voice:'human'};
        if (seqModel !== 'auto') body2.model_override = seqModel;
        var res2 = await api('/ai/chat', {method:'POST', body:body2});
        ld.remove();
        if (res2 && res2.success) { md.innerHTML += '<div style="background:#eef2ff;padding:8px 12px;border-radius:6px;font-size:12px;margin-top:6px;line-height:1.6"><b style="color:#4338ca">AI:</b><br>'+E(res2.reply||res2.result||'').replace(/\n/g,'<br>')+'</div>'; md.scrollTop=md.scrollHeight; }
      } catch(e) { ld.remove(); md.innerHTML += '<div style="color:#dc2626;font-size:11px;margin-top:4px">Send failed</div>'; }
    };
    seqCi.addEventListener('keydown', function(e) { if (e.key==='Enter') { e.preventDefault(); seqCs.click(); } });
  }
  // Refresh button
  var seqRefresh = b.querySelector('#seqChatRefresh');
  var seqClear = b.querySelector('#seqChatClear');
  var seqMd = b.querySelector('#seqChatMsgs');
  if (seqRefresh && seqMd) {
    seqRefresh.onclick = async function() {
      seqMd.innerHTML = '<div style="color:#6366f1;font-size:11px;text-align:center;padding:10px">⏳ Re-analyzing...</div>';
      try {
        var seqModelR = getPanelModel('model_devplan');
        var profileInfo = (dp.profile_summary||'') + ' ' + (dp.profile_type||'') + ' ' + (dp.pain_points||'') + ' ' + (dp.profile_refined||'');
        var interactionsSummary = (drInts||[]).map(function(i){return (i.direction==='inbound'?'Customer':'Outbound')+': '+ (i.content||'').substring(0,300);}).join('\n').substring(0,3000);
        var bodyR = {prompt:'Customer: '+E(dp.company)+' | '+E(dp.country)+' | Profile '+E(dp.profile_type)+'\nProfile: '+profileInfo.substring(0,800)+'\n\nInteraction history:\n'+interactionsSummary+'\n\nAnalyze: 1) current outreach pace and stage 2) recommended next action (email follow-up / proposal quote / channel switch / other) 3) a draft message if suitable. Reply in English with points 1,2,3.', prospect_id: dp.id, voice: 'human'};
        if (seqModelR !== 'auto') bodyR.model_override = seqModelR;
        var resR = await api('/ai/chat', {method:'POST', body: bodyR});
        if (resR && resR.success) {
          seqMd.innerHTML = '<div style="background:#eef2ff;padding:10px 14px;border-radius:6px;font-size:13px;line-height:1.7"><b style="color:#4338ca">AI analysis:</b><br><br>'+E(resR.reply||resR.result||'').replace(/\n/g,'<br>')+'</div>';
        }
      } catch(e) { seqMd.innerHTML = '<div style="color:#dc2626;text-align:center">Analysis failed: '+(e.detail||e.message||'')+'</div>'; }
    };
  }
  if (seqClear && seqMd) {
    seqClear.onclick = function(){
      _seqChatSaved = '';
      seqMd.innerHTML = '<div style="color:#64748b;text-align:center;padding:10px;font-size:11px">I know this customer profile, pain points and intelligence. Tell me your thoughts and I will help with the '+activeChDef.label+' cold-outreach strategy.</div>';
    };
  }

  // ═══ Sequence step action buttons ═══
  // Done / Skip
  b.querySelectorAll('[data-seq-done]').forEach(function(btn){
    btn.addEventListener('click', async function(){
      var seqId = parseInt(btn.dataset.seqDone);
      btn.disabled = true; btn.textContent = '...';
      try {
        await execStep(seqId, 'done');
      } catch(e) { T('Operation failed', '#dc2626'); btn.disabled = false; btn.textContent = 'Done'; }
    });
  });
  b.querySelectorAll('[data-seq-skip]').forEach(function(btn){
    btn.addEventListener('click', async function(){
      var seqId = parseInt(btn.dataset.seqSkip);
      btn.disabled = true; btn.textContent = '...';
      try {
        await execStep(seqId, 'skipped');
      } catch(e) { T('Operation failed', '#dc2626'); btn.disabled = false; btn.textContent = 'Skip'; }
    });
  });
  // Auto-save on blur: when user finishes editing subject or content, save to backend
  b.querySelectorAll('[data-seq-id][data-field]').forEach(function(el){
    el.addEventListener('blur', async function(){
      var seqId = parseInt(el.dataset.seqId);
      var row = el.closest('.card') || el.parentElement;
      var subjectEl = row ? row.querySelector('[data-field="subject"]') : null;
      var contentEl = row ? row.querySelector('[data-field="content"]') : null;
      var toEmailEl = row ? row.querySelector('[data-field="to_email"]') : null;
      var subj = subjectEl ? subjectEl.value : '';
      var body = contentEl ? contentEl.value : '';
      var toEmail = toEmailEl ? toEmailEl.value.trim() : '';
      try {
        await api('/sequences/'+seqId, {method:'PUT', body:{subject:subj, content:body, to_email:toEmail}});
      } catch(e) { /* silent */ }
    });
  });
  // Save — saves to Sequence with auto next-follow-date, and creates draft in EmailQueue (email only)
  b.querySelectorAll('[data-save-seq]').forEach(function(btn){
    btn.addEventListener('click', async function(){
      var seqId = parseInt(btn.dataset.saveSeq);
      var row = btn.closest('.card') || btn.parentElement;
      var subjectEl = row ? row.querySelector('[data-field="subject"]') : null;
      var contentEl = row ? row.querySelector('[data-field="content"]') : null;
      var scheduleEl = row ? row.querySelector('.seqDate') : null;
      var toEmailEl = row ? row.querySelector('[data-field="to_email"]') : null;
      var subject = subjectEl ? subjectEl.value : '';
      var content = contentEl ? contentEl.value : '';
      var schedDate = scheduleEl ? scheduleEl.value : '';
      var toEmail = toEmailEl ? toEmailEl.value.trim() : '';
      btn.disabled = true;
      try {
        // Save to Sequence (backend auto-calculates next_follow_date)
        var putBody = {subject: subject, content: content};
        putBody.to_email = toEmail;
        if (schedDate) putBody.scheduled_date = schedDate;
        await api('/sequences/'+seqId, {method:'PUT', body: putBody});
        // Refresh prospect data to see the new next_follow_date
        try { var fresh = await api('/prospects/'+dp.id); if (fresh) dp = fresh; } catch(e) {}
        // For email steps only: create an email draft
        var seqData = drSeqs.find(function(x){ return x.id === seqId; });
        var isEmail = seqData && seqData.channel === 'email';
        if (isEmail && (toEmail || dp.email || dp.dm_email)) {
          try {
            await api('/email/queue', {method:'POST', body:{
              prospect_id: dp.id, sequence_id: seqId,
              to_email: toEmail || dp.email || dp.dm_email || '',
              subject: subject, body: content, status: 'draft',
              sender_key: getSenderKey('email_sender')
            }});
            T('Saved · email draft synced; next follow-up '+(dp.next_follow_date ? dp.next_follow_date : 'not set'));
            try { await loadEmail(); } catch(e) {}
          } catch(e2) { T('Saved · Next follow-up '+(dp.next_follow_date ? dp.next_follow_date : 'not set')); }
        } else {
          T('Saved · Next follow-up '+(dp.next_follow_date ? dp.next_follow_date : 'not set'));
        }
      } catch(e) { T('Save failed', '#dc2626'); }
      btn.disabled = false;
    });
  });
  // Delete — also removes linked email drafts from Email管理
  b.querySelectorAll('[data-seq-del]').forEach(function(btn){
    btn.addEventListener('click', async function(){
      var seqId = parseInt(btn.dataset.seqDel);
      if (!confirm('Delete step '+seqId+'? The linked email draft will also be deleted.')) return;
      btn.disabled = true;
      try {
        await api('/sequences/'+seqId+'/delete', {method:'POST'});
        drSeqs = await api('/sequences/'+dp.id);
        try { await loadEmail(); } catch(e) {}
        renderDrawer();
        T('Deleted');
      } catch(e) { T('Delete failed', '#dc2626'); }
      btn.disabled = false;
    });
  });
  // Copy
  b.querySelectorAll('[data-copy-seq]').forEach(function(btn){
    btn.addEventListener('click', async function(){
      var txt = btn.dataset.copyTxt || '';
      try { await navigator.clipboard.writeText(txt); T('Copied'); } catch(e) { T('Copy failed', '#dc2626'); }
    });
  });
  // Insert signature
  b.querySelectorAll('[data-sign-seq]').forEach(function(btn){
    btn.addEventListener('click', function(){
      var seqId = parseInt(btn.dataset.signSeq);
      var row = btn.closest('.card') || btn.parentElement;
      if (!row) return;
      var sel = row.querySelector('[data-sign-type]');
      var sigVal = sel ? sel.value : 'AUTO';
      var sig = resolveSelectedSignature(sigVal, dp && dp.profile_type);
      if (!sig) { T('No signature available'); return; }
      var ta = row.querySelector('[data-field="content"]');
      if (!ta) return;
      ta.value = (ta.value || '').trim() + '\n\n' + sig;
      T('Signature inserted');
    });
  });
  // Queue email — read latest from textarea, save to Sequence first, then enqueue
  b.querySelectorAll('[data-queue-seq]').forEach(function(btn){
    btn.addEventListener('click', async function(){
      var seqId = parseInt(btn.dataset.queueSeq);
      btn.disabled = true; btn.textContent = 'Queuing...';
      try {
        // Read current values from the textareas in case user edited inline
        var row = btn.closest('.card') || btn.parentElement;
        var subjectEl = row ? row.querySelector('[data-field="subject"]') : null;
        var contentEl = row ? row.querySelector('[data-field="content"]') : null;
        var toEmailEl = row ? row.querySelector('[data-field="to_email"]') : null;
        var subj = subjectEl ? subjectEl.value : '';
        var body = contentEl ? contentEl.value : '';
        var toEmail = toEmailEl ? toEmailEl.value.trim() : '';
        // Save to Sequence first so the backend reads the latest version
        await api('/sequences/'+seqId, {method:'PUT', body:{subject:subj, content:body, to_email:toEmail}});
        // Now enqueue
        var r = await api('/sequences/'+seqId+'/queue-email', {method:'POST'});
        if (r && r.success) { T('Added to send queue at '+(r.scheduled_at||'')); try{await loadEmail()}catch(e){} }
        else { T('Queue failed: ' + ((r&&r.error)||'Unknown'), '#dc2626'); }
      } catch(e) { T('Queue failed', '#dc2626'); }
      btn.disabled = false; btn.textContent = 'Schedule send';
    });
  });
  // Save to draft only (no scheduling)
  b.querySelectorAll('[data-draft-seq]').forEach(function(btn){
    btn.addEventListener('click', async function(){
      var seqId = parseInt(btn.dataset.draftSeq);
      btn.disabled = true; btn.textContent = 'Saving...';
      try {
        var row = btn.closest('.card') || btn.parentElement;
        var subjectEl = row ? row.querySelector('[data-field="subject"]') : null;
        var contentEl = row ? row.querySelector('[data-field="content"]') : null;
        var toEmailEl = row ? row.querySelector('[data-field="to_email"]') : null;
        var subj = subjectEl ? subjectEl.value : '';
        var body = contentEl ? contentEl.value : '';
        var toEmail = toEmailEl ? toEmailEl.value.trim() : '';
        await api('/sequences/'+seqId, {method:'PUT', body:{subject:subj, content:body, to_email:toEmail}});
        var sender = getSenderKey('email_sender') || 'primary';
        await authFetch('/api/email/queue',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({prospect_id:dp.id,to_email:toEmail||dp.email||dp.dm_email||'',subject:subj,body:body,status:'draft',sender_key:sender,sequence_id:seqId})});
        showDraftHint('Email added to drafts');
        try { await loadEmail(); } catch(e) {}
      } catch(e) { T('Save failed','#dc2626'); }
      btn.disabled = false; btn.textContent = 'Add to drafts';
    });
  });
  // AI Polish
  b.querySelectorAll('[data-polish-seq]').forEach(function(btn){
    btn.addEventListener('click', function(){
      var seqId = parseInt(btn.dataset.polishSeq);
      var txt = btn.dataset.polishTxt || '';
      var subj = btn.dataset.polishSubj || '';
      var inst = prompt('Enter polish instructions (e.g. "shorter"、"more professional"、"add trade show info"）：');
      if (!inst || !inst.trim()) return;
      btn.disabled = true; btn.textContent = 'Polishing...';
      (async function(){
        try {
          var body = {text: txt, instruction: inst.trim(), prospect_id: dp.id};
          var seqModel = getPanelModel('model_devplan');
          if (seqModel !== 'auto') body.model_override = seqModel;
          var r = await api('/ai/polish', {method:'POST', body: body});
          if (r && r.success) {
            // Update the textarea for this step
            var row = btn.closest('.card') || btn.parentElement;
            if (row) {
              var ta = row.querySelector('[data-field="content"]');
              if (ta && r.polished) ta.value = r.polished;
              if (r.subject) {
                var sj = row.querySelector('[data-field="subject"]');
                if (sj) sj.value = r.subject;
              }
            }
            T('Polished');
          } else {
            T('Polish failed: ' + ((r&&r.error)||'Unknown'), '#dc2626');
          }
        } catch(e) { T('Polish failed', '#dc2626'); }
        btn.disabled = false; btn.textContent = 'AI polish';
      })();
    });
  });

  // Suggest date button for active channel
  h += '<button class="btn btn-sm" style="background:#0891b2;color:#fff;font-size:11px;padding:4px 10px;margin-left:auto" id="suggestDateBtn" title="AI suggests the best send time by customer timezone">Smart date</button>';
  h += '</div>';

  // ── Active channel content ──
  var activeSteps = drSeqs.filter(function(s){ return s.channel===activeChannel; });
  var activeChDef = channels.find(function(c){ return c.id===activeChannel; });

  // Channel header
  h += '<div class="card p3 mb3" style="border-left:4px solid '+activeChDef.color+'">';
  h += '<p class="fwm" style="font-size:14px">'+activeChDef.icon+' '+activeChDef.label
    + (activeChDef.avail ? '' : ' <span style="color:#dc2626;font-size:11px"> (no contact info)</span>')+'</p>';

  if (!activeChDef.avail) {
    h += '<p style="font-size:11px;color:#dc2626;margin-top:4px">Add contact info in Basic info first: '+activeChDef.label+' details.</p>';
  } else if (activeSteps.length === 0) {
    h += '<p style="font-size:12px;color:#64748b;margin:8px 0">No outreach steps generated yet</p>';
    h += '<div class="flex aic g2" style="margin-top:8px">'+renderModelSelector('model_devplan','Model')+'<button class="btn genSeqBtn" style="background:'+activeChDef.color+';color:#fff;flex:1">'+activeChDef.icon+' Generate first '+activeChDef.label+' outreach</button></div>';
  } else {
    // Progress bar
    var doneCount = activeSteps.filter(function(s){ return s.status==='done'; }).length;
    var totalCount = activeSteps.length;
    h += '<div style="display:flex;align-items:center;gap:8px;margin-bottom:8px">';
    h += '<div style="flex:1;height:6px;background:#e5e7eb;border-radius:3px;overflow:hidden">';
    h += '<div style="width:'+(doneCount/totalCount*100)+'%;height:100%;background:'+activeChDef.color+';border-radius:3px"></div>';
    h += '</div>';
    h += '<span style="font-size:11px;color:#64748b;white-space:nowrap">'+doneCount+'/'+totalCount+'</span>';
    h += '</div>';

    // Steps list — compact: Step 几 + Contact + 期 + Status；Edit点开
    activeSteps.sort(function(a,b){
      function dateRank(s){ var d = String(s || '').substring(0,10); return d ? d : '9999-12-31'; }
      var da = dateRank(a.scheduled_date), db2 = dateRank(b.scheduled_date);
      if (da !== db2) return da < db2 ? -1 : 1;
      return (a.step_number || 0) - (b.step_number || 0);
    }).forEach(function(s){
      var bg = s.status==='done'?'#f0fdf4':s.status==='skipped'?'#f9fafb':s.status==='cancelled'?'#fef2f2':'#fff';
      var borderColor = s.status==='done'?'#10b981':s.status==='pending'?activeChDef.color:s.status==='cancelled'?'#ef4444':'#d1d5db';
      var who = stepWho(s);
      var stLabel = s.status==='done' ? 'Sent' : s.status==='pending' ? 'Not sent' : s.status==='skipped' ? 'Skipped' : s.status==='cancelled' ? 'Cancelled' : s.status;
      var stColor = s.status==='done' ? '#16a34a' : s.status==='pending' ? '#64748b' : s.status==='skipped' ? '#9ca3af' : s.status==='cancelled' ? '#dc2626' : '#64748b';
      var dateTxt = s.status==='done' ? (_localDate(s.executed_at) || String(s.scheduled_date||'').substring(0,10)) : (String(s.scheduled_date||'').substring(0,10) || 'Not scheduled');
      h += '<div class="card p3 mb2" style="opacity:'+(s.status==='skipped'||s.status==='cancelled'?'.55':'1')+';background:'+bg+';border-left:3px solid '+borderColor+';transition:all .15s">';
      if (s.status==='cancelled') {
        h += '<span style="font-size:11px;color:#dc2626;font-weight:600">Cancelled - replaced by smart follow-up</span><br>';
      }
      h += '<div style="display:flex;align-items:center;gap:10px;flex-wrap:wrap">';
  h += '<span style="font-size:13px;font-weight:700;color:'+activeChDef.color+'">Step '+s.step_number+'</span>';
      h += '<span style="font-size:12px;color:#334155;font-weight:600">'+E(who)+'</span>';
      h += '<span class="fs11 c6">'+E(dateTxt)+'</span>';
      h += '<span style="font-size:10px;font-weight:600;color:'+stColor+'">'+stLabel+'</span>';
      h += '<span style="margin-left:auto;display:flex;gap:4px;align-items:center">';
      if (s.status==='pending') {
        h += '<button class="btn btn-sm" style="background:#34d399;color:#fff;font-size:10px;padding:2px 10px" data-seq-done="'+s.id+'">Done</button>';
        h += '<button class="btn btn-sm" style="background:#9ca3af;color:#fff;font-size:10px;padding:2px 10px" data-seq-skip="'+s.id+'">Skip</button>';
      }
      h += '<button class="btn btn-sm" style="font-size:10px;padding:2px 10px" data-seq-edit="'+s.id+'">Collapse</button>';
      h += '<button class="btn btn-sm" style="background:#ef4444;color:#fff;font-size:10px;padding:2px 10px" data-seq-del="'+s.id+'">Delete</button>';
      h += '</span></div>';

      // Edit区：所有步骤默认展开，直接看/写内容
      h += '<div id="seqEdit'+s.id+'" style="display:block;margin-top:8px;border-top:1px dashed #e5e7eb;padding-top:8px">';
      if (s.status==='pending') {
        h += '<div style="margin-bottom:6px;display:flex;align-items:center;gap:6px"><span class="fs11 c6">Planned send</span><input type="date" value="'+(s.scheduled_date||'')+'" data-seq-id="'+s.id+'" data-field="scheduled_date" class="seqEd seqDate" style="font-size:11px;padding:2px 6px;width:140px;border:1px solid #d1d5db;border-radius:4px"></div>';
      }
      if (s.channel==='email') {
        h += '<input value="'+E(s.subject||'')+'" data-seq-id="'+s.id+'" data-field="subject" class="seqEd" placeholder="EmailSubject" style="font-size:13px;width:100%;margin-bottom:6px;padding:8px 10px;border:1px solid #e2e8f0;border-radius:6px">';
        h += '<input value="'+E(s.to_email||'')+'" data-seq-id="'+s.id+'" data-field="to_email" class="seqEd" placeholder="Recipient email (blank = this customer)" style="font-size:12px;width:100%;margin-bottom:6px;padding:6px 10px;border:1px solid #e2e8f0;border-radius:6px">';
      }
      var contentLabel = s.channel==='email' ? '✉️ Email content (editable)' : s.channel==='linkedin' ? '💼 LinkedIn content (editable)' : s.channel==='phone' ? '📞 Phone content (editable)' : '💬 Content (editable)';
      h += '<div style="font-size:11px;font-weight:600;color:#334155;margin-bottom:4px">'+contentLabel+'</div>';
      h += '<textarea data-seq-id="'+s.id+'" data-field="content" class="seqEd" rows="'+(s.channel==='email'?'8':'5')+'" style="font-size:13px;width:100%;padding:10px 12px;border:1px solid #e2e8f0;border-radius:6px;line-height:1.65;min-height:'+(s.channel==='email'?'190px':'120px')+';resize:vertical" placeholder="Message content">'+E(htmlToPlain(s.content||''))+'</textarea>';
      h += '<div style="display:flex;gap:4px;margin-top:6px;flex-wrap:wrap;align-items:center">';
      h += '<button class="btn btn-sm" style="font-size:10px;padding:2px 10px" data-save-seq="'+s.id+'">Save</button>';
      h += '<button class="btn btn-sm" style="background:#8b5cf6;color:#fff;font-size:10px;padding:2px 10px" data-polish-seq="'+s.id+'" data-polish-txt="'+E(htmlToPlain(s.content||'')).replace(/"/g,'&quot;')+'" data-polish-subj="'+E(s.subject||'').replace(/"/g,'&quot;')+'">AI polish</button>';
      if (s.channel==='email') {
        h += '<select data-sign-type="'+s.id+'" style="font-size:10px;padding:2px 6px;border:1px solid #cbd5e1;border-radius:4px;max-width:140px">'+signatureOptionsHtml(dp && dp.profile_type)+'</select>';
        h += '<button class="btn btn-sm" style="background:#6366f1;color:#fff;font-size:10px;padding:2px 10px" data-sign-seq="'+s.id+'">Insert signature</button>';
        h += '<button class="btn btn-sm" style="background:#9333ea;color:#fff;font-size:10px;padding:2px 10px" data-qc-seq="'+s.id+'">Quality check</button>';
        h += '<button class="btn btn-sm" style="background:#34d399;color:#fff;font-size:10px;padding:2px 10px" data-draft-seq="'+s.id+'">Add to drafts</button>';
        h += '<button class="btn btn-sm" style="background:#3b82f6;color:#fff;font-size:10px;padding:2px 10px" data-queue-seq="'+s.id+'">Schedule send</button>';
      } else {
        h += '<button class="btn btn-sm" style="background:#f59e0b;color:#fff;font-size:10px;padding:2px 10px" data-copy-seq="'+s.id+'" data-copy-txt="'+E(htmlToPlain(s.content||'')).replace(/"/g,'&quot;')+'">Copy</button>';
      }
      h += '</div>';
      h += '</div>';
      h += '</div>';
    });

    // Re-generate button
    h += '<div class="flex aic g2" style="margin-top:6px">'+renderModelSelector('model_devplan','Model')+'<button class="btn btn-sm genSeqBtn" style="background:#e5e7eb;color:#334155;font-size:10px;padding:2px 10px">🔄 Generate next '+activeChDef.label+' Follow-up</button></div>';
  }
  h += '</div>';

  // ── AI Chat panel ──
  h += '<div style="border:1px solid #c7d2fe;border-radius:8px;overflow:hidden;margin-top:12px">';
  h += '<div style="padding:10px 14px;background:#eef2ff;border-bottom:1px solid #c7d2fe;display:flex;justify-content:space-between;align-items:center"><span style="font-size:13px;font-weight:600;color:#4338ca">AI proactive analysis - '+activeChDef.label+'</span><div style="display:flex;gap:4px"><button class="btn btn-sm" style="background:#6366f1;color:#fff;font-size:10px" id="seqChatRefresh">Analyze again</button><button class="btn btn-sm" style="background:#e5e7eb;color:#334155;font-size:10px" id="seqChatClear">Clear</button></div></div>';
  h += '<div id="seqChatMsgs" style="max-height:420px;overflow-y:auto;padding:12px 16px;font-size:13px;min-height:60px;background:#fafbff;line-height:1.7">';
  if (_seqChatSaved) {
    h += _seqChatSaved;
  } else {
    h += '<div style="color:#64748b;text-align:center;padding:10px;font-size:11px">I know this customer profile, pain points and intelligence. Tell me your thoughts and I will help with the '+activeChDef.label+' cold-outreach strategy.</div>';
  }
  h += '</div>';
  h += '<div style="display:flex;padding:6px 10px;gap:6px;border-top:1px solid #e5e7eb;background:#fff">';
  h += '<input id="seqChatInput" placeholder="Revise copy / ask for strategy..." style="flex:1;font-size:12px;padding:6px 10px;border-radius:6px">';
  h += '<button class="btn btn-sm" style="background:#6366f1;white-space:nowrap" id="seqChatSend">Send</button>';
  h += renderModelSelector('model_devplan');
  h += '</div></div>';

  b.innerHTML = h;

  // ── Bindings ──

  // Channel tab clicks
  b.querySelectorAll('.seqChTab').forEach(function(btn){
    btn.addEventListener('click', function(){
      window._seqActiveCh = btn.dataset.seqCh;
      renderDrawer(); // re-render with new active channel
    });
  });

  // Generate for active channel — use class selector to cover both buttons
  async function genSeqForChannel(channel) {
    var btns = b.querySelectorAll('.genSeqBtn');
    btns.forEach(function(bb){ bb.disabled = true; bb.textContent = 'AI analyzing...'; });
    try {
      var r = await api('/ai/suggest-sequence/' + dp.id, {method: 'POST', body: {channel: channel, model_override: getPanelModel('model_devplan')}});
      if (r && r.success) {
        T('Generated step ' + r.step_number + ': ' + channel, '#16a34a', 4000);
        try { drSeqs = await api('/sequences/' + dp.id); } catch(e) {}
        renderDrawer();
      } else {
        T('Generation failed: ' + ((r && r.error) || 'Unknown error'), '#dc2626', 5000);
      }
    } catch(e) {
      T('Request failed: ' + (e.detail || e.message || 'Network error'), '#dc2626', 4000);
    }
    btns.forEach(function(bb){ bb.disabled = false; bb.textContent = activeChDef.icon + ' Generate next step ' + activeChDef.label + ' Follow-up'; });
  }

  b.querySelectorAll('.genSeqBtn').forEach(function(btn){
    btn.addEventListener('click', function(){ genSeqForChannel(activeChannel); });
  });

  // AI 智能Development Plan：整家公司按决策链Generate完整流程
  var smartBtn = b.querySelector('#smartPlanBtn');
  if (smartBtn) {
    smartBtn.addEventListener('click', async function(){
      smartBtn.disabled = true; smartBtn.textContent = 'AI analyzing...';
      try {
        var body = {model_override: getPanelModel('model_devplan')};
        var r = await api('/ai/suggest-company-sequence/' + dp.id, {method:'POST', body: body});
        if (r && r.success) {
          T('Generated ' + (r.count || (r.created && r.created.length) || 0) + ' smart plan steps', '#7c3aed', 5000);
          var mainTarget = r.main_prospect_id && r.main_prospect_id !== dp.id ? r.main_prospect_id : null;
          if (!mainTarget) {
            try {
              var cr = await api('/prospects/' + dp.id + '/colleagues');
              var main = companyMainOf([dp].concat((cr && cr.colleagues) || []));
              if (main && main.id !== dp.id) mainTarget = main.id;
            } catch(e){}
          }
          if (mainTarget) {
            await openDrawer(mainTarget);
            dtab = 'sequence';
            renderDrawer();
          } else {
            try { drSeqs = await api('/sequences/' + dp.id); } catch(e){}
            renderDrawer();
          }
        } else {
          T('Generation failed: ' + ((r && r.error) || 'Unknown error'), '#dc2626', 6000);
        }
      } catch(e) {
        T('Request failed: ' + (e.detail || e.message || 'Network error'), '#dc2626', 4000);
      }
      smartBtn.disabled = false; smartBtn.textContent = 'Generate smart outreach plan';
    });
  }

  // 步骤Edit展开/Collapse
  b.querySelectorAll('[data-seq-edit]').forEach(function(btn){
    btn.addEventListener('click', function(){
      var id = parseInt(btn.dataset.seqEdit);
      var box = document.getElementById('seqEdit'+id);
      if (!box) return;
      var show = box.style.display === 'none';
      box.style.display = show ? 'block' : 'none';
      btn.textContent = show ? 'Collapse' : 'Edit';
    });
  });

  // 打开的是Contact而非公司主记录时，提示计划在主记录上
  var mainHint = document.getElementById('mainPlanHint');
  if (mainHint) {
    (async function(){
      try {
        var cr = await api('/prospects/'+dp.id+'/colleagues');
        var all = [dp].concat((cr && cr.colleagues) || []);
        var main = companyMainOf(all);
        if (main && main.id !== dp.id) {
          mainHint.innerHTML = '<div class="card p2" style="background:#f5f3ff;border:1px solid #ddd6fe;font-size:12px;color:#6d28d9;display:flex;align-items:center;gap:8px;flex-wrap:wrap">Company-level plan is on the main record #'+main.id+'（'+E(main.contact||main.company||'')+'）.<button class="btn btn-sm" style="background:#7c3aed;color:#fff" id="openMainPlanBtn">Open main record</button></div>';
          var btn = document.getElementById('openMainPlanBtn');
          if (btn) btn.onclick = function(){ openDrawer(main.id); };
        }
      } catch(e){}
    })();
  }

  // ═══ AI CHAT for Development Plan ═══
  var seqCs = b.querySelector('#seqChatSend');
  var seqCi = b.querySelector('#seqChatInput');
  if (seqCs && seqCi) {
    seqCs.onclick = async function() {
      var msg = seqCi.value.trim(); if (!msg) return;
      var md = b.querySelector('#seqChatMsgs');
      md.innerHTML += '<div style="background:#f1f5f9;padding:6px 10px;border-radius:6px;font-size:11px;margin-top:6px"><b>You:</b> '+E(msg)+'</div>';
      seqCi.value = '';
      var ld = document.createElement('div'); ld.style.cssText='color:#6366f1;font-size:11px;margin-top:4px'; ld.textContent='⏳ ...'; md.appendChild(ld);
      try {
        var seqModel = getPanelModel('model_devplan');
        var body2 = {prompt:msg, prospect_id:dp.id, voice:'human'};
        if (seqModel !== 'auto') body2.model_override = seqModel;
        var res2 = await api('/ai/chat', {method:'POST', body:body2});
        ld.remove();
        if (res2 && res2.success) { md.innerHTML += '<div style="background:#eef2ff;padding:8px 12px;border-radius:6px;font-size:12px;margin-top:6px;line-height:1.6"><b style="color:#4338ca">AI:</b><br>'+E(res2.reply||res2.result||'').replace(/\n/g,'<br>')+'</div>'; md.scrollTop=md.scrollHeight; }
      } catch(e) { ld.remove(); md.innerHTML += '<div style="color:#dc2626;font-size:11px;margin-top:4px">Send failed</div>'; }
    };
    seqCi.addEventListener('keydown', function(e) { if (e.key==='Enter') { e.preventDefault(); seqCs.click(); } });
  }
  // Refresh button
  var seqRefresh = b.querySelector('#seqChatRefresh');
  var seqClear = b.querySelector('#seqChatClear');
  var seqMd = b.querySelector('#seqChatMsgs');
  if (seqRefresh && seqMd) {
    seqRefresh.onclick = async function() {
      seqMd.innerHTML = '<div style="color:#6366f1;font-size:11px;text-align:center;padding:10px">⏳ Re-analyzing...</div>';
      try {
        var seqModelR = getPanelModel('model_devplan');
        var profileInfo = (dp.profile_summary||'') + ' ' + (dp.profile_type||'') + ' ' + (dp.pain_points||'') + ' ' + (dp.profile_refined||'');
        var interactionsSummary = (drInts||[]).map(function(i){return (i.direction==='inbound'?'Customer':'Outbound')+': '+ (i.content||'').substring(0,300);}).join('\n').substring(0,3000);
        var bodyR = {prompt:'Customer: '+E(dp.company)+' | '+E(dp.country)+' | Profile '+E(dp.profile_type)+'\nProfile: '+profileInfo.substring(0,800)+'\n\nInteraction history:\n'+interactionsSummary+'\n\nAnalyze: 1) current outreach pace and stage 2) recommended next action (email follow-up / proposal quote / channel switch / other) 3) a draft message if suitable. Reply in English with points 1,2,3.', prospect_id: dp.id, voice: 'human'};
        if (seqModelR !== 'auto') bodyR.model_override = seqModelR;
        var resR = await api('/ai/chat', {method:'POST', body: bodyR});
        if (resR && resR.success) {
          seqMd.innerHTML = '<div style="background:#eef2ff;padding:10px 14px;border-radius:6px;font-size:13px;line-height:1.7"><b style="color:#4338ca">AI analysis:</b><br><br>'+E(resR.reply||resR.result||'').replace(/\n/g,'<br>')+'</div>';
        }
      } catch(e) { seqMd.innerHTML = '<div style="color:#dc2626;text-align:center">Analysis failed: '+(e.detail||e.message||'')+'</div>'; }
    };
  }
  if (seqClear && seqMd) {
    seqClear.onclick = function(){
      _seqChatSaved = '';
      seqMd.innerHTML = '<div style="color:#64748b;text-align:center;padding:10px;font-size:11px">I know this customer profile, pain points and intelligence. Tell me your thoughts and I will help with the '+activeChDef.label+' cold-outreach strategy.</div>';
    };
  }

  // ═══ Sequence step action buttons ═══
  // Done / Skip
  b.querySelectorAll('[data-seq-done]').forEach(function(btn){
    btn.addEventListener('click', async function(){
      var seqId = parseInt(btn.dataset.seqDone);
      btn.disabled = true; btn.textContent = '...';
      try {
        await execStep(seqId, 'done');
      } catch(e) { T('Operation failed', '#dc2626'); btn.disabled = false; btn.textContent = 'Done'; }
    });
  });
  b.querySelectorAll('[data-seq-skip]').forEach(function(btn){
    btn.addEventListener('click', async function(){
      var seqId = parseInt(btn.dataset.seqSkip);
      btn.disabled = true; btn.textContent = '...';
      try {
        await execStep(seqId, 'skipped');
      } catch(e) { T('Operation failed', '#dc2626'); btn.disabled = false; btn.textContent = 'Skip'; }
    });
  });
  // Auto-save on blur: when user finishes editing subject or content, save to backend
  b.querySelectorAll('[data-seq-id][data-field]').forEach(function(el){
    el.addEventListener('blur', async function(){
      var seqId = parseInt(el.dataset.seqId);
      var row = el.closest('.card') || el.parentElement;
      var subjectEl = row ? row.querySelector('[data-field="subject"]') : null;
      var contentEl = row ? row.querySelector('[data-field="content"]') : null;
      var toEmailEl = row ? row.querySelector('[data-field="to_email"]') : null;
      var subj = subjectEl ? subjectEl.value : '';
      var body = contentEl ? contentEl.value : '';
      var toEmail = toEmailEl ? toEmailEl.value.trim() : '';
      try {
        await api('/sequences/'+seqId, {method:'PUT', body:{subject:subj, content:body, to_email:toEmail}});
      } catch(e) { /* silent */ }
    });
  });
  // Save — saves to Sequence with auto next-follow-date, and creates draft in EmailQueue (email only)
  b.querySelectorAll('[data-save-seq]').forEach(function(btn){
    btn.addEventListener('click', async function(){
      var seqId = parseInt(btn.dataset.saveSeq);
      var row = btn.closest('.card') || btn.parentElement;
      var subjectEl = row ? row.querySelector('[data-field="subject"]') : null;
      var contentEl = row ? row.querySelector('[data-field="content"]') : null;
      var scheduleEl = row ? row.querySelector('.seqDate') : null;
      var toEmailEl = row ? row.querySelector('[data-field="to_email"]') : null;
      var subject = subjectEl ? subjectEl.value : '';
      var content = contentEl ? contentEl.value : '';
      var schedDate = scheduleEl ? scheduleEl.value : '';
      var toEmail = toEmailEl ? toEmailEl.value.trim() : '';
      btn.disabled = true;
      try {
        // Save to Sequence (backend auto-calculates next_follow_date)
        var putBody = {subject: subject, content: content};
        putBody.to_email = toEmail;
        if (schedDate) putBody.scheduled_date = schedDate;
        await api('/sequences/'+seqId, {method:'PUT', body: putBody});
        // Refresh prospect data to see the new next_follow_date
        try { var fresh = await api('/prospects/'+dp.id); if (fresh) dp = fresh; } catch(e) {}
        // For email steps only: create an email draft
        var seqData = drSeqs.find(function(x){ return x.id === seqId; });
        var isEmail = seqData && seqData.channel === 'email';
        if (isEmail && (toEmail || dp.email || dp.dm_email)) {
          try {
            await api('/email/queue', {method:'POST', body:{
              prospect_id: dp.id, sequence_id: seqId,
              to_email: toEmail || dp.email || dp.dm_email || '',
              subject: subject, body: content, status: 'draft',
              sender_key: getSenderKey('email_sender')
            }});
            T('Saved · email draft synced; next follow-up '+(dp.next_follow_date ? dp.next_follow_date : 'not set'));
            try { await loadEmail(); } catch(e) {}
          } catch(e2) { T('Saved · Next follow-up '+(dp.next_follow_date ? dp.next_follow_date : 'not set')); }
        } else {
          T('Saved · Next follow-up '+(dp.next_follow_date ? dp.next_follow_date : 'not set'));
        }
      } catch(e) { T('Save failed', '#dc2626'); }
      btn.disabled = false;
    });
  });
  // Delete — also removes linked email drafts from Email管理
  b.querySelectorAll('[data-seq-del]').forEach(function(btn){
    btn.addEventListener('click', async function(){
      var seqId = parseInt(btn.dataset.seqDel);
      if (!confirm('Delete step '+seqId+'? The linked email draft will also be deleted.')) return;
      btn.disabled = true;
      try {
        await api('/sequences/'+seqId+'/delete', {method:'POST'});
        drSeqs = await api('/sequences/'+dp.id);
        try { await loadEmail(); } catch(e) {}
        renderDrawer();
        T('Deleted');
      } catch(e) { T('Delete failed', '#dc2626'); }
      btn.disabled = false;
    });
  });
  // Copy
  b.querySelectorAll('[data-copy-seq]').forEach(function(btn){
    btn.addEventListener('click', async function(){
      var txt = btn.dataset.copyTxt || '';
      try { await navigator.clipboard.writeText(txt); T('Copied'); } catch(e) { T('Copy failed', '#dc2626'); }
    });
  });
  // Insert signature
  b.querySelectorAll('[data-sign-seq]').forEach(function(btn){
    btn.addEventListener('click', function(){
      var seqId = parseInt(btn.dataset.signSeq);
      var row = btn.closest('.card') || btn.parentElement;
      if (!row) return;
      var sel = row.querySelector('[data-sign-type]');
      var sigVal = sel ? sel.value : 'AUTO';
      var sig = resolveSelectedSignature(sigVal, dp && dp.profile_type);
      if (!sig) { T('No signature available'); return; }
      var ta = row.querySelector('[data-field="content"]');
      if (!ta) return;
      ta.value = (ta.value || '').trim() + '\n\n' + sig;
      T('Signature inserted');
    });
  });
  // Queue email — read latest from textarea, save to Sequence first, then enqueue
  b.querySelectorAll('[data-queue-seq]').forEach(function(btn){
    btn.addEventListener('click', async function(){
      var seqId = parseInt(btn.dataset.queueSeq);
      btn.disabled = true; btn.textContent = 'Queuing...';
      try {
        // Read current values from the textareas in case user edited inline
        var row = btn.closest('.card') || btn.parentElement;
        var subjectEl = row ? row.querySelector('[data-field="subject"]') : null;
        var contentEl = row ? row.querySelector('[data-field="content"]') : null;
        var toEmailEl = row ? row.querySelector('[data-field="to_email"]') : null;
        var subj = subjectEl ? subjectEl.value : '';
        var body = contentEl ? contentEl.value : '';
        var toEmail = toEmailEl ? toEmailEl.value.trim() : '';
        // Save to Sequence first so the backend reads the latest version
        await api('/sequences/'+seqId, {method:'PUT', body:{subject:subj, content:body, to_email:toEmail}});
        // Now enqueue
        var r = await api('/sequences/'+seqId+'/queue-email', {method:'POST'});
        if (r && r.success) { T('Added to send queue at '+(r.scheduled_at||'')); try{await loadEmail()}catch(e){} }
        else { T('Queue failed: ' + ((r&&r.error)||'Unknown'), '#dc2626'); }
      } catch(e) { T('Queue failed', '#dc2626'); }
      btn.disabled = false; btn.textContent = 'Schedule send';
    });
  });
  // Save to draft only (no scheduling)
  b.querySelectorAll('[data-draft-seq]').forEach(function(btn){
    btn.addEventListener('click', async function(){
      var seqId = parseInt(btn.dataset.draftSeq);
      btn.disabled = true; btn.textContent = 'Saving...';
      try {
        var row = btn.closest('.card') || btn.parentElement;
        var subjectEl = row ? row.querySelector('[data-field="subject"]') : null;
        var contentEl = row ? row.querySelector('[data-field="content"]') : null;
        var toEmailEl = row ? row.querySelector('[data-field="to_email"]') : null;
        var subj = subjectEl ? subjectEl.value : '';
        var body = contentEl ? contentEl.value : '';
        var toEmail = toEmailEl ? toEmailEl.value.trim() : '';
        await api('/sequences/'+seqId, {method:'PUT', body:{subject:subj, content:body, to_email:toEmail}});
        var sender = getSenderKey('email_sender') || 'primary';
        await authFetch('/api/email/queue',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({prospect_id:dp.id,to_email:toEmail||dp.email||dp.dm_email||'',subject:subj,body:body,status:'draft',sender_key:sender,sequence_id:seqId})});
        showDraftHint('Email added to drafts');
        try { await loadEmail(); } catch(e) {}
      } catch(e) { T('Save failed','#dc2626'); }
      btn.disabled = false; btn.textContent = 'Add to drafts';
    });
  });
  // AI Polish
  b.querySelectorAll('[data-polish-seq]').forEach(function(btn){
    btn.addEventListener('click', function(){
      var seqId = parseInt(btn.dataset.polishSeq);
      var txt = btn.dataset.polishTxt || '';
      var subj = btn.dataset.polishSubj || '';
      var inst = prompt('Enter polish instructions (e.g. "shorter"、"more professional"、"add trade show info"）：');
      if (!inst || !inst.trim()) return;
      btn.disabled = true; btn.textContent = 'Polishing...';
      (async function(){
        try {
          var body = {text: txt, instruction: inst.trim(), prospect_id: dp.id};
          var seqModel = getPanelModel('model_devplan');
          if (seqModel !== 'auto') body.model_override = seqModel;
          var r = await api('/ai/polish', {method:'POST', body: body});
          if (r && r.success) {
            // Update the textarea for this step
            var row = btn.closest('.card') || btn.parentElement;
            if (row) {
              var ta = row.querySelector('[data-field="content"]');
              if (ta && r.polished) ta.value = r.polished;
              if (r.subject) {
                var sj = row.querySelector('[data-field="subject"]');
                if (sj) sj.value = r.subject;
              }
            }
            T('Polished');
          } else {
            T('Polish failed: ' + ((r&&r.error)||'Unknown'), '#dc2626');
          }
        } catch(e) { T('Polish failed', '#dc2626'); }
        btn.disabled = false; btn.textContent = 'AI polish';
      })();
    });
  });

  // Suggest date button
  bindSafe(b, '#suggestDateBtn', 'click', async function(){
      var btn = b.querySelector('#suggestDateBtn');
      btn.disabled = true;
      btn.textContent = 'Analyzing...';
      try{
        var res = await api('/prospects/'+dp.id+'/suggest-date', {method:'POST'});
        if (res && res.suggested_date) {
          var steps = drSeqs.filter(function(s){ return s.channel===activeChannel && s.status==='pending'; });
          if (steps.length) {
            await api('/sequences/'+steps[0].id, {method:'PUT', body:{scheduled_date:res.suggested_date}});
            drSeqs = await api('/sequences/'+dp.id);
            renderDrawer();
            T('Suggested date: '+res.suggested_date+' | '+res.reason, '#0891b2');
          } else {
            T('Suggested date: '+res.suggested_date+' | '+res.reason, '#0891b2');
          }
        }
      }catch(e){}
      btn.disabled = false;
      btn.textContent = 'Smart date';
    });
}

// ── Helpers ──
async function execStep(seqId, action) {
  var body = action==='sent' ? {status:'done'} : {status:action};
  try {
    if (action==='sent') {
      var s = drSeqs.find(function(x){ return x.id===seqId; });
      if (s && s.content) {
        await api('/interactions',{method:'POST',body:{prospect_id:dp.id,direction:'outbound',channel:s.channel,content:s.content,subject:s.subject||''}});
      }
    }
    await api('/sequences/'+seqId+'/execute',{method:'POST',body:body});

    if (action==='sent') {
      try {
        var seq = drSeqs.find(function(x){ return x.id===seqId; });
        await api('/interactions',{method:'POST',body:{prospect_id:dp.id,direction:'outbound',channel:seq.channel,content:seq.content,subject:seq.subject||''}});
      } catch(e){}
    }

    drSeqs = await api('/sequences/'+dp.id);
    try { var fresh = await api('/prospects/'+dp.id); if (fresh) dp = fresh; } catch(e) {}
    renderDrawer();
    T(action==='sent' ? 'Marked as sent' : 'Updated');
  } catch(e) { T('Operation failed', '#dc2626'); }
}

async function deleteStep(seqId) {
  if (!confirm('Delete this step?')) return;
  try {
    await api('/sequences/'+seqId, {method:'DELETE'});
    drSeqs = await api('/sequences/'+dp.id);
    renderDrawer();
    T('Deleted');
  } catch(e) { T('Delete failed', '#dc2626'); }
}

async function addCustomStep() {
  var channel = prompt('Channel (email/linkedin/whatsapp/wechat/phone):', activeChannel||'email');
  if (!channel) return;
  var content = prompt('Content:');
  if (!content) return;
  var toEmail = '';
  if (channel === 'email') toEmail = prompt('Recipient email (blank = this customer):', '') || '';
  var date = prompt('Date (YYYY-MM-DD):', new Date().toISOString().substring(0,10));
  try {
    await api('/sequences',{method:'POST',body:{prospect_id:dp.id,channel:channel,step_number:drSeqs.length+1,content:content,scheduled_date:date,to_email:toEmail}});
    drSeqs = await api('/sequences/'+dp.id);
    renderDrawer();
    T('Added');
  } catch(e) { T('Add failed', '#dc2626'); }
}

// ── Event Bindings ──
function bindSafe(container, selector, event, handler) {
  try {
    var el = typeof selector === 'string' ? container.querySelector(selector) : selector;
    if (el) el.addEventListener(event, handler);
  } catch(e) { console.error('bindSafe error:', selector, e); }
}
