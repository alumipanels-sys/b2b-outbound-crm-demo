var _stats = null;

function _loadStats(){
  return api('/prospects/stats').then(function(s){ _stats = s; }).catch(function(){ _stats = null; });
}

function prospectFilterQuery(){var s='';if(filters.sales_stage)s+='&sales_stage='+encodeURIComponent(filters.sales_stage);if(filters.source_channel)s+='&source_channel='+encodeURIComponent(filters.source_channel);if(filters.profile_type)s+='&profile_type='+encodeURIComponent(filters.profile_type);if(filters.profile_source)s+='&profile_source='+encodeURIComponent(filters.profile_source);if(filters.value_level)s+='&value_level='+encodeURIComponent(filters.value_level);if(filters.region)s+='&region='+encodeURIComponent(filters.region);if(filters.mine)s+='&mine=1';return s}
async function loadList(){_listLoaded=true;try{await _loadUsers();var u='/prospects?page='+page+'&limit=15'+prospectFilterQuery();if(filters.sort)u+='&sort='+encodeURIComponent(filters.sort)+'&order='+(filters.order||'desc');var r=await api(u);prospects=r.items;totalResults=r.total;totalPages=Math.ceil(r.total/15)||1;await _loadStats()}catch(e){prospects=[]}render()}
async function doSearch(q){_listLoaded=true;try{await _loadUsers();var u='/prospects?search='+encodeURIComponent(q)+'&limit=50'+prospectFilterQuery();if(filters.sort)u+='&sort='+encodeURIComponent(filters.sort)+'&order='+(filters.order||'desc');var r=await api(u);prospects=r.items;totalResults=r.total;totalPages=1}catch(e){prospects=[]}render()}
async function _loadUsers(){usersMap={};if(!currentUser||currentUser.role==='member')return;try{var ur=await api('/auth/users');(ur.users||[]).forEach(function(u){usersMap[u.id]=u.name});}catch(e){}}
// ── Status color helper ──
function _rowColor(x){
  if (x.email_status === 'bounced' || x.email_status === 'bounced_risk') return {bar:'#dc2626', bg:'#fef2f2', label:'Bounced'};
  if (x.sales_stage === 'won') return {bar:'#7c3aed', bg:'#faf5ff', label:'Won'};
  if (x.sales_stage === 'lost') return {bar:'#9ca3af', bg:'#f9fafb', label:'Lost'};
  if (x.sales_stage === 'cooling') return {bar:'#8b5cf6', bg:'#faf5ff', label:'Cooling'};
  if (x.sales_stage === 'testing' || x.sales_stage === 'sample_sent' || x.sales_stage === 'feedback' || x.sales_stage === 'sample_pending') return {bar:'#f59e0b', bg:'#fffbeb', label:'Samples'};
  if (x.sales_stage === 'replied' || x.sales_stage === 'interested') return {bar:'#16a34a', bg:'#ecfdf5', label:'Replied'};
  if (x.sales_stage === 'trial_order') return {bar:'#0891b2', bg:'#ecfeff', label:'Trial order'};
  if (x.value_level === 'HIGH') return {bar:'#2563eb', bg:'#eff6ff', label:'High value'};
  if (x.interaction_count === 0) return {bar:'#f97316', bg:'#fff7ed', label:'Waiting'};
  return {bar:'#d1d5db', bg:'#fff', label:''};
}

function _renderStat(label, val, color, icon, filter){
  var onclick = filter ? " onclick=\"filters.sales_stage='"+filter+"';page=1;loadList()\"" : "";
  return '<div class=\"stat-card\" style=\"--stat-color:'+color+'\"'+onclick+'>'
    + '<div class=\"stat-label\">'+label+'</div>'
    + '<div class=\"stat-value-wrapper\"><span class=\"stat-value\">'+E(val)+'</span></div>'
    + '</div>';
}

