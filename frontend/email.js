// ── Multi-model quality check (DeepSeek + Gemini) ──
window.runQualityCheck = async function(subject, body, pid){
  var text = String(body||'').replace(/<[^>]+>/g,'').trim();
  if (!text) { T('Please write the email body first','#dc2626'); return; }
  T('Quality check in progress...','#7c3aed');
  try {
    var res = await api('/ai/quality-check', {method:'POST', body:{subject: subject||'', body: text, prospect_id: pid||0}});
    showQcModal(res);
  } catch(e) { T('Quality check failed: '+(e.detail||e.message||''),'#dc2626'); }
};

// Send前拦截的可视化Status: Draft/待发列表直接显示开头是否合规
window.emailOpeningWarning = function(e){
  if (!e || !e.subject || /^(re:|aw:|fw:|fwd:)/i.test(e.subject)) return '';
  var body = String(e.body || '');
  var text = body
    .replace(/<br\s*\/?>/gi, '\n')
    .replace(/<\/?(p|div|tr|li)>/gi, '\n')
    .replace(/<[^>]+>/g, ' ')
    .replace(/&nbsp;/g, ' ');
  var paras = text.split(/\n\s*\n/).map(function(x){ return x.trim(); }).filter(Boolean);
  for (var i = 0; i < paras.length; i++) {
    var para = paras[i];
    if (/^(hi|hello|hey|dear|good (morning|afternoon|evening))\b/i.test(para) && para.length <= 80) continue;
    var m = para.match(/[^.!?]+[.!?]+/);
    var first = (m && m[0]) ? m[0].trim() : para;
    if (/(?:I am .* from|I'm .* from|I work with|We manufacture|We specialize|Our company|Our core competency|I am reaching out|I wanted to introduce|We('ve| have) been supplying|I handle international trade|I run a workshop)/i.test(first)) {
      return 'First cold email opens with self-introduction';
    }
    break;
  }
  return '';
};

// 开发计划步骤的「质检」按钮：一次性事件委托，页面里所有 [data-qc-seq] 按钮共用
if (!window._qcSeqDelegated) {
  window._qcSeqDelegated = true;
  document.addEventListener('click', function(e){
    var btn = e.target && e.target.closest ? e.target.closest('[data-qc-seq]') : null;
    if (!btn) return;
    var row = btn.closest('.card') || btn.parentElement;
    var subjectEl = row ? row.querySelector('[data-field="subject"]') : null;
    var contentEl = row ? row.querySelector('[data-field="content"]') : null;
    window.runQualityCheck(subjectEl ? subjectEl.value : '', contentEl ? contentEl.value : '', (typeof dp !== 'undefined' && dp) ? dp.id : 0);
  });
}

function showQcModal(res){
  var old = document.getElementById('qcModalMsk');
  if (old) old.remove();
  var avg = res.average;
  var passed = res.pass;
  var avgColor = avg==null ? '#94a3b8' : avg>=70 ? '#16a34a' : avg>=50 ? '#f59e0b' : '#dc2626';
  var h = '<div id="qcModalMsk" style="position:fixed;inset:0;background:rgba(15,23,42,.55);z-index:9999;display:flex;align-items:flex-start;justify-content:center;padding:40px 16px;overflow-y:auto">';
  h += '<div style="background:#fff;border-radius:14px;max-width:720px;width:100%;padding:22px 24px;box-shadow:0 20px 60px rgba(0,0,0,.25)">';
  h += '<div class="flex aic mb3"><div><p class="fs16 fwb" style="color:#0f172a">Multi-model quality check</p><p class="fs12 c6">Scores are for reference; your review decides</p></div><div style="margin-left:auto;text-align:right"><span class="fs28 fwb" style="color:'+avgColor+'">'+(avg==null?'-':avg)+'</span><span class="fs13 c6">/100</span><div class="fs12" style="color:'+(passed?'#16a34a':'#f59e0b')+'">'+(avg==null?'No valid score':(passed?'Passed (>= '+res.threshold+'）':'⚠️ Suggest revising before sending'))+'</div></div></div>';
  (res.results||[]).forEach(function(r){
    var sc = r.score;
    var scC = sc==null ? '#94a3b8' : sc>=70 ? '#16a34a' : sc>=50 ? '#f59e0b' : '#dc2626';
    var vMap = {pass:'Pass', revise:'Revise & send', rewrite:'Rewrite', error:'Error', unknown:'Unknown'};
    h += '<div style="border:1px solid #e2e8f0;border-radius:10px;padding:14px 16px;margin-bottom:12px">';
    h += '<div class="flex aic mb2"><b style="color:#0f172a">'+E(r.model_label||r.model)+'</b>';
    if (r.verdict) h += '<span class="badge" style="background:'+(r.verdict==='pass'?'#dcfce7;color:#166534':r.verdict==='revise'?'#fef9c3;color:#854d0e':'#fee2e2;color:#991b1b')+'">'+(vMap[r.verdict]||r.verdict)+'</span>';
    h += '<span style="margin-left:auto;font-size:20px;font-weight:700;color:'+scC+'">'+(sc==null?'-':sc)+'</span></div>';
    if (r.error) { h += '<p class="fs12" style="color:#dc2626">'+E(r.error)+'</p>'; }
    if (r.red_flags && r.red_flags.length) { h += '<p class="fs12 fwm mb1" style="color:#991b1b">Red flags / risks</p><ul style="margin:0 0 8px;padding-left:18px;font-size:12px;color:#991b1b">'+r.red_flags.map(function(x){return '<li>'+E(x)+'</li>'}).join('')+'</ul>'; }
    if (r.strengths && r.strengths.length) { h += '<p class="fs12 fwm mb1" style="color:#166534">Strengths</p><ul style="margin:0 0 8px;padding-left:18px;font-size:12px;color:#334155">'+r.strengths.map(function(x){return '<li>'+E(x)+'</li>'}).join('')+'</ul>'; }
    if (r.suggestions && r.suggestions.length) { h += '<p class="fs12 fwm mb1" style="color:#b45309">Suggestions</p><ul style="margin:0;padding-left:18px;font-size:12px;color:#334155">'+r.suggestions.map(function(x){return '<li>'+E(x)+'</li>'}).join('')+'</ul>'; }
    h += '</div>';
  });
  h += '<div style="text-align:right"><button class="btn" id="qcCloseBtn" style="background:#6366f1;color:#fff">Close</button></div>';
  h += '</div></div>';
  document.body.insertAdjacentHTML('beforeend', h);
  document.getElementById('qcModalMsk').onclick = function(e){ if(e.target===document.getElementById('qcModalMsk')) document.getElementById('qcModalMsk').remove(); };
  document.getElementById('qcCloseBtn').onclick = function(){ document.getElementById('qcModalMsk').remove(); };
}

async function loadEmail(){
  _emailLoaded=true;
  try{eqData=await api('/email/queue')}catch(e){eqData=[]}
  try{
    var es=await api('/email/stats/today');
    stats={sent:es.sent_count||0,limit:es.limit_count||10,remaining:(es.limit_count-es.sent_count)||0};
  }catch(e){
    stats={sent:0,limit:10,remaining:10};
  }
  // ── Email performance data ──
  try{emailPerf=await api('/email/stats/performance')}catch(e){emailPerf=null}
  if(emailFilter==='inbox'){
    try{
      var inboxQ = encodeURIComponent((window._inboxSearchTerm||'').trim());
      var r=await api('/interactions/inbox?limit=200'+(inboxQ?'&q='+inboxQ:''));
      eqInbox=Array.isArray(r)?r:[];
    }catch(e){eqInbox=[]}
  }

  cdTargets=[];
  if(emailFilter==='queue'){
    (eqData||[]).filter(function(e){return e.status==='pending'}).forEach(function(e){
      if(e.scheduled_at){cdTargets.push({id:e.id,ts:new Date(e.scheduled_at+'Z'),to:e.to_email,subj:e.subject})}
    });
  }
  render();
}

function renderEmailTables(){
  // Re-render email tables with current search filter — without re-fetching from API.
  // REmail() reads window._emailSearchTerm and filters the already-loaded arrays inline.
  var p = document.getElementById('mainPane');
  REmail(p);
}

var cdTargets=[];
var cdInterval=null;

function emailStatusText(status){
  var map={draft:'Draft',pending:'Pending',sending:'Sending',sent:'Sent',cancelled:'Cancelled',failed:'Failed'};
  return map[status]||status||'-';
}

function inboxPriority(i){
  var intent=(i.reply_intent||'').toUpperCase();
  if(intent==='Bounced')return 99;
  var hasProspect=(i.prospect_id&&i.prospect_id>0);
  var unread=(!i.is_read||i.is_read===0);
  // Hot/inquiry/sample always first
  if(intent==='HOT_LEAD'||intent==='INFORMATION_REQUEST'||intent==='SAMPLE')return 0;
  // Explicit positive engagement signals next
  if(intent==='POSITIVE_ENGAGEMENT'||intent==='MEETING'||intent==='QUOTE_REQUEST')return 1;
  // All unread emails before all read emails
  if(unread)return 2;
  // Read + matched
  if(hasProspect)return 3;
  // Read + unmatched
  return 4;
}

function inboxPriorityLabel(i){
  var intent=(i.reply_intent||'').toUpperCase();
  if(intent==='Bounced')return{label:'Bounced',color:'#9ca3af',bg:'#f9fafb'};
  if(intent==='HOT_LEAD')return{label:'Hot',color:'#dc2626',bg:'#fef2f2'};
  if(intent==='INFORMATION_REQUEST')return{label:'Inquiry',color:'#2563eb',bg:'#eff6ff'};
  if(intent==='SAMPLE'||intent==='SAMPLE_ADDRESS')return{label:'Sample',color:'#7c3aed',bg:'#f5f3ff'};
  if(intent==='POSITIVE_ENGAGEMENT')return{label:'Positive',color:'#16a34a',bg:'#f0fdf6'};
  if(intent==='MEETING')return{label:'Meeting',color:'#d97706',bg:'#fffbeb'};
  if(intent==='QUOTE_REQUEST')return{label:'Quote',color:'#ea580c',bg:'#fff7ed'};
  var unread=(!i.is_read||i.is_read===0);
  if(unread)return{label:'Unread',color:'#6366f1',bg:'#f0f0ff'};
  return{label:'Read',color:'#64748b',bg:'#f8fafc'};
}

function inboxIntentText(intent){
  var map={'HOT_LEAD':'Hot','INFORMATION_REQUEST':'Inquiry','SAMPLE':'Sample','SAMPLE_ADDRESS':'Shipping address','POSITIVE_ENGAGEMENT':'Positive reply','MEETING':'Meeting','Bounced':'Bounced','QUOTE_REQUEST':'Quote','NEGATIVE':'Rejected','OTHER':'Other'};
  return map[intent]||intent||'-';
}

function updateInboxBatchBar(){
  var cbs = document.querySelectorAll('.inbox-cb:checked');
  var bar = document.getElementById('inboxBatchBar');
  if(!bar)return;
  var count=cbs.length;
  bar.style.display=count>0?'flex':'none';
  var sel=document.getElementById('batchSelectedCount');
  if(sel)sel.textContent='Selected '+count+'  emails';
}

function clearInboxSelection(){
  document.querySelectorAll('.inbox-cb').forEach(function(cb){cb.checked=false;});
  updateInboxBatchBar();
}

async function batchMarkInbox(isRead){
  var cbs = document.querySelectorAll('.inbox-cb:checked');
  var ids=[];
  cbs.forEach(function(cb){ids.push(parseInt(cb.dataset.inboxId));});
  if(!ids.length){T('Select emails first');return;}
  try{
    await api('/interactions/inbox/batch-read',{method:'PUT',body:{ids:ids,is_read:isRead}});
    T('Updated'+ids.length+' emails');
    await loadEmail();
  }catch(e){T('Update failed','#dc2626');}
}

