// Audit log: owner views what members did

var AUDIT_ACTIONS = {
  login: 'Sign in', logout: 'Sign out', create_owner: 'Create owner account', create_user: 'Add member',
  update_user: 'Update member', delete_user: 'Delete member', update_prospect: 'Update customer',
  delete_prospect: 'Delete customer', assign_prospect: 'Assign customer', import_prospects: 'Import customers',
  send_email: 'Send email', user_export: 'Export data', user_restore: 'Restore data',
  view_prospect: 'View customer', ai_score: 'AI score', email_draft: 'Create email',
  kb_update: 'Update knowledge base'
};
var _auditFilter = { user_id: '', action: '' };

async function RAudit(p){
  p.innerHTML = '<div class="empty-state card">Loading...</div>';
  await _loadUsers();

  var qs = '?limit=200';
  if(_auditFilter.user_id) qs += '&user_id=' + _auditFilter.user_id;
  if(_auditFilter.action) qs += '&action=' + encodeURIComponent(_auditFilter.action);
  var rows = [];
  try{
    var r = await api('/audit/logs' + qs);
    rows = r.logs || [];
  }catch(e){
    p.innerHTML = '<div class="card tc p4" style="color:#dc2626">'+E(e.detail||e.message||String(e))+'</div>';
    return;
  }

  var h = '<div class="page-hd"><div><h2>Audit Log</h2><p class="page-sub">The owner can see what each member did: sign-ins, customer edits, assignments, exports / restores, and more.</p></div></div>';
  h += '<div class="card p3 mb3" style="display:flex;gap:8px;flex-wrap:wrap;align-items:center">';
  if(currentUser && currentUser.role !== 'member'){
    h += '<select id="auUser" style="max-width:160px"><option value="">All members</option>';
    Object.keys(usersMap).forEach(function(id){
      h += '<option value="'+id+'" '+(_auditFilter.user_id===id?'selected':'')+'>'+E(usersMap[id])+'</option>';
    });
    h += '</select>';
  }
  h += '<select id="auAction" style="max-width:180px"><option value="">All actions</option>';
  Object.keys(AUDIT_ACTIONS).forEach(function(k){
    h += '<option value="'+k+'" '+(_auditFilter.action===k?'selected':'')+'>'+AUDIT_ACTIONS[k]+'</option>';
  });
  h += '</select>';
  h += '<button class="btn btn-sm btn-pri" id="auQuery">Query</button>';
  h += '<button class="btn btn-sm btn-b" id="auReset">Reset</button>';
  h += '</div>';

  h += '<div class="card" style="overflow:hidden"><div style="padding:12px 16px;background:#f7f9fc;border-bottom:1px solid #e4e9f2;display:flex;align-items:center;gap:8px">';
  h += '<span class="dot" style="width:8px;height:8px;border-radius:50%;background:#0f172a"></span>';
  h += '<span class="fs14 fwb" style="color:#0f172a">Recent activity</span><span class="fs11 c6">'+rows.length+' records</span></div>';
  h += '<div style="padding:6px 12px">';
  if(!rows.length){
    h += '<div class="fs12 c6 tc" style="padding:20px">No records yet</div>';
  }else{
    h += '<table><thead><tr><th>Time</th><th>Member</th><th>Action</th><th>Target</th><th>Details</th></tr></thead><tbody>';
    rows.forEach(function(x){
      var who = x.user_id ? (usersMap[x.user_id] || ('Member #'+x.user_id)) : 'System';
      h += '<tr><td style="white-space:nowrap">'+E((x.created_at||'').replace('T',' ').substring(0,16))+'</td>';
      h += '<td>'+E(who)+'</td>';
      h += '<td>'+E(AUDIT_ACTIONS[x.action]||x.action)+'</td>';
      h += '<td>'+E(x.target||'')+'</td>';
      h += '<td>'+E(x.detail||'')+'</td></tr>';
    });
    h += '</tbody></table>';
  }
  h += '</div></div>';
  p.innerHTML = h;

  var qbtn = p.querySelector('#auQuery');
  if(qbtn) qbtn.addEventListener('click', function(){
    var u = p.querySelector('#auUser');
    var a = p.querySelector('#auAction');
    _auditFilter.user_id = u ? u.value : '';
    _auditFilter.action = a ? a.value : '';
    RAudit(p);
  });
  var rbtn = p.querySelector('#auReset');
  if(rbtn) rbtn.addEventListener('click', function(){
    _auditFilter = { user_id: '', action: '' };
    RAudit(p);
  });
}