function RList(p){
  var h = '<div class="page-hd"><div><h2>Customer List <span style="font-weight:400;color:#64748b;font-size:14px">'+totalResults+'</span></h2><p class="page-sub">Check core pools first — click a number to filter, or use search to find customers.</p></div>'
    + '<button class="btn btn-pri" onclick="nav(\'import\')">＋ Add Customer</button></div>';

  // Core pools
  h += '<div id="statsRow" style="display:flex;gap:10px;margin-bottom:18px;flex-wrap:wrap">';
  if (_stats) {
    h += _renderStat('New today', _stats.today_new || 0, '#10b981', '', '__today__');
    h += _renderStat('Waiting', _stats.pool_waiting || 0, '#f97316', '', '__waiting__');
    h += '<div class="stat-card" style="--stat-color:#6366f1" onclick="filters.sales_stage=\'touched\';filters.sort=\'last_sent\';filters.order=\'desc\';page=1;loadList()">'
      + '<div class="stat-label">Cold emails sent</div>'
      + '<div class="stat-value-wrapper"><span class="stat-value">'+( _stats.touched||0)+'</span></div>'
      + '<div class="fs11" style="color:#64748b;margin-top:2px">Sorted by send time</div></div>';
    h += _renderStat('Following up', _stats.pool_following || 0, '#2563eb', '', '__following__');
    h += _renderStat('Due today', _stats.need_follow, '#dc2626', '', '__follow__');
    h += _renderStat('Replied', _stats.replied+_stats.interested, '#16a34a', '', '__replied__');
    h += '<div class="stat-card" style="--stat-color:#0ea5e9" onclick="filters.sales_stage=\'__recent__\';filters.sort=\'last_edited_at\';filters.order=\'desc\';page=1;loadList()">'
      + '<div class="stat-label">Recently edited</div>'
      + '<div class="stat-value-wrapper"><span class="stat-value">'+(_stats.recent_modified||0)+'</span></div>'
      + '<div class="fs11" style="color:#64748b;margin-top:2px">Customers touched within 30 days</div></div>';
    h += _renderStat('Samples / testing', _stats.sample_active, '#f59e0b', '', '__sample__');
    h += _renderStat('Trial orders', _stats.trial, '#0891b2', '', 'trial_order');
    h += _renderStat('Won', _stats.won, '#7c3aed', '', 'won');
    h += _renderStat('Total', _stats.total, '#2563eb', '', '__all__');
  } else {
    h += '<div style="color:#64748b;font-size:12px;padding:10px">Loading stats...</div>';
  }
  h += '</div>';

  // Search + advanced filters
  h += '<div class="card p3" style="margin-bottom:16px;background:#f8fafc">';
  h += '<div class="flex g2 aic"><input id="searchBox" placeholder="Search company, contact, country, email..." style="flex:1;max-width:520px;height:34px"><button class="btn btn-sm btn-pri" id="searchBtn" style="height:34px;padding:0 20px">Search</button><button class="btn btn-sm btn-b" id="advToggle" style="height:34px">Filters ▾</button><button class="btn btn-sm btn-b" id="clearBtn" style="height:34px">Reset</button><span style="flex:1"></span>'+renderModelSelector('model_list','Scoring model')+'<button class="btn btn-sm btn-b" id="selectAllBtn" onclick="selectAllScores()">☑ Select page</button><button class="btn btn-sm" style="background:#7c3aed" id="batchScoreBtn">Batch score</button><button class="btn btn-sm" style="background:#6366f1" id="batchVerifyBtn">Verify emails</button></div>';
  h += '<div id="advFilter" class="flex g2 fw aic" style="margin-top:12px;padding-top:12px;border-top:1px dashed #d7dee8;display:none">';
  var salesStages = {new:'New',touched:'Cold email sent',connected:'Connected',replied:'Replied',interested:'Interested',sample_pending:'Sample pending',sample_sent:'Sample sent',testing:'Testing',feedback:'Feedback',trial_order:'Trial order',won:'Won',lost:'Lost',cooling:'Cooling'};
  h += '<select id="fStage" style="padding:7px 12px;border:1px solid #d1d5db;border-radius:6px;font-size:13px;color:#334155;background:#fff"><option value="">All stages</option>';
  // Special pools at top
  h += '<option value="__waiting__" '+(filters.sales_stage==='__waiting__'?'selected':'')+'>Waiting</option>';
  h += '<option value="__drafts__" '+(filters.sales_stage==='__drafts__'?'selected':'')+'>Drafts pending</option>';
  h += '<option value="__following__" '+(filters.sales_stage==='__following__'?'selected':'')+'>Following up</option>';
  h += '<option value="__need_nfd__" '+(filters.sales_stage==='__need_nfd__'?'selected':'')+'>Needs scheduling</option>';
  h += '<option value="__follow__" '+(filters.sales_stage==='__follow__'?'selected':'')+'>Due today</option>';
  h += '<option value="__today__" '+(filters.sales_stage==='__today__'?'selected':'')+'>New today</option>';
  h += '<option value="__cooling__" '+(filters.sales_stage==='__cooling__'?'selected':'')+'>Cooling customers</option>';
  h += '<option value="__recent__" '+(filters.sales_stage==='__recent__'?'selected':'')+'>Recently edited</option>';
  h += '<option value="__bounce__" '+(filters.sales_stage==='__bounce__'?'selected':'')+'>Bounced</option>';
  h += '<option value="__all__" '+(filters.sales_stage==='__all__'?'selected':'')+'>All customers</option>';
  h += '<option disabled>── By stage ──</option>';
  Object.keys(salesStages).forEach(function(k){ h += '<option value="'+k+'" '+(filters.sales_stage===k?'selected':'')+'>'+salesStages[k]+'</option>'; });
  h += '</select>';
  h += '<select id="fProfile" style="padding:7px 12px;border:1px solid #d1d5db;border-radius:6px;font-size:13px;color:#334155;background:#fff"><option value="">All profiles</option>';
  profileCatKeys().forEach(function(v){ h += '<option value="'+v+'" '+(filters.profile_type===v?'selected':'')+'>'+E(profileCatLabel(v))+'</option>'; });
  h += '<option value="EXCLUDE" '+(filters.profile_type==='EXCLUDE'?'selected':'')+'>Excluded</option>';
  h += '</select>';
  h += '<select id="fRegion" style="padding:7px 12px;border:1px solid #d1d5db;border-radius:6px;font-size:13px;color:#334155;background:#fff"><option value="">All regions</option>';
  [['europe','Europe'],['middle_east','Middle East'],['asia','Asia'],['americas','Americas'],['africa','Africa'],['oceania','Oceania'],['other','Other']].forEach(function(v){ h += '<option value="'+v[0]+'" '+(filters.region===v[0]?'selected':'')+'>'+v[1]+'</option>'; });
  h += '</select>';
  h += '<select id="fValue" style="padding:7px 12px;border:1px solid #d1d5db;border-radius:6px;font-size:13px;color:#334155;background:#fff"><option value="">All values</option>';
  ['HIGH','MID','LOW','EXCLUDE'].forEach(function(v){ h += '<option value="'+v+'" '+(filters.value_level===v?'selected':'')+'>'+v+'</option>'; });
  h += '</select>';
  h += '<select id="fSourceCh" style="padding:7px 12px;border:1px solid #d1d5db;border-radius:6px;font-size:13px;color:#334155;background:#fff"><option value="">All sources</option>';
  ['LinkedIn','Email','Google','Google Maps','Trade Show','Industry Directory','Referral','Website','WhatsApp','Existing Customer','Other'].forEach(function(v){ h += '<option value="'+v+'" '+(filters.source_channel===v?'selected':'')+'>'+v+'</option>'; });
  h += '</select>';
  h += '<select id="fProfileSrc" style="padding:7px 12px;border:1px solid #d1d5db;border-radius:6px;font-size:13px;color:#334155;background:#fff"><option value="">Profile source</option><option value="manual">Manual</option><option value="ai">AI guess</option></select>';
  if(!currentUser || currentUser.role!=='member'){ h += '<select id="fMine" style="padding:7px 12px;border:1px solid #d1d5db;border-radius:6px;font-size:13px;color:#334155;background:#fff"><option value="">All customers</option><option value="1" '+(filters.mine==='1'?'selected':'')+'>My customers</option></select>'; }
  h += '<select id="fSort" style="padding:7px 12px;border:1px solid #d1d5db;border-radius:6px;font-size:13px;color:#334155;background:#fff;margin-left:auto"><option value="">Default sort</option><option value="next_follow_date" '+(filters.sort==='next_follow_date'?'selected':'')+'>Next follow-up</option><option value="created_at" '+(filters.sort==='created_at'?'selected':'')+'>Created</option><option value="ai_score" '+(filters.sort==='ai_score'?'selected':'')+'>Score</option></select>';
  h += '</div></div>';

  if(!prospects.length){ h += '<div class="empty-state card">No data yet</div>'; }
  else{
    // One row per company: group by company, first record represents it
    var groupMap = {};
    var groups = [];
    prospects.forEach(function(x){
      var key = (x.company || '').trim() || ('__' + x.id);
      if (!groupMap[key]) { groupMap[key] = []; groups.push(groupMap[key]); }
      groupMap[key].push(x);
    });
    groups.forEach(function(group){
      var x = group[0];
      group.forEach(function(g){ if (!x.decision_maker && g.decision_maker) x = g; });
      var contactNames = group.map(function(g){ return g.contact; }).filter(Boolean);
      var contactLabel = contactNames.length ? contactNames.slice(0,3).join(', ') + (contactNames.length>3?' +'+ (contactNames.length-3) +' more':'') : '';
      var groupCount = group.length;
      var col = _rowColor(x);
      var stageLabel = ({new:'New',touched:'Cold email sent',connected:'Connected',replied:'Replied',interested:'Interested',sample_pending:'Sample pending',sample_sent:'Sample sent',testing:'Testing',feedback:'Feedback',trial_order:'Trial order',won:'Won',lost:'Lost',cooling:'Cooling'})[x.sales_stage||'new'] || (x.sales_stage||'-');
      var sc = x.ai_score!=null ? Math.round(x.ai_score) : null;
      var isNew = (x.sales_stage||'new')==='new' && !x.ai_score;
      var countryFlag = {DE:'DE',US:'US',CH:'CH',AT:'AT',IN:'IN',TR:'TR',GB:'GB',JP:'JP',KR:'KR',FR:'FR',IT:'IT',RU:'RU',BR:'BR',CZ:'CZ',PL:'PL',NL:'NL',ES:'ES',AU:'AU',CA:'CA',SE:'SE',IL:'IL',AE:'AE',SA:'SA',VN:'VN',ID:'ID',TH:'TH',MY:'MY',PH:'PH',MX:'MX',ZA:'ZA',EG:'EG',NZ:'NZ',SG:'SG'};

      // Stage pill color
      var stageBg = {
        'Replied':'#059669','Interested':'#059669','Won':'#a78bfa',
        'Trial order':'#22d3ee','Sample pending':'#f59e0b','Sample sent':'#f59e0b',
        'Testing':'#fbbf24','Feedback':'#c084fc',
        'Cold email sent':'#6366f1','Connected':'#6366f1',
        'New':'#64748b','Lost':'#475569','Cooling':'#a78bfa'
      }[stageLabel] || '#64748b';

      h += '<div class="prospect-row" style="border-left:3px solid '+col.bar+'" data-open="'+x.id+'">';

      // ── Checkbox (batch select) ──
      h += '<div style="flex-shrink:0"><input type="checkbox" class="scoreCheck" value="'+x.id+'" style="width:16px;height:16px;cursor:pointer;accent-color:#7c3aed" onclick="event.stopPropagation()"></div>';

      // ── Company ──
      h += '<div style="flex:3;min-width:0">';
      h += '<div class="fwb" style="font-size:14px;color:#0f172a;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">';
      h += E(x.company||'');
      if (/外链|external|backlink/.test((x.source||'') + (x.source_channel||'') + (x.development_batch||''))) {
        h += ' <span class="badge" style="background:#dbeafe;color:#1d4ed8;font-size:10px;vertical-align:middle">External link</span>';
      }
      h += ' <span style="font-size:11px;color:#64748b;font-weight:400">'+E(x.country||'')+'</span>';
      h += '</div>';
      h += '<div style="font-size:11px;color:#94a3b8;margin-top:2px;display:flex;align-items:center;gap:6px;flex-wrap:wrap">';
      if (contactLabel) { h += '<span>'+E(contactLabel)+'</span>'; h += '<span style="color:#d1d5db">·</span>'; }
      if (groupCount > 1) h += '<span style="background:#eef2ff;color:#3730a3;font-size:10px;padding:1px 6px;border-radius:8px;font-weight:600">'+groupCount+' contacts</span>';
      if (x.source) { h += '<span>'+E(x.source)+'</span>'; h += '<span style="color:#d1d5db">·</span>'; }
      h += '<span style="background:'+stageBg+';color:#fff;font-size:9px;padding:1px 6px;border-radius:3px;font-weight:500">'+stageLabel+'</span>';
      if (x.profile_type) h += '<span style="font-size:10px;color:#6366f1;font-weight:600">'+E(x.profile_type)+'</span>';
      if (x.value_level === 'HIGH') h += '<span style="background:#fef3c7;color:#92400e;font-size:9px;padding:1px 5px;border-radius:3px;font-weight:600">HIGH</span>';
      if (sc != null) h += '<span style="color:#d1d5db">·</span><span>Score '+sc+'</span>';
      if(currentUser && currentUser.role!=='member'){
        h += '<span style="color:#d1d5db">·</span><span title="Owner">👤 '+E(usersMap[x.owner_user_id]||'Unassigned')+'</span>';
        h += '<select class="assignSel" data-pid="'+x.id+'" onclick="event.stopPropagation()" style="font-size:10px;padding:1px 4px;border:1px solid #d1d5db;border-radius:3px;max-width:110px"><option value="">Assign...</option>';
        Object.keys(usersMap).forEach(function(id){
          h += '<option value="'+id+'" '+(String(x.owner_user_id)===id?'selected':'')+'>'+E(usersMap[id])+'</option>';
        });
        h += '</select>';
      }
      h += '</div>';
      h += '</div>';

      // ── Quick info ──
      h += '<div style="flex:1;text-align:right;font-size:11px;color:#64748b">';
      if (x.next_follow_date) h += '<div>Next follow-up '+x.next_follow_date.substring(0,10)+'</div>';
      if (x.next_follow_reason) h += '<div style="color:#94a3b8;max-width:230px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap" title="'+E(x.next_follow_reason)+'">📌 '+E(x.next_follow_reason)+'</div>';
      if (x.created_at) h += '<div style="color:#94a3b8">Created '+fd(x.created_at).substring(0,10)+'</div>';
      h += '</div>';

      h += '</div>';
    });
  }

  // Pagination
  if (totalPages > 1) {
    h += '<div style="display:flex;justify-content:center;gap:6px;margin-top:16px">';
    h += '<button class="btn btn-sm btn-b" '+(page<=1?'disabled':'')+' onclick="page=1;loadList()">First</button>';
    h += '<button class="btn btn-sm btn-b" '+(page<=1?'disabled':'')+' onclick="page--;loadList()">Prev</button>';
    h += '<span style="padding:4px 12px;font-size:12px;color:#64748b">Page '+page+' / '+totalPages+'</span>';
    h += '<button class="btn btn-sm btn-b" '+(page>=totalPages?'disabled':'')+' onclick="page++;loadList()">Next</button>';
    h += '<button class="btn btn-sm btn-b" '+(page>=totalPages?'disabled':'')+' onclick="page=totalPages;loadList()">Last</button>';
    h += '</div>';
  }

  p.innerHTML = h;

  // ── Bind events ──
  bindSafe(p, '#advToggle', 'click', function(){
    var box = document.getElementById('advFilter');
    var on = box.style.display !== 'none';
    box.style.display = on ? 'none' : 'flex';
    this.textContent = on ? 'Filters ▾' : 'Filters ▴';
  });
  bindSafe(p, '#searchBtn', 'click', function(){ page=1; doSearch(document.getElementById('searchBox').value); });
  bindSafe(p, '#searchBox', 'keydown', function(e){ if(e.key==='Enter'){ page=1; doSearch(document.getElementById('searchBox').value); } });
  bindSafe(p, '#clearBtn', 'click', function(){ document.getElementById('searchBox').value=''; filters={status:'',sales_stage:'',source_channel:'',profile_type:'',profile_source:'',value_level:'',kbCat:'',sort:'',order:'desc'}; page=1; loadList(); });
  bindSafe(p, '#fStage', 'change', function(){ filters.sales_stage=this.value; page=1; loadList(); });
  bindSafe(p, '#fProfile', 'change', function(){ filters.profile_type=this.value; page=1; loadList(); });
  bindSafe(p, '#fValue', 'change', function(){ filters.value_level=this.value; page=1; loadList(); });
  bindSafe(p, '#fRegion', 'change', function(){ filters.region=this.value; page=1; loadList(); });
  bindSafe(p, '#fSourceCh', 'change', function(){ filters.source_channel=this.value; page=1; loadList(); });
  bindSafe(p, '#fProfileSrc', 'change', function(){ filters.profile_source=this.value; page=1; loadList(); });
  bindSafe(p, '#fMine', 'change', function(){ filters.mine=this.value; page=1; loadList(); });
  bindSafe(p, '#fSort', 'change', function(){ filters.sort=this.value; page=1; loadList(); });
  p.querySelectorAll('.assignSel').forEach(function(sel){
    sel.addEventListener('change', async function(){
      var pid = sel.dataset.pid;
      var val = sel.value ? parseInt(sel.value, 10) : null;
      try{
        await api('/prospects/'+pid+'/assign', {method:'POST', body:{owner_user_id:val}});
        T(val ? 'Customer assigned' : 'Assignment removed', '#16a34a');
        loadList();
      }catch(e){ T(E(e.detail||e.message||String(e)),'#dc2626'); loadList(); }
    });
  });
  bindSafe(p, '#batchScoreBtn', 'click', async function(){
    var ids = [];
    document.querySelectorAll('.scoreCheck:checked').forEach(function(cb){ ids.push(parseInt(cb.value)); });
    if (!ids.length){ T('Select customers first', '#f59e0b'); return; }
    var btn = document.getElementById('batchScoreBtn');
    btn.disabled = true; btn.textContent = 'Scoring...';
    try {
      var r = await api('/ai/score/batch', {method:'POST', body:{prospect_ids:ids}});
      T('Batch scoring done: '+r.scored+'/'+r.total+' succeeded', '#16a34a');
      loadList();
    } catch(e) { T('Scoring failed: '+(e.detail||e.message||''), '#dc2626'); }
    btn.disabled = false; btn.textContent = 'Score selected';
  });
  bindSafe(p, '#batchVerifyBtn', 'click', function(){
    var ids = prospects.map(function(x){ return x.id; });
    batchVerifyEmails(ids, document.getElementById('batchVerifyBtn'));
  });

  // Click rows to open drawer
  p.querySelectorAll('.prospect-row').forEach(function(row){
    row.addEventListener('click', function(e){
      if (e.target.tagName === 'BUTTON' || e.target.tagName === 'SELECT' || e.target.tagName === 'INPUT') return;
      var id = parseInt(row.dataset.open);
      if (typeof openDrawer === 'function') openDrawer(id);
    });
  });

  // Stat cards use inline onclick — no JS override needed
}

// ── Batch select helpers ──
function selectAllScores(){
  document.querySelectorAll('.scoreCheck').forEach(function(cb){ cb.checked = true; });
}