var TZ_OFFSETS = {
  'UTC8': 8, 'Asia/Shanghai': 8, 'Asia/Taipei': 8, 'Asia/Hong_Kong': 8, 'Asia/Singapore': 8,
  'UTC0': 0, 'Europe/London': 0, 'Europe/Berlin': 1, 'Europe/Paris': 1, 'Europe/Madrid': 1,
  'Europe/Rome': 1, 'Europe/Amsterdam': 1, 'Europe/Zurich': 1, 'Europe/Stockholm': 1,
  'UTC-5': -5, 'America/New_York': -5, 'America/Chicago': -6, 'America/Denver': -7, 'America/Los_Angeles': -8,
  'UTC+5:30': 5.5, 'Asia/Kolkata': 5.5, 'UTC3': 3, 'Asia/Dubai': 4,
  'UTC-3': -3, 'America/Sao_Paulo': -3, 'UTC+2': 2, 'UTC+1': 1,
};

function tzOffset(tz) {
  if (!tz) return null;
  if (TZ_OFFSETS[tz] !== undefined) return TZ_OFFSETS[tz];
  var m = tz.match(/UTC([+-]?\d+)(?::?(\d+))?/i);
  if (m) return parseFloat(m[1]) + (m[2] ? parseInt(m[2]) / 60 : 0);
  return null;
}

function fmtTime(utcStr, offsetHours) {
  if (!utcStr || offsetHours === null || offsetHours === undefined) return utcStr ? utcStr.substring(0, 16).replace('T', ' ') : '-';
  var d = new Date(String(utcStr) + 'Z');
  if (isNaN(d.getTime())) return utcStr;
  var totalMin = d.getUTCHours() * 60 + d.getUTCMinutes() + Math.round(offsetHours * 60);
  var days = Math.floor(totalMin / 1440);
  totalMin = ((totalMin % 1440) + 1440) % 1440;
  var h = Math.floor(totalMin / 60), m = totalMin % 60;
  var dd = new Date(Date.UTC(d.getUTCFullYear(), d.getUTCMonth(), d.getUTCDate() + days));
  var M = dd.getUTCMonth() + 1, D = dd.getUTCDate();
  return (M < 10 ? '0' : '') + M + '/' + (D < 10 ? '0' : '') + D + ' ' + (h < 10 ? '0' : '') + h + ':' + (m < 10 ? '0' : '') + m;
}

function fmtTimeLocal(utcStr){if(!utcStr)return'';var d=new Date(String(utcStr)+'Z');if(isNaN(d.getTime()))return utcStr;var Y=d.getUTCFullYear(),M=d.getUTCMonth()+1,D=d.getUTCDate(),h=d.getUTCHours()+8,m=d.getUTCMinutes();return Y+'-'+(M<10?'0':'')+M+'-'+(D<10?'0':'')+D+'T'+(h<10?'0':'')+h+':'+(m<10?'0':'')+m;}

function dualTimeStr(e) {
  var utc = e.scheduled_at;
  if (!utc) return '-';
  var bj = fmtTime(utc, 8);
  var ctz = e.timezone;
  var cofs = tzOffset(ctz);
  if (cofs === null || cofs === 8) return '<b>Beijing</b> ' + bj;
  var cl = fmtTime(utc, cofs);
  return '<b>Beijing</b> ' + bj + '<br><b style="color:#059669">Customer</b> ' + cl + (ctz ? ' (' + ctz + ')' : '');
}

function startCountdown(){
  if(cdInterval)clearInterval(cdInterval);
  cdInterval=setInterval(function(){
    var el=document.getElementById('cdDisplay');
    if(!el){clearInterval(cdInterval);cdInterval=null;return}
    var now=new Date();
    var next=null;
    cdTargets.forEach(function(t){
      if(t.ts>now&&(!next||t.ts<next))next=t.ts;
    });
    if(!next){el.textContent='Can send now';return}
    var diff=Math.max(0,Math.floor((next-now)/1000));
    var hh=Math.floor(diff/3600);
    var mm=Math.floor((diff%3600)/60);
    var ss=diff%60;
    if(hh>0)el.textContent=hh+'h '+mm+'m '+ss+'s before send (recommend customer-local 9:00-17:00)';
    else el.textContent=mm+'m '+ss+'s before send';
  },1000);
}

function REmail(p){
  var h='';
  // ── 页面头 ──
  h+='<div class="page-hd" style="align-items:center"><div><h2>Email Center</h2><p class="page-sub">Check replies first, then handle pending, drafts and the inbox。</p></div>'
    + '<button class="btn btn-sm btn-b" onclick="REmail(document.getElementById(\'mainPane\'))">Refresh</button></div>';
  // ── 邮件表现统计卡 ──
  if (emailPerf) {
    var o = emailPerf.overview || {};
    var pr = emailPerf.profiles || [];
    var topProfile = '';
    if (pr.length > 0) {
      var best = pr.slice().sort(function(a,b){return (b.reply_rate||0)-(a.reply_rate||0);})[0];
      if (best && best.reply_rate > 0) topProfile = '<div class="fs11 c6" style="margin-top:8px">🏆 Highest reply rate: Profile '+best.profile+' ('+best.reply_rate+'%)</div>';
    }
    h+='<div style="display:flex;gap:10px;margin-bottom:16px;flex-wrap:wrap">';
    h+='<div class="stat-card" style="--stat-color:#0f172a"><div class="stat-label">Total sent</div><div class="stat-value-wrapper"><span class="stat-value">'+(o.total_sent||0)+'</span></div></div>';
    h+='<div class="stat-card" style="--stat-color:#2563eb"><div class="stat-label">Customers reached</div><div class="stat-value-wrapper"><span class="stat-value">'+(o.contacted_customers||0)+'</span></div></div>';
    h+='<div class="stat-card" style="--stat-color:#059669"><div class="stat-label">Real replies</div><div class="stat-value-wrapper"><span class="stat-value">'+(o.total_replied||0)+'</span></div></div>';
    h+='<div class="stat-card" style="--stat-color:#7c3aed"><div class="stat-label">Reply rate</div><div class="stat-value-wrapper"><span class="stat-value">'+(o.reply_rate||0)+'%</span></div></div>';
    h+='<div class="stat-card" style="--stat-color:#0891b2"><div class="stat-label">Replies within 7 days</div><div class="stat-value-wrapper"><span class="stat-value">'+(o.replied_within_7d||0)+'</span></div></div>';
    h+='</div>';

    // 各画像回复率 chips
    if (pr.length > 0) {
      h+='<div class="card p3" style="margin-bottom:16px">';
      h+='<div class="fs12 fwm mb2" style="color:#0f172a">Reply rate by profile</div>';
      h+='<div style="display:flex;gap:8px;flex-wrap:wrap;font-size:11px">';
      pr.forEach(function(r){
        if (!r.sent || r.sent === 0) return;
        var rateColor = r.reply_rate >= 10 ? '#059669' : r.reply_rate > 0 ? '#f59e0b' : '#94a3b8';
        h+='<span style="padding:4px 10px;background:#f8fafc;border:1px solid #e4e9f2;border-radius:6px"><b style="color:#2563eb">'+E(r.profile)+'</b>: '+r.sent+' emails · '+r.contacted+'Customer → <b style="color:'+rateColor+'">'+r.reply_rate+'%</b></span>';
      });
      h+='</div>'+topProfile+'</div>';
    }
    if (!pr.length) h += topProfile;
  }

  h+='<div class="filter-bar" style="margin-bottom:16px">';
  h+='<div class="stat-card" style="--stat-color:#38bdf8"><div class="stat-label">Draft</div><div class="stat-value-wrapper"><span class="stat-value">'+(eqData||[]).filter(function(e){return e.status==='draft'}).length+'</span></div></div>';
  h+='<div class="stat-card" style="--stat-color:#d97706"><div class="stat-label">Pending</div><div class="stat-value-wrapper"><span class="stat-value">'+(eqData||[]).filter(function(e){return e.status==='pending'}).length+'</span></div></div>';
  h+='<div class="stat-card" style="--stat-color:#059669"><div class="stat-label">Sent today</div><div class="stat-value-wrapper"><span class="stat-value">'+stats.sent+'</span></div><div class="fs11" style="color:#64748b;margin-top:2px">Limit '+stats.limit+'</div></div>';
  h+='<div class="stat-card" style="--stat-color:#7c3aed"><div class="stat-label">Customer replies</div><div class="stat-value-wrapper"><span class="stat-value">'+(eqInbox||[]).length+'</span></div><div class="fs11" style="color:#64748b;margin-top:2px">';
  var unreadCount = (eqInbox||[]).filter(function(i){ return !i.is_read || i.is_read === 0; }).length;
  if (unreadCount > 0) h+=unreadCount+' Unread';
  h+='</div></div>';
  h+='</div>';

  var tabs=[{key:'queue',label:'Pending'},{key:'sent',label:'Sent'},{key:'inbox',label:'Inbox'}];
  h+='<div class="tab-bar">';
  tabs.forEach(function(t){
    var active=emailFilter===t.key;
    h+='<button id="tab_'+t.key+'" class="'+(active?'active':'')+'">'+t.label+'</button>';
  });
  h+='</div>';
  // ── Global email search (queue + sent tabs) ──
  var searchTerm = window._emailSearchTerm || '';
  var searchClearStyle = searchTerm ? '' : 'display:none;';
  h+='<div id="emailSearchBar" style="margin-bottom:10px;'+(emailFilter==='inbox'?'display:none':'')+'">';
  h+='<div style="display:flex;align-items:center;padding:4px 8px;background:#f8fafc;border:1px solid #e2e8f0;border-radius:6px;max-width:420px"><span style="font-size:12px;color:#94a3b8;margin-right:4px">🔍</span><input id="emailSearchBox" type="text" placeholder="Search recipient / subject / body..." value="'+E(searchTerm)+'" style="flex:1;border:none;background:transparent;outline:none;font-size:13px;color:#1e293b;padding:6px 4px"><span id="emailSearchClear" style="cursor:pointer;font-size:14px;color:#64748b;padding:2px 4px;'+searchClearStyle+'" title="Clear search">&times;</span></div>';
  h+='</div>';
  h+='<div style="font-size:11px;color:#64748b;margin-bottom:12px">To view LinkedIn / WhatsApp / phone history, open the customer detail interactions.</div>';
  h+='<div style="display:flex;gap:8px;margin-bottom:16px;align-items:center">';
  h+=renderSenderSelector('email_sender','Sender');
  h+='<button class="btn" style="background:#2563eb" id="composeBtn">Compose</button>';
  h+='<button class="btn" style="background:#8b5cf6" id="fetchBtn">Sync replies</button>';
  h+='<button class="btn" style="background:#16a34a" id="sendBtn">Send confirmed queue</button>';

  if(emailFilter==='queue'){
    var now=new Date();
    var nextEligible=null;
    cdTargets.forEach(function(t){if(!nextEligible||t.ts<nextEligible)nextEligible=t.ts});
    if(nextEligible&&nextEligible>now){
      h+='<div style="margin-left:12px;font-size:12px;color:#64748b"><span id="cdDisplay" style="color:#0ea5e9;font-weight:500"></span></div>';
    }else if(cdTargets.length>0){
      h+='<div style="margin-left:12px;font-size:12px;color:#16a34a;font-weight:500" id="cdDisplay">Can send now</div>';
    }
  }
  h+='</div>';

  if(emailFilter==='queue'){
    h+='<div style="font-size:11px;color:#64748b;margin-bottom:10px">First emails that open with self-introduction are blocked; the list shows the ⚠ opening status.</div>';
  }

  // Inbox quick filter state
  window._inboxQuickFilter = window._inboxQuickFilter || 'all';

  if(emailFilter==='queue'){
    var pd=eqData.filter(function(e){return e.status==='pending'||e.status==='sending'});
    var qs = window._emailSearchTerm;
    if (qs) {
      var qsl = qs.toLowerCase();
      pd = pd.filter(function(e){
        return (e.to_email||'').toLowerCase().indexOf(qsl)>=0
            || (e.subject||'').toLowerCase().indexOf(qsl)>=0
            || (e.body||'').toLowerCase().indexOf(qsl)>=0;
      });
    }
    if(!pd.length){
      var emptyMsg = qs ? 'No matches for "'+E(qs)+'" pending emails' : 'No pending emails';
      h+='<div class="card" style="text-align:center;padding:48px 16px;color:#64748b">'+emptyMsg+'</div>';
    }else{
      h+='<div class="card oa"><table><thead><tr><th>Recipient</th><th>Subject</th><th>Status</th><th>Scheduled</th><th>Wait</th><th width="55">View</th><th width="180">Actions</th></tr></thead><tbody>';
      pd.forEach(function(e){
        var waitStr='';
        if(e.scheduled_at){
          var eta=new Date(e.scheduled_at+'Z');
          var diff=Math.max(0,Math.floor((eta-new Date())/1000));
          if(diff<=0)waitStr='<span style="color:#16a34a;font-size:11px">Now</span>';
          else if(diff<3600)waitStr='<span style="color:#f59e0b;font-size:11px">'+Math.floor(diff/60)+'m</span>';
          else waitStr='<span style="color:#ef4444;font-size:11px">'+Math.floor(diff/3600)+'h '+Math.floor((diff%3600)/60)+'m</span>';
        }else{
          waitStr='<span style="color:#64748b;font-size:11px">-</span>';
        }
        var autoTag=(e.subject||'').indexOf('[Auto')>=0?'<span style="font-size:9px;background:#fef3c7;color:#92400e;padding:1px 4px;border-radius:3px">Auto</span>':'';
        h+='<tr><td style="font-size:13px">'+E(e.to_email)+'</td>';
        h+='<td style="font-size:13px">'+autoTag+' <input value="'+E(e.subject||'').replace(/"/g,'&quot;')+'" data-edit-field="subject" data-eid="'+e.id+'" style="border:1px solid transparent;background:transparent;font-size:11px;width:180px;padding:2px 4px" onfocus="this.style.borderColor=\'#93c5fd\';this.style.background=\'#fff\'" onblur="this.style.borderColor=\'transparent\';this.style.background=\'transparent\'"></td>';
        var openingWarn = window.emailOpeningWarning(e);
        var openingBadge = openingWarn
          ? '<div style="margin-top:4px;font-size:10px;color:#b91c1c;background:#fee2e2;padding:1px 6px;border-radius:4px;white-space:nowrap">⚠ '+openingWarn+'</div>'
          : '<div style="margin-top:4px;font-size:10px;color:#047857;background:#d1fae5;padding:1px 6px;border-radius:4px;white-space:nowrap">✅ Opening OK</div>';
        h+='<td style="font-size:12px">'+emailStatusText(e.status)+openingBadge+'</td>';
        h+='<td style="font-size:11px;line-height:1.4">'+dualTimeStr(e)+'<br><input type="datetime-local" id="sched-'+e.id+'" value="'+(e.scheduled_at?fmtTimeLocal(e.scheduled_at):'')+'" style="border:1px solid #e2e8f0;font-size:10px;width:140px;padding:2px 4px;margin-top:2px"><button class="btn btn-sm" style="background:#6366f1;color:#fff;font-size:10px;padding:1px 8px;margin-left:4px;vertical-align:top;margin-top:2px" onclick="var inp=document.getElementById(\'sched-'+e.id+'\');if(!inp||!inp.value)return;var sd=new Date(inp.value);var bd={scheduled_at:sd.toISOString().substring(0,19).replace(/Z/g,\'\')};var btn=this;btn.disabled=true;btn.textContent=\'...\';fetch(\'/api/email/queue/'+e.id+'\',{method:\'PUT\',headers:{\'Content-Type\':\'application/json\'},body:JSON.stringify(bd)}).then(function(r){if(r.ok){T(\'Saved\');loadEmail()}else{T(\'Failed\',\'#dc2626\')}}).catch(function(){T(\'Failed\',\'#dc2626\')}).finally(function(){btn.disabled=false;btn.textContent=\'Save time\'})">Save time</button></td>';
        h+='<td>'+waitStr+'</td>';
        h+='<td><button class="btn btn-sm btn-b" data-preview="'+e.id+'">View</button></td>';
        h+='<td style="white-space:nowrap"><button class="btn btn-sm" style="background:#64748b;margin-right:4px;font-size:10px" data-save-inline="'+e.id+'">Save</button><button class="btn btn-sm" style="background:#16a34a;margin-right:4px" data-send-one="'+e.id+'">Send</button><button class="btn btn-sm" style="background:#f87171" data-cancel="'+e.id+'">Cancel</button></td></tr>';
      });
      h+='</tbody></table></div>';
    }

    var drafts=eqData.filter(function(e){return e.status==='draft'});
    if (qs) {
      drafts = drafts.filter(function(e){
        return (e.to_email||'').toLowerCase().indexOf(qsl)>=0
            || (e.subject||'').toLowerCase().indexOf(qsl)>=0
            || (e.body||'').toLowerCase().indexOf(qsl)>=0;
      });
    }
    if(drafts.length>0){
      h+='<hr style="margin:20px 0"><div class="flex aic g2 fw mb2"><span class="fwm" style="font-size:14px">Draft - generated, awaiting review</span><span class="fs11 c6">Flow: review & edit → "Confirm pending" → click "Send" on the Pending tab</span></div>';
      h+='<div class="card oa"><table><thead><tr><th>Customer</th><th>Recipient</th><th>Subject</th><th>Body preview</th><th width="160">Actions</th></tr></thead><tbody>';
      drafts.forEach(function(e){
        var autoTag=(e.subject||'').indexOf('[Auto')>=0?'<span style="font-size:9px;background:#fef3c7;color:#92400e;padding:1px 4px;border-radius:3px">Auto</span>':'';
        var companyTag = e.company ? '<span style="color:#2563eb;font-size:12px;font-weight:600;cursor:pointer;text-decoration:underline" onclick="event.stopPropagation();openDrawer('+E(e.prospect_id)+')" title="Open customer details">'+E(e.company)+'</span>' : '<span style="color:#94a3b8">-</span>';
        var draftOpening = window.emailOpeningWarning(e);
        var draftBadge = draftOpening
          ? '<div style="margin-top:4px;font-size:10px;color:#b91c1c;background:#fee2e2;padding:1px 6px;border-radius:4px;white-space:nowrap">⚠ '+draftOpening+'</div>'
          : '<div style="margin-top:4px;font-size:10px;color:#047857;background:#d1fae5;padding:1px 6px;border-radius:4px;white-space:nowrap">✅ Opening OK</div>';
        h+='<tr><td style="font-size:12px">'+companyTag+'</td><td style="font-size:12px">'+E(e.to_email)+'</td><td style="font-size:13px">'+autoTag+' <input value="'+E(e.subject||'').replace(/"/g,'&quot;')+'" data-edit-field="subject" data-eid="'+e.id+'" style="border:1px solid transparent;background:transparent;font-size:11px;width:160px;padding:2px 4px" onfocus="this.style.borderColor=\'#93c5fd\';this.style.background=\'#fff\'" onblur="this.style.borderColor=\'transparent\';this.style.background=\'transparent\'"></td><td style="font-size:11px;color:#64748b">'+E((e.body||'').replace(/<br\s*\/?>/gi,' ').substring(0,80))+'...'+draftBadge+'</td><td style="white-space:nowrap">';
        h+='<button class="btn btn-sm btn-b" style="margin-right:4px" data-preview="'+e.id+'">Edit</button>';
        h+='<button class="btn btn-sm" style="background:#f59e0b;margin-right:4px;font-size:10px" data-approve="'+e.id+'">Confirm pending</button>';
        h+='<button class="btn btn-sm" style="background:#f87171;font-size:10px" data-cancel="'+e.id+'">Delete</button>';
        h+='</td></tr>';
      });
      h+='</tbody></table></div>';
    }
  }else if(emailFilter==='sent'){
    var sd=eqData.filter(function(e){return e.status==='sent'});
    var ss = window._emailSearchTerm;
    if (ss) {
      var ssl = ss.toLowerCase();
      sd = sd.filter(function(e){
        return (e.to_email||'').toLowerCase().indexOf(ssl)>=0
            || (e.subject||'').toLowerCase().indexOf(ssl)>=0
            || (e.body||'').toLowerCase().indexOf(ssl)>=0;
      });
    }
    if(!sd.length){
      var emptySentMsg = ss ? 'No matches for "'+E(ss)+'" sent emails' : 'No sent emails';
      h+='<div class="card" style="text-align:center;padding:48px 16px;color:#64748b">'+emptySentMsg+'</div>';
    }else{
      sd = sd.slice().sort(function(a,b){ return String(b.sent_at||'').localeCompare(String(a.sent_at||'')); });
      h+='<div class="card oa"><table><thead><tr><th>Customer</th><th>Recipient</th><th>Subject</th><th>Sent at</th><th width="70">View</th></tr></thead><tbody>';
      sd.forEach(function(e){
        var companyTag = e.company ? '<span style="color:#2563eb;font-size:12px;font-weight:600;cursor:pointer" onclick="event.stopPropagation();openDrawer('+E(e.prospect_id)+')">'+E(e.company)+'</span>' : '<span style="color:#94a3b8">-</span>';
        h+='<tr><td>'+companyTag+'</td><td>'+E(e.to_email)+'</td><td>'+E(e.subject)+'</td><td style="color:#64748b">'+(e.sent_at?fd(e.sent_at):'-')+'</td><td><button class="btn btn-sm btn-b" data-preview="'+e.id+'">View</button></td></tr>';
      });
      h+='</tbody></table></div>';
    }
  }else if(emailFilter==='inbox'){
    if(!eqInbox.length){
      h+='<div class="card" style="text-align:center;padding:48px 16px;color:#64748b">📭 No new emails in inbox<br><span style="font-size:11px">Click Sync replies to fetch new emails</span></div>';
    }else{
      // ── Smart search / filter bar ──
      h+='<div style="display:flex;gap:8px;align-items:center;margin-bottom:12px;flex-wrap:wrap">';
      var _inboxSearchVal = window._inboxSearchTerm || '';
      h+='<input id="inboxSearchBox" type="text" placeholder="Search sender / subject / customer / content..." value="'+E(_inboxSearchVal)+'" style="flex:1;min-width:240px;max-width:420px;padding:8px 12px;border:1px solid #d1d5db;border-radius:6px;font-size:13px;outline:none" onfocus="this.style.borderColor=\'#6366f1\'" onblur="this.style.borderColor=\'#d1d5db\'">';
      // Quick filters
      h+='<button class="inbox-filter-btn" data-filter="all" style="background:#6366f1;color:#fff">All</button>';
      h+='<button class="inbox-filter-btn" data-filter="unread">Unread</button>';
      h+='<button class="inbox-filter-btn" data-filter="hot">Hot / Inquiry / Sample</button>';
      h+='<button class="inbox-filter-btn" data-filter="unmatched">Unmatched</button>';
      h+='</div>';
      // Batch action bar
      h+='<div id="inboxBatchBar" style="display:none;padding:8px 12px;background:#f0f4ff;border:1px solid #bfdbfe;border-radius:8px;margin-bottom:10px;align-items:center;gap:8px">';
      h+='<span style="font-size:12px;color:#4f46e5;font-weight:600" id="batchSelectedCount">Selected 0  emails</span>';
      h+='<button class="btn btn-sm" style="background:#6366f1" onclick="batchMarkInbox(1)">Mark read</button>';
      h+='<button class="btn btn-sm" style="background:#64748b" onclick="batchMarkInbox(0)">Mark unread</button>';
      h+='<span style="flex:1"></span>';
      h+='<button class="btn btn-sm" style="background:#f8fafc;color:#64748b" id="inboxSelectAllBtn">Select all</button>';
      h+='<button class="btn btn-sm" style="background:#fef5f5;color:#dc2626" onclick="clearInboxSelection()">Cancel</button>';
      h+='</div>';
      // Stats line
      var bounceCount2=(eqInbox||[]).filter(function(i){return (i.reply_intent||'').toUpperCase()==='Bounced'}).length;
      var hotCount2=(eqInbox||[]).filter(function(i){var ip=inboxPriority(i);return ip===0;}).length;
      h+='<div style="display:flex;gap:16px;font-size:11px;color:#64748b;margin-bottom:8px;flex-wrap:wrap">';
      h+='<span>📬 <b style="color:#0f172a">'+eqInbox.length+'</b> emails total'+(unreadCount>0?', <b style="color:#6366f1">'+unreadCount+'</b> Unread':'')+'</span>';
      if(hotCount2>0)h+='<span>🔥 <b style="color:#dc2626">'+hotCount2+'</b> need attention</span>';
      if(bounceCount2>0)h+='<span style="color:#9ca3af">🚫 '+bounceCount2+' bounced</span>';
      h+='<span style="flex:1"></span><span style="font-size:10px">Click any row to view details and reply</span>';
      h+='</div>';
      // ── Inbox list as card layout instead of cramped table ──
      var inboxQuickFilter = window._inboxQuickFilter || 'all';
      // 按时间倒序（最新在前），不再按优先级插队
      var sortedInbox=eqInbox.slice().sort(function(a,b){
        var ta = a.interacted_at || a.email_received_at || '';
        var tb = b.interacted_at || b.email_received_at || '';
        return String(tb).localeCompare(String(ta));
      });
      // Apply quick filter
      if (inboxQuickFilter === 'unread') {
        sortedInbox = sortedInbox.filter(function(i){ return !i.is_read || i.is_read === 0; });
      } else if (inboxQuickFilter === 'hot') {
        sortedInbox = sortedInbox.filter(function(i){ return inboxPriority(i) <= 1; });
      } else if (inboxQuickFilter === 'unmatched') {
        sortedInbox = sortedInbox.filter(function(i){ return !i.prospect_id || i.prospect_id === 0; });
      }
      h+='<div style="max-height:65vh;overflow-y:auto;border:1px solid #e5e7eb;border-radius:8px">';
      sortedInbox.forEach(function(i){
        var isUnread = !i.is_read || i.is_read === 0;
        var pl=inboxPriorityLabel(i);
        var plainBody = htmlToPlain(i.content || '');
        var bodyPreview = plainBody.substring(0, 150);
        if (plainBody.length > 150) bodyPreview += '...';
        var timeStr = i.email_received_at ? fd(i.email_received_at) : (i.interacted_at ? fd(i.interacted_at) : '');
        var attBadge = '';
        try { var af = JSON.parse(i.attachment_files||'null'); if (af&&af.length>0) attBadge='📎×'+af.length; } catch(e) {}
        // Customer name with link
        var customerLine = '';
        if (i.prospect_id && i.prospect_id > 0) {
          customerLine = '<a href="#" onclick="event.stopPropagation();event.preventDefault();openDrawer('+i.prospect_id+')" style="color:#4f46e5;font-weight:600;font-size:11px;text-decoration:none">'+E(i.company||'#'+i.prospect_id)+'</a>';
        } else {
          customerLine = '<span style="color:#94a3b8;font-size:11px">Unmatched customer</span>';
        }
        h+='<div style="cursor:pointer;display:flex;align-items:flex-start;gap:12px;padding:12px 14px;border-bottom:1px solid #f1f5f9;'+(isUnread?'background:#f0f7ff;font-weight:600;':'')+'transition:background 0.15s" data-inbox-row="'+i.id+'" onmouseenter="this.style.background=\''+(isUnread?'#dbeafe':'#f8fafc')+'\'" onmouseleave="this.style.background=\''+(isUnread?'#f0f7ff':'')+'\'">';
        // Checkbox + status dot
        h+='<div style="flex-shrink:0;display:flex;flex-direction:column;align-items:center;gap:6px;padding-top:2px" onclick="event.stopPropagation()">';
        h+='<input type="checkbox" class="inbox-cb" data-inbox-id="'+i.id+'" style="cursor:pointer" onchange="updateInboxBatchBar()">';
        // Status badge
        if(pl.label==='Hot'||pl.label==='Inquiry'||pl.label==='Sample'||pl.label==='Positive'||pl.label==='Meeting'||pl.label==='Quote'||pl.label==='Bounced'){
          h+='<span style="font-size:9px;font-weight:600;padding:1px 5px;border-radius:3px;color:'+pl.color+';background:'+pl.bg+'">'+pl.label+'</span>';
        }else{
          h+='<span style="display:inline-block;width:8px;height:8px;border-radius:50%;background:'+(isUnread?'#6366f1':'#d1d5db')+'" title="'+(isUnread?'Unread':'Read')+'"></span>';
        }
        h+='</div>';
        // Main content
        h+='<div style="flex:1;min-width:0">';
        h+='<div style="display:flex;justify-content:space-between;align-items:baseline;margin-bottom:3px">';
        h+='<span style="font-size:12px;color:'+(isUnread?'#1e293b':'#64748b')+'">'+E(i.email_from||'-')+'</span>';
        h+='<span style="font-size:10px;color:#94a3b8;white-space:nowrap;margin-left:8px">'+timeStr+'</span>';
        h+='</div>';
        h+='<div style="font-size:12px;font-weight:500;margin-bottom:3px">'+(attBadge?'<span style="font-size:10px;color:#4f46e5;margin-right:4px">'+attBadge+'</span>':'')+E((i.subject||'(no subject)').substring(0,80))+'</div>';
        h+='<div style="font-size:11px;color:#64748b;line-height:1.4;max-height:32px;overflow:hidden">'+bodyPreview+'</div>';
        h+='</div>';
        // Right side: customer + time
        h+='<div style="flex-shrink:0;text-align:right;min-width:80px">';
        h+=customerLine;
        h+='<div style="margin-top:6px"><button class="btn btn-sm" style="background:#fff;color:#dc2626;border:1px solid #fecaca;font-size:10px;padding:1px 7px" data-inbox-del="'+i.id+'" title="Delete this inbox record">🗑</button></div>';
        h+='</div>';
        h+='</div>';
      });
      h+='</div>';
    }
  }

  p.innerHTML=h;
  bindSafe(p,'#tab_queue','click',function(){emailFilter='queue';window._emailSearchTerm='';loadEmail()});
  bindSafe(p,'#tab_sent','click',function(){emailFilter='sent';window._emailSearchTerm='';loadEmail()});
  bindSafe(p,'#tab_inbox','click',function(){emailFilter='inbox';loadEmail()});
  var composeBtn = p.querySelector('#composeBtn');
  if (composeBtn) composeBtn.addEventListener('click', function(){ openComposeModal(); });
  // ── Global email search (queue + sent tabs) ──
  var emailSearchBox = p.querySelector('#emailSearchBox');
  var emailSearchClear = p.querySelector('#emailSearchClear');
  if (emailSearchBox) {
    emailSearchBox.addEventListener('input', function(){
      window._emailSearchTerm = this.value.trim();
      if (emailSearchClear) emailSearchClear.style.display = window._emailSearchTerm ? '' : 'none';
      renderEmailTables();
    });
    emailSearchBox.addEventListener('focus', function(){
      this.parentElement.style.borderColor = '#6366f1';
    });
    emailSearchBox.addEventListener('blur', function(){
      this.parentElement.style.borderColor = '#e2e8f0';
    });
  }
  if (emailSearchClear) {
    emailSearchClear.addEventListener('click', function(){
      window._emailSearchTerm = '';
      if (emailSearchBox) { emailSearchBox.value = ''; emailSearchBox.focus(); }
      emailSearchClear.style.display = 'none';
      renderEmailTables();
    });
  }
  var inboxSearchEl = p.querySelector('#inboxSearchBox');
  if (inboxSearchEl) {
    inboxSearchEl.addEventListener('input', function(){
      window._inboxSearchTerm = this.value.trim();
      loadEmail();
    });
  }
  bindSafe(p,'#fetchBtn','click',async function(){
    var btn=p.querySelector('#fetchBtn');
    if(btn){btn.disabled=true;btn.textContent='Syncing...'}
    try{
      var r=await api('/email/fetch-replies',{method:'POST'});
      var closed={processed:0};
      try{closed=await api('/ops/replies/close-unclosed?limit=10',{method:'POST'})}catch(e2){}
      T('New replies '+(r.new_replies||0)+' replies, auto-analyzed  '+(closed.processed||0)+' replies','#16a34a',5000);
      await loadEmail();
    }catch(e){T('Sync repliesFailed','#dc2626')}
    if(btn){btn.disabled=false;btn.textContent='Sync replies'}
  });
  bindSafe(p,'#sendBtn','click',async function(){
    var btn=p.querySelector('#sendBtn');
    if(btn){btn.disabled=true;btn.textContent='Sending...'}
    try{
      var r=await api('/email/send-ready',{method:'POST'});
      T('Sent '+r.sent+'  emails'+(r.failed?'，Failed '+r.failed+'  emails':'')+'  - customer entered follow-up flow (reminder in 3 days)', r.failed?'#f97316':'#16a34a', 6000);
      await loadEmail();
    }catch(e){T('Send failed','#dc2626')}
    if(btn){btn.disabled=false;btn.textContent='Send confirmed queue'}
  });
  bindSafe(p,'#gotoChannels','click',function(e){e.preventDefault();T('Open the customer detail interactions to view all-channel history.')});

  p.querySelectorAll('[data-cancel]').forEach(function(b){b.addEventListener('click',async function(){
    var btn=b,eid=parseInt(btn.dataset.cancel);
    var item=eqData.find(function(e){return e.id===eid});
    if(item&&(item.status==='draft'||item.status==='pending')){
      if(!confirm('Delete this '+(item.status==='draft'?'Draft':'pending email')+'? This action cannot be undone.'))return;
      btn.disabled=true;btn.textContent='...';
      try{await api('/email/queue/'+eid,{method:'DELETE'});T('Deleted');await loadEmail()}catch(e){T('Delete failed','#dc2626');btn.disabled=false;btn.textContent='Delete'}
    }else{
      btn.disabled=true;btn.textContent='...';
      try{await api('/email/queue/'+eid+'/cancel',{method:'POST'});T('Cancelled');await loadEmail()}catch(e){T('CancelFailed','#dc2626');btn.disabled=false;btn.textContent='Cancel'}
    }
  })});
  p.querySelectorAll('[data-approve]').forEach(function(b){b.addEventListener('click',async function(){
    var btn=b,eid=parseInt(btn.dataset.approve);
    btn.disabled=true;btn.textContent='...';
    try{await api('/email/queue/'+eid,{method:'PUT',body:{status:'pending'}});T('Confirmed as pending','#f59e0b');await loadEmail()}catch(e){T('Confirm failed','#dc2626');btn.disabled=false;btn.textContent='Confirm pending'}
  })});
  p.querySelectorAll('[data-send-one]').forEach(function(b){b.addEventListener('click',async function(){
    var btn=b;
    btn.disabled=true;btn.textContent='...';
    try{await api('/email/send-one/'+btn.dataset.sendOne,{method:'POST'});T('✅ Sent → Customer entered the follow-up flow; reminder in 3 days','#16a34a',5000);await loadEmail()}catch(e){T('Send failed: '+(e.detail||e.message||'Unknown error'),'#dc2626',6000);btn.disabled=false;btn.textContent='Send'}
  })});
  p.querySelectorAll('[data-save-inline]').forEach(function(b){b.addEventListener('click',async function(){
    var eid=parseInt(b.dataset.saveInline),btn=b;
    var fields=p.querySelectorAll('[data-eid="'+eid+'"][data-edit-field]');
    var subject='',scheduled='';
    fields.forEach(function(f){if(f.dataset.editField==='subject')subject=f.value;if(f.dataset.editField==='scheduled')scheduled=f.value});
    if(!subject.trim()&&!scheduled){T('No changes');return}
    btn.disabled=true;btn.textContent='...';
    var body={};
    if(subject.trim())body.subject=subject.trim();
    if(scheduled){var sd=new Date(scheduled);body.scheduled_at=sd.toISOString().substring(0,19).replace('Z','');}
    try{await api('/email/queue/'+eid,{method:'PUT',body:body});T('Saved');await loadEmail()}catch(e){T('Save failed','#dc2626');btn.disabled=false;btn.textContent='Save'}
  })});
  p.querySelectorAll('[data-view-inbox]').forEach(function(b){b.addEventListener('click',function(e){viewInboxReply(parseInt(b.dataset.viewInbox))})});
  // Click on any inbox row/card to open
  p.querySelectorAll('[data-inbox-row]').forEach(function(tr){
    tr.addEventListener('click', function(e){
      // Don't open if clicking checkbox or client link
      if (e.target.tagName === 'INPUT' || e.target.tagName === 'A' || e.target.closest('a') || e.target.closest('[data-inbox-del]')) return;
      var id = parseInt(tr.dataset.inboxRow);
      if (id > 0) viewInboxReply(id);
    });
  });
  // Delete a received email record
  p.querySelectorAll('[data-inbox-del]').forEach(function(b){
    b.addEventListener('click', async function(e){
      e.stopPropagation();
      var iid = parseInt(b.dataset.inboxDel);
      if (!confirm('Delete this inbox record？\n\nNote: if the email still exists in the mailbox, Sync replies will pull it back.')) return;
      b.disabled = true;
      b.textContent = '...';
      try {
        await api('/interactions/'+iid, {method:'DELETE'});
        T('Deleted');
        await loadEmail();
      } catch(err) {
        T('Delete failed', '#dc2626');
        b.disabled = false;
        b.textContent = '🗑';
      }
    });
  });
  // Quick filter buttons
  p.querySelectorAll('.inbox-filter-btn').forEach(function(b){
    b.addEventListener('click', function(e){
      e.stopPropagation();
      window._inboxQuickFilter = b.dataset.filter;
      p.querySelectorAll('.inbox-filter-btn').forEach(function(x){ x.style.background='#f1f5f9'; x.style.color='#475569'; });
      b.style.background='#6366f1'; b.style.color='#fff';
      render();
    });
  });
  // Batch selection
  var selectAll = p.querySelector('#inboxSelectAll');
  if (selectAll) selectAll.addEventListener('change', function(){
    var cbs = p.querySelectorAll('.inbox-cb');
    cbs.forEach(function(cb){ cb.checked = selectAll.checked; });
    updateInboxBatchBar();
  });
  window.updateInboxBatchBar = function(){
    var cbs = document.querySelectorAll('.inbox-cb:checked');
    var count = cbs.length;
    var bar = document.getElementById('inboxBatchBar');
    var label = document.getElementById('batchSelectedCount');
    if (bar) bar.style.display = count > 0 ? 'flex' : 'none';
    if (label) label.textContent = 'Selected ' + count + '  emails';
    // Sync select-all checkbox
    var all = document.getElementById('inboxSelectAll');
    var total = document.querySelectorAll('.inbox-cb');
    if (all && total.length > 0) all.checked = count === total.length;
  };
  window.clearInboxSelection = function(){
    document.querySelectorAll('.inbox-cb').forEach(function(cb){ cb.checked = false; });
    updateInboxBatchBar();
  };
  var selectAllBtn = p.querySelector('#inboxSelectAllBtn');
  if (selectAllBtn) selectAllBtn.addEventListener('click', function(){
    var all = document.getElementById('inboxSelectAll');
    if (all) all.checked = true;
    document.querySelectorAll('.inbox-cb').forEach(function(cb){ cb.checked = true; });
    updateInboxBatchBar();
  });
  window.batchMarkInbox = async function(isRead){
    var cbs = document.querySelectorAll('.inbox-cb:checked');
    var ids = [];
    cbs.forEach(function(cb){ ids.push(parseInt(cb.dataset.inboxId)); });
    if (!ids.length){ T('Select emails first'); return; }
    try {
      await api('/interactions/inbox/batch-read', {method:'PUT', body:{ids: ids, is_read: isRead}});
      T(isRead ? 'Marked ' + ids.length + ' emails as read' : 'Marked ' + ids.length + ' emails as unread');
      await loadEmail();
    } catch(e) { T('ActionsFailed', '#dc2626'); }
  };
  p.querySelectorAll('[data-preview]').forEach(function(b){b.addEventListener('click',function(){
    var qid=parseInt(b.dataset.preview);
    var item=eqData.find(function(e){return e.id===qid});
    if(!item){T('Email not found');return}
    var oldM=document.getElementById('eqPrevMsk');if(oldM)oldM.remove();
    var oldC=document.getElementById('eqPrevWrap');if(oldC)oldC.remove();
    var h='<div class="mask" style="z-index:80" id="eqPrevMsk"></div>';
    h+='<div id="eqPrevWrap" class="card" style="position:fixed;top:8%;left:50%;transform:translateX(-50%);width:650px;max-width:92vw;max-height:85vh;overflow-y:auto;z-index:90;padding:24px;background:#fff">';
    h+='<div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:12px"><b class="fs14">'+E(item.subject||'')+'</b><button style="border:none;background:none;font-size:20px;cursor:pointer;color:#64748b" onclick="document.getElementById(\'eqPrevMsk\').remove();document.getElementById(\'eqPrevWrap\').remove()">&times;</button></div>';
    h+='<div style="font-size:11px;color:#64748b;margin-bottom:12px">Recipient: <b>'+E(item.to_email)+'</b> | Status: '+emailStatusText(item.status)+(item.scheduled_at?' | Scheduled: '+dualTimeStr(item):'')+'</div>';
    h+='<label style="font-size:11px;color:#64748b;display:block;margin-bottom:2px">Subject (editable)</label>';
    h+='<input id="eqPrevSubject" value="'+E(item.subject||'')+'" style="width:100%;padding:8px 10px;border:1px solid #d1d5db;border-radius:6px;font-size:13px;margin-bottom:10px;font-family:inherit">';
    h+='<div id="eqPrevBody" contenteditable="true" style="width:100%;padding:14px;background:#f8fafc;border:1px solid #d1d5db;border-radius:6px;font-size:13px;line-height:1.7;max-height:40vh;min-height:200px;overflow-y:auto;outline:none;font-family:inherit;white-space:pre-wrap">'+(item.body||'(empty)')+'</div>';
    // Attachment display
    var attFiles=null;
    try{attFiles=JSON.parse(item.attachment_files||'null')}catch(e){}
    if(attFiles&&attFiles.length>0){
      h+='<div style="margin-top:8px;padding:8px 10px;background:#f0f4ff;border-radius:6px;border:1px solid #bfdbfe;font-size:11px">';
      h+='<b>📎 Attachments ('+attFiles.length+')</b>';
      for(var ai=0;ai<attFiles.length;ai++){
        var a=attFiles[ai];
        var sizeStr=a.size?(a.size>1048576?(a.size/1048576).toFixed(1)+'MB':(a.size/1024).toFixed(0)+'KB'):'';
        h+='<div style="margin-top:4px"><a href="/attachments/'+encodeURIComponent((a.path||'').replace('attachments/',''))+'" download style="color:#4f46e5;text-decoration:none;font-weight:500" target="_blank">📎 '+E(a.filename)+'</a> <span style="color:#64748b">'+sizeStr+'</span></div>';
      }
      h+='</div>';
    }
    h+='<div style="margin-top:12px;display:flex;gap:6px">';
    h+=renderSenderSelector('email_sender','Sender', item && item.sender_key);
    h+='<button class="btn btn-sm" style="background:#9333ea;color:#fff" id="eqPrevQc">Quality check</button>';
    h+='<button class="btn btn-sm" style="background:#8b5cf6" id="eqPrevSave" data-sid="'+item.id+'">Save edits</button>';
    if(item.status==='draft') h+='<button class="btn btn-sm" style="background:#f59e0b" id="eqPrevApprove" data-sid="'+item.id+'">Confirm pending</button>';
    if(item.status==='pending') h+='<button class="btn btn-sm" style="background:#16a34a" id="eqPrevSend" data-sid="'+item.id+'">Send now</button>';
    h+='</div>';
    h+='</div></div>';
    document.body.insertAdjacentHTML('beforeend',h);
    document.getElementById('eqPrevMsk').onclick=function(){document.getElementById('eqPrevMsk').remove();document.getElementById('eqPrevWrap').remove()};
    var cpBtn=document.getElementById('eqPrevCopy');
    if(cpBtn)cpBtn.addEventListener('click',function(){navigator.clipboard.writeText(item.body||'');T('Body copied')});
    var qcPrevBtn=document.getElementById('eqPrevQc');
    if(qcPrevBtn)qcPrevBtn.addEventListener('click',function(){
      var subj=((document.getElementById('eqPrevSubject')||{}).value)||'';
      var raw=((document.getElementById('eqPrevBody')||{}).innerHTML)||'';
      var clean=raw.replace(/<br\s*\/?>/gi,'\n').replace(/<\/p>/gi,'\n').replace(/<[^>]+>/g,'').replace(/&nbsp;/g,' ').trim();
      window.runQualityCheck(subj, clean, item.prospect_id||0);
    });
    document.getElementById('eqPrevSave').addEventListener('click',async function(){
      var btn=document.getElementById('eqPrevSave');
        var newBody=document.getElementById('eqPrevBody').innerHTML;
      if(!newBody||!newBody.trim()){T('Body cannot be empty');return}
      btn.disabled=true;btn.textContent='Saving...';
      try{
        var newSubj=document.getElementById('eqPrevSubject').value.trim()||item.subject||'';
        var upd={subject:newSubj,body:newBody,sender_key:getSenderKey('email_sender')};
        await api('/email/queue/'+btn.dataset.sid,{method:'PUT',body:upd});
        T('Saved');
        document.getElementById('eqPrevMsk').remove();
        document.getElementById('eqPrevWrap').remove();
        await loadEmail();
      }catch(e){T('Save failed','#dc2626');btn.disabled=false;btn.textContent='Save edits'}
    });
    var approveBtn=document.getElementById('eqPrevApprove');
    if(approveBtn)approveBtn.addEventListener('click',async function(){
      var btn=document.getElementById('eqPrevApprove');
      btn.disabled=true;btn.textContent='...';
      try{
        var newSubj=document.getElementById('eqPrevSubject').value.trim()||item.subject||'';
        var newBody2=document.getElementById('eqPrevBody').innerHTML;
        await api('/email/queue/'+btn.dataset.sid,{method:'PUT',body:{subject:newSubj,body:newBody2,status:'pending',sender_key:getSenderKey('email_sender')}});
        T('Confirmed as pending');
        document.getElementById('eqPrevMsk').remove();
        document.getElementById('eqPrevWrap').remove();
        await loadEmail();
      }catch(e){T('Confirm failed','#dc2626');btn.disabled=false;btn.textContent='Confirm pending'}
    });
    var sendPrevBtn=document.getElementById('eqPrevSend');
    if(sendPrevBtn)sendPrevBtn.addEventListener('click',async function(){
      var btn=document.getElementById('eqPrevSend');
      btn.disabled=true;btn.textContent='...';
      try{
        var newBody3=document.getElementById('eqPrevBody').innerHTML;
        if(newBody3 && newBody3!==item.body){
          await api('/email/queue/'+btn.dataset.sid,{method:'PUT',body:{body:newBody3}});
        }
        await api('/email/send-one/'+btn.dataset.sid,{method:'POST'});
        T('✅ Sent → Customer entered the follow-up flow; reminder in 3 days','#16a34a',5000);
        document.getElementById('eqPrevMsk').remove();
        document.getElementById('eqPrevWrap').remove();
        await loadEmail();
      }catch(e){T('Send failed: '+(e.detail||e.message||'Unknown error'),'#dc2626',6000);btn.disabled=false;btn.textContent='Send now'}
    });
  })});

  if(emailFilter==='queue'&&cdTargets.length>0)startCountdown();
  else if(cdInterval){clearInterval(cdInterval);cdInterval=null}
}

function openComposeModal(){
    // Remove any existing compose modal
    var oldM = document.getElementById('composeMsk'); if (oldM) oldM.remove();
    var oldC = document.getElementById('composeWrap'); if (oldC) oldC.remove();

    var h = '<div class="mask" style="z-index:80" id="composeMsk"></div>';
    h += '<div id="composeWrap" class="card" style="position:fixed;top:3%;left:50%;transform:translateX(-50%);width:700px;max-width:96vw;max-height:94vh;overflow-y:auto;z-index:90;padding:20px 24px;background:#fff;box-shadow:0 20px 60px rgba(0,0,0,0.3)">';
    h += '<div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:16px"><b class="fs16">Compose</b><button style="border:none;background:none;font-size:22px;cursor:pointer;color:#64748b" onclick="document.getElementById(\'composeMsk\').remove();document.getElementById(\'composeWrap\').remove()">&times;</button></div>';

    // Recipient
    h += '<label style="font-size:12px;color:#475569;display:block;margin-bottom:3px">Recipient <span style="color:#dc2626">*</span></label>';
    h += '<input id="composeTo" placeholder="email@example.com" style="width:100%;padding:8px 10px;border:1px solid #d1d5db;border-radius:6px;font-size:13px;margin-bottom:10px;font-family:inherit">';

    // Subject
    h += '<label style="font-size:12px;color:#475569;display:block;margin-bottom:3px">Subject <span style="color:#dc2626">*</span></label>';
    h += '<input id="composeSubj" placeholder="Email subject..." style="width:100%;padding:8px 10px;border:1px solid #d1d5db;border-radius:6px;font-size:13px;margin-bottom:10px;font-family:inherit">';

    // Body with formatting toolbar
    h += '<label style="font-size:12px;color:#475569;display:block;margin-bottom:3px">Body <span style="color:#dc2626">*</span></label>';
    h += '<div style="display:flex;gap:2px;padding:4px 8px;background:#f8fafc;border:1px solid #d1d5db;border-bottom:none;border-radius:6px 6px 0 0;flex-wrap:wrap">';
    h += '<button class="rte-btn" data-cmd="bold" title="Bold" style="font-weight:bold;width:28px">B</button>';
    h += '<button class="rte-btn" data-cmd="italic" title="Italic" style="font-style:italic;width:28px">I</button>';
    h += '<button class="rte-btn" data-cmd="underline" title="Underline" style="text-decoration:underline;width:28px">U</button>';
    h += '<span style="width:1px;background:#d1d5db;margin:2px 4px"></span>';
    h += '<button class="rte-btn" data-cmd="insertUnorderedList" title="Bullets" style="width:28px">•</button>';
    h += '<button class="rte-btn" data-cmd="insertOrderedList" title="Numbered list" style="width:28px">1.</button>';
    h += '</div>';
    h += '<div id="composeBody" contenteditable="true" style="min-height:280px;max-height:45vh;overflow-y:auto;padding:12px 14px;border:1px solid #d1d5db;border-top:none;border-radius:0 0 6px 6px;font-size:13px;line-height:1.8;outline:none;background:#fff;white-space:pre-wrap;font-family:system-ui,-apple-system,sans-serif" placeholder="Write email body here..."></div>';
    h += '<style>#composeBody:empty:before{content:attr(placeholder);color:#64748b}</style>';

    // Attachments
    h += '<div style="margin-top:12px;margin-bottom:8px">';
    h += '<div style="font-size:12px;color:#475569;font-weight:500;margin-bottom:4px">Attachments</div>';
    h += '<div style="border:1px dashed #93c5fd;border-radius:6px;padding:10px;background:#f8fafc;min-height:40px">';
    h += '<div id="composeAttList" style="font-size:12px;color:#64748b;line-height:2">No attachments yet</div>';
    h += '<div style="margin-top:6px"><label style="cursor:pointer;display:inline-flex;align-items:center;gap:4px;font-size:12px;color:#4f46e5;font-weight:600;padding:5px 12px;border:1px solid #60a5fa;border-radius:4px;background:#f0f4ff"><span style="font-size:15px;line-height:1">+</span> Add file<input type="file" id="composeAttInput" multiple style="display:none" onchange="window._composeAttChanged()"></label></div>';
    h += '</div></div>';

    // Sender selector + actions
    h += '<div style="display:flex;gap:8px;align-items:center;margin-top:12px">';
    h += renderSenderSelector('email_sender','Sender');
    h += '<button class="btn" style="background:#16a34a" id="composeDraftBtn">Save as draft</button>';
    h += '<button class="btn" style="background:#3b82f6" id="composeSendBtn">Send now</button>';
    h += '<button class="btn" style="background:#9333ea;color:#fff" id="composeQcBtn">Multi-model quality check</button>';
    h += '</div>';

    h += '</div>'; // composeWrap

    document.body.insertAdjacentHTML('beforeend', h);

    // Mask click to close
    document.getElementById('composeMsk').onclick = function(){
        document.getElementById('composeMsk').remove();
        document.getElementById('composeWrap').remove();
    };

    // Attachment handling
    window._composeAttChosen = [];
    window._composeAttChanged = function(){
        var input = document.getElementById('composeAttInput');
        var list = document.getElementById('composeAttList');
        if (!input || !input.files.length) { if (list) list.innerHTML = '<span style="color:#64748b">No attachments yet</span>'; return; }
        var html = '';
        for (var i = 0; i < input.files.length; i++) {
            var f = input.files[i];
            var sizeStr = f.size > 1048576 ? (f.size/1048576).toFixed(1)+'MB' : (f.size/1024).toFixed(0)+'KB';
            html += '<div style="display:flex;align-items:center;justify-content:space-between;padding:4px 0;border-bottom:1px solid #f1f5f9"><span>📎 '+E(f.name)+' <span style="color:#64748b">('+sizeStr+')</span></span><button style="border:none;background:none;color:#dc2626;cursor:pointer;font-size:11px" onclick="this.parentElement.remove();window._composeAttSynced=false">✕</button></div>';
        }
        if (list) list.innerHTML = html || '<span style="color:#64748b">No attachments yet</span>';
        window._composeAttChosen = Array.from(input.files);
        window._composeAttSynced = false;
    };

    // RTE toolbar buttons
    document.querySelectorAll('#composeWrap .rte-btn').forEach(function(btn){
        btn.addEventListener('click', function(e){
            e.preventDefault();
            var cmd = this.dataset.cmd;
            var body = document.getElementById('composeBody');
            if (!body) return;
            body.focus();
            document.execCommand(cmd, false, null);
        });
    });

    // Shared send/save logic
    async function _composeSubmit(status) {
        var to = document.getElementById('composeTo').value.trim();
        var subj = document.getElementById('composeSubj').value.trim();
        var bodyEl = document.getElementById('composeBody');
        var raw = bodyEl ? bodyEl.innerHTML : '';
        var cleanHtml2 = cleanRichHtml(raw);
        var clean = cleanHtml2
            .replace(/<br\s*\/?>/gi,'\n')
            .replace(/<\/p>/gi,'\n')
            .replace(/<\/tr>/gi,'\n')
            .replace(/<[^>]+>/g,'')
            .replace(/&nbsp;/g,' ')
            .replace(/\n{3,}/g,'\n\n')
            .trim();
        if (!to) { T('Enter recipient','#dc2626'); return; }
        if (!clean) { T('Enter email body','#dc2626'); return; }
        var body = cleanHtml2;

        var attJson = null;
        if (window._composeAttChosen && window._composeAttChosen.length > 0 && !window._composeAttSynced) {
            var fd = new FormData();
            window._composeAttChosen.forEach(function(f){ fd.append('files', f); });
            try {
                var upRes = await authFetch('/api/email/upload-attachments', { method: 'POST', body: fd });
                if (!upRes.ok) { var et = await upRes.text(); try { et = JSON.parse(et).detail || et; } catch(e) {} throw new Error(et); }
                var upJson = await upRes.json();
                if (upJson.success) {
                    attJson = JSON.stringify(upJson.files);
                    window._composeAttSynced = true;
                }
            } catch(e) {
                T('Attachment upload failed: ' + (e.detail||e.message||''), '#dc2626');
                return;
            }
        }

        try {
            var payload = { prospect_id: 0, to_email: to, subject: subj || '(no subject)', body: body, status: status, sender_key: getSenderKey('email_sender') };
            if (attJson) payload.attachment_files = attJson;
            var res = await api('/email/queue', { method: 'POST', body: payload });
            if (status === 'draft') {
                showDraftHint('Email saved as draft');
            } else {
                // Try to send immediately
                try {
                    var sr = await api('/email/send-one/' + res.id, { method: 'POST' });
                    T('✅ Sent → Customer entered the follow-up flow; reminder in 3 days', '#16a34a', 5000);
                } catch(e) {
                    T('Moved to pending queue', '#f59e0b');
                }
            }
            document.getElementById('composeMsk').remove();
            document.getElementById('composeWrap').remove();
            await loadEmail();
        } catch(e) {
            T('Save failed: ' + (e.detail||e.message||''), '#dc2626');
        }
    }

    var draftBtn = document.getElementById('composeDraftBtn');
    var sendBtn = document.getElementById('composeSendBtn');
    if (draftBtn) draftBtn.addEventListener('click', function(){
        draftBtn.disabled = true; draftBtn.textContent = 'Saving...';
        sendBtn.disabled = true;
        _composeSubmit('draft').finally(function(){
            draftBtn.disabled = false; draftBtn.textContent = 'Save as draft';
            sendBtn.disabled = false;
        });
    });
    if (sendBtn) sendBtn.addEventListener('click', function(){
        sendBtn.disabled = true; sendBtn.textContent = 'Sending...';
        draftBtn.disabled = true;
        _composeSubmit('pending').finally(function(){
            sendBtn.disabled = false; sendBtn.textContent = 'Send now';
            draftBtn.disabled = false;
        });
    });
    var qcBtn = document.getElementById('composeQcBtn');
    if (qcBtn) qcBtn.addEventListener('click', function(){
      var subj = ((document.getElementById('composeSubj')||{}).value) || '';
      var raw = ((document.getElementById('composeBody')||{}).innerHTML) || '';
      var clean = raw.replace(/<br\s*\/?>/gi,'\n').replace(/<\/p>/gi,'\n').replace(/<[^>]+>/g,'').replace(/&nbsp;/g,' ').trim();
      window.runQualityCheck(subj, clean, 0);
    });
}

async function viewInboxReply(id){
  // Mark as read immediately when viewed
  try { await api('/interactions/inbox/'+id+'/read', {method:'PUT'}); } catch(e) {}
  // Use cached inbox data first — avoids API limit=50 issue
  var item=eqInbox.find(function(i){return i.id===id});
  if(!item){
    // Fallback: try API (for emails beyond default 50 limit)
    try{
      var r=await api('/interactions/inbox?limit=500');
      item=r.find(function(i){return i.id===id});
    }catch(e){}
  }
  if(!item){T('Email not found (may be deleted or out of range)','#dc2626');return}
  try{
    var pid=item.prospect_id;
    var prospect=null;
    if(pid>0){try{prospect=await api('/prospects/'+pid)}catch(e){}}
    var oldM=document.getElementById('vpMsk');if(oldM)oldM.remove();
    var oldC=document.getElementById('vpWrap');if(oldC)oldC.remove();
    var hasAnalysis=!!item.reply_intent;

    var h='<div class="mask" style="z-index:60" id="vpMsk"></div>';
    h+='<div id="vpWrap" class="card" style="position:fixed;top:2%;left:50%;transform:translateX(-50%);width:900px;max-width:98vw;max-height:96vh;overflow-y:auto;z-index:70;padding:18px 24px;background:#fff">';
    h+='<div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:16px"><h3 style="margin:0;font-size:16px">'+E(item.subject||'')+'</h3><button style="border:none;background:none;font-size:22px;cursor:pointer;color:#64748b" onclick="document.getElementById(\'vpMsk\').remove();document.getElementById(\'vpWrap\').remove()">&times;</button></div>';
    h+='<div style="font-size:12px;color:#64748b;margin-bottom:16px">Sender: <b>'+E(item.email_from||'')+'</b> | '+fd(item.interacted_at)+(prospect?' | Company: <b>'+E(prospect.company)+'</b>':'')+'</div>';
    h+='<div style="padding:12px;background:#f8fafc;border-radius:6px;margin-bottom:16px;font-size:13px;line-height:1.7;max-height:200px;overflow-y:auto">'+(item.content ? formatEmailBody(item.content) : '(empty)')+'</div>';

    var attFiles=null;
    try{attFiles=JSON.parse(item.attachment_files||'null')}catch(e){}
    if(attFiles&&attFiles.length>0){
      h+='<div style="margin-bottom:12px;padding:10px 12px;background:#f0f4ff;border-radius:6px;border:1px solid #bfdbfe;font-size:12px">';
      h+='<b>Attachments ('+attFiles.length+')</b>';
      for(var ai=0;ai<attFiles.length;ai++){
        var a=attFiles[ai];
        var sizeStr=a.size?(a.size>1048576?(a.size/1048576).toFixed(1)+'MB':(a.size/1024).toFixed(0)+'KB'):'';
        h+='<div style="margin-top:6px"><a href="/attachments/'+encodeURIComponent(a.path.replace('attachments/',''))+'" download style="color:#4f46e5;text-decoration:none;font-weight:500" target="_blank">📎 '+E(a.filename)+'</a> <span style="color:#64748b">'+sizeStr+'</span></div>';
      }
      h+='</div>';
    }

    h+='<div id="vpAnalysisArea" style="margin-bottom:8px">';
    if(hasAnalysis){
      h+='<div style="padding:10px 12px;background:#f0fdf6;border-radius:6px;font-size:12px"><b>AI analysis: </b>'+E(item.reply_intent)+(item.sentiment_score?'（sentiment score: '+item.sentiment_score+'）':'')+(item.ai_suggested_action?'<br>Suggested: '+E(item.ai_suggested_action):'')+'</div>';
    }else{
      h+='<div class="flex aic g2" style="margin-top:4px">'+renderModelSelector('model_email','Model')+'<button class="btn btn-sm" style="background:#f59e0b" id="vpAnalyze">AI analyze this reply</button></div>';
    }
    h+='</div>';

    h+='<div style="border-top:1px solid #e5e7eb;padding-top:12px">';
    h+='<label style="font-size:11px;color:#64748b;display:block;margin-bottom:2px">Recipient</label><input id="vpTo" value="'+E(item.email_from||'')+'" style="margin-bottom:8px">';
    h+='<label style="font-size:11px;color:#64748b;display:block;margin-bottom:2px">Subject</label><input id="vpSubj" value="Re: '+E(item.subject||'')+'" style="margin-bottom:8px">';
    h+='<label style="font-size:11px;color:#64748b;display:block;margin-bottom:2px">Reply body</label>';
    h+='<div style="display:flex;gap:2px;padding:4px 8px;background:#f8fafc;border:1px solid #d1d5db;border-bottom:none;border-radius:6px 6px 0 0;flex-wrap:wrap">';
    h+='<button class="rte-btn" data-cmd="bold" title="Bold" style="font-weight:bold;width:28px">B</button>';
    h+='<button class="rte-btn" data-cmd="italic" title="Italic" style="font-style:italic;width:28px">I</button>';
    h+='<button class="rte-btn" data-cmd="underline" title="Underline" style="text-decoration:underline;width:28px">U</button>';
    h+='<span style="width:1px;background:#d1d5db;margin:2px 4px"></span>';
    h+='<button class="rte-btn" data-cmd="insertUnorderedList" title="Bullets" style="width:28px">•</button>';
    h+='<button class="rte-btn" data-cmd="insertOrderedList" title="Numbered list" style="width:28px">1.</button>';
    h+='<span style="width:1px;background:#d1d5db;margin:2px 4px"></span>';
    h+='<button class="rte-btn" data-cmd="h2" title="Heading" style="width:28px">H</button>';
    h+='<button class="rte-btn" data-cmd="createLink" title="Insert link" style="width:28px">🔗</button>';
    h+='<span style="width:1px;background:#d1d5db;margin:2px 4px"></span>';
    h+='<button class="rte-btn" id="vpAutoFormat" title="AI auto format" style="width:auto;padding:2px 8px;background:#eef2ff;border-color:#c7d2fe;color:#4338ca;font-weight:600;font-size:11px">✨ AIformat</button>';
    h+='</div>';
    h+='<div id="vpBody" contenteditable="true" style="min-height:300px;max-height:55vh;overflow-y:auto;padding:12px 14px;border:1px solid #d1d5db;border-top:none;border-radius:0 0 6px 6px;font-size:13px;line-height:1.8;outline:none;background:#fff;white-space:pre-wrap;font-family:system-ui,-apple-system,sans-serif" placeholder="Write reply here..."></div>';
    h+='<style>#vpBody:empty:before{content:attr(placeholder);color:#64748b}.rte-btn{border:1px solid transparent;background:transparent;cursor:pointer;border-radius:3px;font-size:12px;color:#475569;padding:2px 4px;line-height:1.4}.rte-btn:hover{background:#e2e8f0;border-color:#334155}</style>';
    h+='<div id="vpAiDraftArea" style="margin-bottom:8px"></div>';

    h+='<div id="vpChatPanel" style="margin-bottom:12px;border:1px solid #e2e8f0;border-radius:8px;overflow:hidden">';
    h+='<div style="padding:8px 12px;background:#f8fafc;border-bottom:1px solid #e5e7eb;font-size:12px;font-weight:600;color:#475569;display:flex;align-items:center;justify-content:space-between">AI chat'+renderModelSelector('model_email','')+'</div>';
    h+='<div id="vpChatMsgs" style="max-height:250px;overflow-y:auto;padding:8px 12px;font-size:12px;min-height:80px;background:#fff"></div>';
    h+='<div style="display:flex;padding:6px 8px;gap:4px;border-top:1px solid #e5e7eb"><input id="vpChatInput" placeholder="Ask AI how to reply..." style="flex:1;font-size:12px;padding:5px 8px"><button class="btn btn-sm" style="background:#6366f1;white-space:nowrap" id="vpChatSend">Send</button></div>';
    h+='</div>';

    if(pid>0&&prospect){
      h+='<div style="margin-bottom:12px;padding:10px 12px;background:#fefce8;border-radius:6px;font-size:12px;border:1px solid #fde68a">';
      h+='<b>Customer info</b>';
      if(prospect.ai_score)h+='<br>Score: <b>'+prospect.ai_score+'</b>/100 | '+E(prospect.value_level||'-')+' | Profile '+E(prospect.profile_type||'-');
      if(prospect.score_reason)h+='<br>'+E(prospect.score_reason).substring(0,200);
      if(prospect.note)h+='<br>Note: '+E(prospect.note).substring(0,100);
      h+='<br><button class="btn btn-sm" style="background:#3b82f6;margin-top:4px" onclick="closeVpInline();openDrawer('+pid+')">Open customer details</button>';
      h+='</div>';
    }

    h+='<div style="display:flex;gap:8px;margin-bottom:8px">';
    h+=renderSenderSelector('email_sender','Sender', prospect && prospect.sender_key);
    h+='<button class="btn" style="background:#16a34a" id="vpSend">Save as draft</button>';
    h+='<button class="btn" style="background:#9333ea;color:#fff" id="vpQcBtn">Quality check</button>';
    h+='<div style="display:flex;align-items:center;gap:4px">';
    h+='<label style="font-size:10px;color:#64748b;white-space:nowrap">Next follow-up</label>';
    h+='<input type="date" id="vpNextFollow" value="" style="font-size:11px;padding:4px 6px;width:130px;border:1px solid #d1d5db;border-radius:4px" title="Auto-set next follow-up date after replying">';
    h+='</div>';
    if(pid>0||true){
      h+='<div style="display:flex;align-items:center;gap:4px;margin-left:4px">';
      h+='<button class="btn" style="background:#8b5cf6" id="vpAi">Generate AI reply</button>';
      h+=renderModelSelector('model_email','');
      h+='</div>';
    }
    h+='</div>';
    h+='<input id="vpReviseInput" placeholder="Tell AI how to revise this email reply..." style="margin-bottom:4px;font-size:12px">';
    h+='<button class="btn btn-sm" style="background:#eab308;color:#fff" id="vpReviseBtn">EditDraft</button>';
    h+='</div>';

    h+='<div style="margin-bottom:12px">';
    h+='<div style="font-size:11px;color:#64748b;margin-bottom:6px;font-weight:600">Attachments</div>';
    h+='<div style="border:1px dashed #93c5fd;border-radius:6px;padding:12px;background:#f8fafc;min-height:50px">';
    h+='<div id="vpAttList" style="font-size:12px;color:#64748b;line-height:2">No attachments yet</div>';
    h+='<div style="margin-top:8px"><label style="cursor:pointer;display:inline-flex;align-items:center;gap:4px;font-size:12px;color:#4f46e5;font-weight:600;padding:5px 12px;border:1px solid #60a5fa;border-radius:4px;background:#f0f4ff"><span style="font-size:15px;line-height:1">+</span> Add file<input type="file" id="vpAttInput" multiple style="display:none" onchange="window._vpAttChanged()"></label></div>';
    h+='</div>';
    h+='</div>';
    h+='<hr style="border:none;border-top:1px solid #e5e7eb;margin-bottom:12px">';

    h+='</div></div>';
    document.body.insertAdjacentHTML('beforeend',h);

    document.getElementById('vpMsk').onclick=function(){document.getElementById('vpMsk').remove();document.getElementById('vpWrap').remove()};
    window.closeVpInline=function(){document.getElementById('vpMsk').remove();document.getElementById('vpWrap').remove()};

    window._vpAttChosen = [];
    window._vpAttChanged = function(){
      var input = document.getElementById('vpAttInput');
      var list = document.getElementById('vpAttList');
      if (!input.files.length) { list.innerHTML='<span style="color:#64748b">No attachments yet</span>'; return; }
      var html='';
      for (var i=0;i<input.files.length;i++){
        var f=input.files[i];
        var sizeStr=f.size>1048576?(f.size/1048576).toFixed(1)+'MB':(f.size/1024).toFixed(0)+'KB';
        html+='<div style="display:flex;align-items:center;justify-content:space-between;padding:4px 0;border-bottom:1px solid #f1f5f9"><span>📎 '+E(f.name)+' <span style="color:#64748b">('+sizeStr+')</span></span><button style="border:none;background:none;color:#dc2626;cursor:pointer;font-size:11px" onclick="this.parentElement.remove();window._vpAttSynced=false">✕</button></div>';
      }
      list.innerHTML=html||'<span style="color:#64748b">No attachments yet</span>';
      window._vpAttChosen = Array.from(input.files);
      window._vpAttSynced = false;
    };

    document.querySelectorAll('.rte-btn').forEach(function(btn){
      btn.addEventListener('click',function(e){
        e.preventDefault();
        var cmd=this.dataset.cmd;
        var body=document.getElementById('vpBody');
        body.focus();
        if(cmd==='h2'){
          document.execCommand('formatBlock',false,'<h3>');
        }else if(cmd==='createLink'){
          var url=prompt('Enter link URL:','https://');
          if(url) document.execCommand('createLink',false,url);
        }else{
          document.execCommand(cmd,false,null);
        }
      });
    });

    var fmtBtn=document.getElementById('vpAutoFormat');
    if(fmtBtn)fmtBtn.addEventListener('click',async function(){
      var body=document.getElementById('vpBody');
      var raw=body.innerHTML;
      if(!raw||raw.replace(/<br\s*\/?>/g,'').replace(/<[^>]+>/g,'').trim().length<3){
        T('Write content before formatting','#dc2626');return;
      }
      fmtBtn.disabled=true;fmtBtn.textContent='Formatting...';
      try{
        var draftArea=document.getElementById('vpAiDraftArea');
        // 本地确定性format：稳定、立即生效、不改原文
        draftArea.innerHTML='<div style="font-size:11px;color:#6366f1;margin-bottom:4px">Formatting...</div>';
        var formatted = formatEmailBody(raw);
        if(formatted && formatted.replace(/<[^>]+>/g,'').trim().length >= 3){
          body.innerHTML = formatted;
          draftArea.innerHTML='<div style="font-size:11px;color:#16a34a">✅ Formatted (local rules; original unchanged)</div>';
        } else {
          draftArea.innerHTML='<div style="font-size:11px;color:#dc2626">Format failed: content empty</div>';
        }
      }catch(e){
        document.getElementById('vpAiDraftArea').innerHTML='<div style="font-size:11px;color:#dc2626">formatFailed: '+E(e.detail||e.message||'')+'</div>';
      }
      fmtBtn.disabled=false;fmtBtn.textContent='✨ AIformat';
    });

    var vpa=document.getElementById('vpAnalyze');
    if(vpa)vpa.addEventListener('click',async function(){
      vpa.disabled=true;vpa.textContent='Analyzing...';
      try{
        var emailModel = getPanelModel('model_email'); var bodyAnalyze = {}; if (emailModel !== 'auto') bodyAnalyze.model_override = emailModel; var res=await api('/ai/analyze-reply/'+id,{method:'POST', body: bodyAnalyze});
        if(res.success&&res.result){
          var d=res.result;
          var area=document.getElementById('vpAnalysisArea');
          var html='<div style="padding:10px 12px;background:#f0fdf6;border-radius:6px;font-size:12px"><b>AI analysis: </b>'+E(d.replyIntent||'?')+(d.sentimentScore?'（sentiment score: '+d.sentimentScore+'）':'')+(d.suggestedNextAction?'<br>Suggested: '+E(d.suggestedNextAction):'')+'</div>';
          if(d.draftSuggestion){
            document.getElementById('vpBody').innerHTML=cleanAiHtml(d.draftSuggestion);
            html+='<div style="font-size:11px;color:#16a34a">AI prefilled the reply draft</div>';
          }
          area.innerHTML=html;
          T('Analysis complete');
        }else{
          var errMsg = res.error || (res.result && res.result.error) || 'No response from backend';
          vpa.disabled=false;vpa.textContent='AI analyze this reply';
          var area2=document.getElementById('vpAnalysisArea');
          area2.innerHTML='<div style="padding:8px 12px;background:#fef5f5;border-radius:6px;font-size:12px;color:#dc2626">Analysis failed: '+E(errMsg)+'</div>';
          T('Analysis failed: '+E(errMsg),'#dc2626');
        }
      }catch(e){
        vpa.disabled=false;vpa.textContent='AI analyze this reply';
        var em = e.detail || e.message || String(e);
        var area3=document.getElementById('vpAnalysisArea');
        area3.innerHTML='<div style="padding:8px 12px;background:#fef5f5;border-radius:6px;font-size:12px;color:#dc2626">Analysis failed: '+E(em)+'</div>';
        T('Analysis failed: '+E(em),'#dc2626');
      }
    });

    var snd=document.getElementById('vpSend');
    if(snd)snd.addEventListener('click',async function(){
      snd.disabled=true; snd.textContent='Saving...';
      var to=document.getElementById('vpTo').value.trim();
      var subj=document.getElementById('vpSubj').value.trim();
      var bodyEl=document.getElementById('vpBody');
      var raw=bodyEl.innerHTML;
      // 保留有价值的 HTML（表格/段落/列表），只清富文本垃圾
      var cleanHtml = cleanRichHtml(raw);
      // 纯文本（用于校验非空 + AI 建议跟进日期）
      var clean = cleanHtml
        .replace(/<br\s*\/?>/gi,'\n')
        .replace(/<\/p>/gi,'\n')
        .replace(/<\/tr>/gi,'\n')
        .replace(/<[^>]+>/g,'')
        .replace(/&nbsp;/g,' ')
        .replace(/\n{3,}/g,'\n\n')
        .trim();
      if(!to||!clean){T('Enter recipient and body');snd.disabled=false;snd.textContent='Save as draft';return}
      var body = cleanHtml;
      var attJson = null;
      if (window._vpAttChosen && window._vpAttChosen.length > 0 && !window._vpAttSynced) {
        var fd2 = new FormData();
        window._vpAttChosen.forEach(function(f){ fd2.append('files', f); });
        try {
          var upRes = await authFetch('/api/email/upload-attachments', {method:'POST', body: fd2});
          if (!upRes.ok) { var et=await upRes.text(); try{et=JSON.parse(et).detail||et}catch(e){}; throw new Error(et); }
          var upJson = await upRes.json();
          if (upJson.success) {
            attJson = JSON.stringify(upJson.files);
            window._vpAttSynced = true;
          }
        } catch(e) { T('Attachment upload failed: '+(e.detail||e.message||''), '#dc2626'); snd.disabled=false;snd.textContent='Save as draft'; return; }
      }
      try{
        await api('/email/queue',{method:'POST',body:{prospect_id:pid||0,to_email:to,subject:subj,body:body,status:'draft',sender_key:getSenderKey('email_sender'),attachment_files:attJson||undefined}});
        var nf = document.getElementById('vpNextFollow');
        var followDate = nf ? nf.value : '';
        var followNote = '';
        // Auto-suggest next follow-up date via AI if not manually set
        if (!followDate && pid > 0 && clean.length > 20) {
          try {
            var fp = 'Based on the email draft below, suggest the best next follow-up date. Return only YYYY-MM-DD with no explanation.\n\nDraft:\n' + clean.substring(0, 1500) + '\n\nCustomer: ' + (prospect ? prospect.company : '') + '\n\nRule: hot reply 3-5 days, cold reply 7-10 days, quote/sample 1-2 days';
            var fr = await api('/ai/chat', {method:'POST', body:{prompt: fp, prospect_id: pid, voice:'human'}});
            var sd = (fr.result || '').trim();
            var m = sd.match(/(\d{4}-\d{2}-\d{2})/);
            if (m) { followDate = m[1]; followNote = '[Draft saved - AI suggestion] ' + followDate + ' follow up on customer feedback'; if (nf) nf.value = followDate; }
          } catch(e) {}
        }
        if (followDate && pid > 0) {
          if (!followNote) followNote = '[Hot reply - replied] Replied to email; follow up on time.';
          try { await api('/prospects/'+pid, {method:'PUT', body:{next_follow_date: followDate, reminder_note: followNote}}); } catch(e) {}
        }
        showDraftHint('Reply saved as draft' + (followDate ? ' · Next follow-up ' + followDate : ''));
        document.getElementById('vpMsk').remove();
        document.getElementById('vpWrap').remove();
      }catch(e){snd.disabled=false;snd.textContent='Save as draft';T('Save draft failed: '+(e.detail||e.message||''),'#dc2626')}
    });

    var vpQc = document.getElementById('vpQcBtn');
    if (vpQc) vpQc.addEventListener('click', function(){
      var subj = ((document.getElementById('vpSubj')||{}).value) || '';
      var raw = ((document.getElementById('vpBody')||{}).innerHTML) || '';
      var clean = raw.replace(/<br\s*\/?>/gi,'\n').replace(/<\/p>/gi,'\n').replace(/<[^>]+>/g,'').replace(/&nbsp;/g,' ').trim();
      window.runQualityCheck(subj, clean, pid||0);
    });

    var aiBtn=document.getElementById('vpAi');
    if(aiBtn)aiBtn.addEventListener('click',async function(){
      T('AI is generating a reply...');
      aiBtn.disabled=true;
      try{
        var ctx='Previous email: Subject: '+E(item.subject||'')+'\nBody: '+E(item.content||'').substring(0,500);
        if(prospect)ctx+='\n'+E(prospect.profile_type||'')+'\n';
        // 根据Customer email内容Auto选回复类型：Inquiry/要Quote → reply_quote，否则跟进
        var _inq = (item.content||'')+' '+(item.subject||'');
        var _lower = _inq.toLowerCase();
        var _isQuoteReq = /quote|quotation|pricing|price|Quote||provide a quote|moq|lead time|shipping cost/.test(_lower);
        var genBody = {message_type: _isQuoteReq ? 'reply_quote' : 'followup_signal', tone:'human', additional_context:ctx};
        var emailModel = getPanelModel('model_email');
        if(emailModel !== 'auto') genBody.model_override = emailModel;
        var res=await api('/ai/generate-message/'+pid,{method:'POST',body:genBody});
        if(res.success&&res.result){
          if(res.result.body){
            document.getElementById('vpBody').innerHTML=cleanAiHtml(res.result.body);
            // 本地确定性format（稳定、不改原文）
            try {
              var _fmt = formatEmailBody(res.result.body);
              if(_fmt) document.getElementById('vpBody').innerHTML = _fmt;
            } catch(e2){}
          }
          if(res.result.subject)document.getElementById('vpSubj').value='Re: '+E(item.subject||'');
          T('AI reply ready - review, then Save as draft or Confirm pending','#16a34a',5000);
        }else{
          var em2 = res.error || (res.result && res.result.error) || '';
          document.getElementById('vpAiDraftArea').innerHTML='<div style="font-size:11px;color:#dc2626">AI generation failed: '+E(em2)+'</div>';
          T('Generation failed'+(em2?': '+em2:''),'#dc2626');
        }
      }catch(e){
        aiBtn.disabled=false;
        var em3 = e.detail || e.message || String(e);
        document.getElementById('vpAiDraftArea').innerHTML='<div style="font-size:11px;color:#dc2626">AI generation failed: '+E(em3)+'</div>';
        T('Generation failed: '+E(em3),'#dc2626');
      }
    });

    var rvb=document.getElementById('vpReviseBtn');
    if(rvb)rvb.addEventListener('click',async function(){
      var inst=document.getElementById('vpReviseInput').value;
      if(!inst||!inst.trim()){T('Enter revision request');return}
      rvb.disabled=true;rvb.textContent='Revising...';
      try{
        var draftHtml=document.getElementById('vpBody').innerHTML;
        var draftText=draftHtml.replace(/<[^>]+>/g,'').trim();
        var reviseMsg='Customer email:\nSubject: '+E(item.subject||'')+'\n'+E(item.content||'').substring(0,1000)+'\n\n---\nCurrent draft:\n'+draftText.substring(0,2000)+'\n\nRevise the draft per these instructions. Output the full revised email body with no explanation and no "Here is the revised email" style preambles:\n'+inst;
        var emailModel=getPanelModel('model_email');
        var chatBody={prompt:reviseMsg,prospect_id:pid,voice:'human'};
        if(emailModel!=='auto')chatBody.model_override=emailModel;
        var res=await api('/ai/chat',{method:'POST',body:chatBody});
        rvb.disabled=false;rvb.textContent='EditDraft';
        if(res.success&&res.result){
          var newBody=typeof res.result==='string'?res.result:(res.result.text||res.result.body||'');
          if(newBody&&newBody.length>5){
            document.getElementById('vpBody').innerHTML=cleanAiHtml(newBody);
            document.getElementById('vpReviseInput').value='';
            T('Revised');
          }else{T('Revision failed: AI returned empty','#dc2626')}
        }else{T('Revision failed: '+(res.error||'no response'),'#dc2626')}
      }catch(e){rvb.disabled=false;rvb.textContent='EditDraft';T('Revision failed: '+(e.detail||e.message||''),'#dc2626')}
    });

    var chatM=document.getElementById('vpChatMsgs'),chatI=document.getElementById('vpChatInput'),chatS=document.getElementById('vpChatSend');
    if(chatM&&chatI&&chatS){
      chatM.innerHTML='<div style="color:#64748b;font-size:11px;font-style:italic">Customer and email context loaded - ask freely.</div>';
      chatS.addEventListener('click',async function(){
        var msg=chatI.value.trim();
        if(!msg)return;
        chatI.value='';
        var draftBody = document.getElementById('vpBody').innerHTML;
        var draftText = draftBody.replace(/<[^>]+>/g,'').trim();
        var fullMsg = 'Customer email:\nSubject: '+E(item.subject||'')+'\n'+E(item.content||'').substring(0,1000)+'\n\n---\n'+msg;
        if(draftText){
          fullMsg += '\n\nCurrent draft:\n'+draftText.substring(0,1500)+'\n\nRevise based on the customer email and current draft; output the full revised email body with no explanation.';
        }else{
          fullMsg += '\n\nReply based on the customer email; output the full email body with no explanation.';
        }
        chatM.innerHTML+='<div style="margin-bottom:3px;color:#4f46e5"><b>You: </b> '+E(msg)+'</div>';
        chatM.scrollTop=chatM.scrollHeight;
        var think=document.createElement('div');
        think.style.cssText='color:#64748b;font-size:11px';
        think.textContent='AI thinking...';
        chatM.appendChild(think);
        chatM.scrollTop=chatM.scrollHeight;
        try{
          var emailChatModel = getPanelModel('model_email'); var chatBody = {prompt: fullMsg, prospect_id: pid, voice: 'human'}; if (emailChatModel !== 'auto') chatBody.model_override = emailChatModel; var res=await api('/ai/chat',{method:'POST',body: chatBody});
          think.remove();
          if(res.success&&res.result){
            var replyDiv = document.createElement('div');
            replyDiv.style.cssText = 'margin-bottom:4px;padding:8px 10px;background:#f0fdf6;border-radius:6px;font-size:12px;border-left:3px solid #16a34a';
            replyDiv.textContent = res.result;
            var btnRow = document.createElement('div');
            btnRow.style.cssText = 'margin-top:6px';
            var applyBtn = document.createElement('button');
            applyBtn.className = 'btn btn-sm';
            applyBtn.style.cssText = 'background:#16a34a;padding:2px 10px;font-size:11px';
            applyBtn.textContent = 'Apply to draft';
            applyBtn.onclick = function(){
              document.getElementById('vpBody').innerText = replyDiv.textContent.replace('Apply to draft','').trim();
              T('Applied');
            };
            btnRow.appendChild(applyBtn);
            replyDiv.appendChild(btnRow);
            chatM.appendChild(replyDiv);
          }else{
            chatM.innerHTML+='<div style="color:#dc2626">AI reply failed</div>';
          }
        }catch(e){
          think.remove();
          chatM.innerHTML+='<div style="color:#dc2626">AI reply failed</div>';
        }
        chatM.scrollTop=chatM.scrollHeight;
        if(e.key==='Enter'&&!e.shiftKey){e.preventDefault();chatS.click();}
      });
    }
  }catch(e){T('Load failed','#dc2626')}
}
