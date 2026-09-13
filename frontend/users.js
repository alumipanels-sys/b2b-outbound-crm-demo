// User management (owner / admin)

async function RUsers(p){
  p.innerHTML = '<div class="empty-state card">Loading...</div>';
  var lic = null;
  try{ lic = await api('/license/status'); }catch(e){}
  var data;
  try{
    data = await api('/auth/users');
  }catch(e){
    p.innerHTML = '<div class="card tc p4" style="color:#dc2626">Unable to load member list: '+E(e.detail||e.message||String(e))+'</div>';
    return;
  }
  var users = data.users || [];

  var h = '<div class="page-hd"><div><h2>User Management</h2><p class="page-sub">The owner can add / disable member accounts and see everyone\'s activity (audit log).</p></div></div>';

  if(lic){
    h += '<div class="card p3 mb3" style="border-top:2px solid #7c3aed">';
    h += '<div class="flex aic g2 mb2"><span class="dot" style="width:8px;height:8px;border-radius:50%;background:#7c3aed"></span><span class="fs14 fwb" style="color:#0f172a">License status</span></div>';
    if(lic.activated && lic.valid){
      h += '<div class="fs12 mb1">Company: <b>'+E(lic.company)+'</b> · Plan: '+E(lic.plan)+' · Account limit: <b>'+lic.max_users+'</b>'+(lic.expires?' · Expires: '+E(lic.expires):'')+'</div>';
      h += '<div class="fs11" style="color:#16a34a">✓ Activated ('+E(lic.license_company||'')+' · '+lic.license_max_users+' accounts)</div>';
    }else if(lic.activated && !lic.valid){
      h += '<div class="fs12" style="color:#dc2626">Activation code invalid: '+E(lic.error||'')+'</div>';
    }else{
      h += '<div class="fs12 c6 mb2">Not activated yet. Activation unlocks accounts by count.</div>';
      if(currentUser && currentUser.role === 'owner'){
        h += '<div class="flex g2"><input id="licKey" placeholder="Paste activation code" style="max-width:420px"><button class="btn btn-sm" style="background:#7c3aed" id="licActivate">Activate</button> <span id="licMsg" class="fs11 c6"></span></div>';
      }
    }
    h += '</div>';
  }

  h += '<div class="card p3 mb3" style="border-top:2px solid #2563eb">';
  h += '<div class="flex aic g2 mb2"><span class="dot" style="width:8px;height:8px;border-radius:50%;background:#2563eb"></span><span class="fs14 fwb" style="color:#0f172a">Add member</span></div>';
  h += '<div class="grid gcol2 g2 mb2">';
  h += '<div><label class="fs11 c6">Name</label><input id="usName" style="margin-top:2px"></div>';
  h += '<div><label class="fs11 c6">Email</label><input id="usEmail" type="email" style="margin-top:2px"></div>';
  h += '<div><label class="fs11 c6">Password (at least 6 characters)</label><input id="usPass" type="password" style="margin-top:2px"></div>';
  h += '<div><label class="fs11 c6">Role</label><select id="usRole" style="margin-top:2px"><option value="member">Member</option><option value="admin">Admin</option></select></div>';
  h += '</div>';
  h += '<button class="btn btn-sm" style="background:#2563eb" id="usAdd">Add</button> <span id="usMsg" class="fs11 c6"></span>';
  h += '</div>';

  h += '<div class="card" style="overflow:hidden">';
  h += '<div style="padding:12px 16px;background:#f7f9fc;border-bottom:1px solid #e4e9f2;display:flex;align-items:center;gap:8px">';
  h += '<span class="dot" style="width:8px;height:8px;border-radius:50%;background:#0f172a"></span>';
  h += '<span class="fs14 fwb" style="color:#0f172a">Member list</span><span class="fs11 c6">'+users.length+' accounts</span></div>';
  h += '<div style="padding:6px 16px">';
  users.forEach(function(u){
    var roleTxt = ({owner:'Owner', admin:'Admin', member:'Member'})[u.role] || u.role;
    var statusTxt = u.status === 'active' ? 'Active' : (u.status === 'deleted' ? 'Deleted' : 'Disabled');
    h += '<div class="flex aic jcs fw g2" style="padding:11px 0;border-bottom:1px solid #f1f5f9">';
    h += '<div><b class="fs13">'+E(u.name)+'</b> <span class="badge" style="background:#e0e7ff;color:#3730a3">'+roleTxt+'</span>';
    h += '<div class="fs11 c6">'+E(u.email)+' · '+statusTxt+(u.last_login_at ? ' · last login '+E(u.last_login_at) : '')+'</div></div>';
    h += '<div class="flex g2">';
    h += '<button class="btn btn-sm btn-b" data-us-sig="'+u.id+'" data-sig="'+encodeURIComponent(u.email_signature||'')+'" title="Set this member\'s email signature">Signature</button>';
    if(u.role !== 'owner'){
      h += '<button class="btn btn-sm btn-b" data-us-pass="'+u.id+'">Reset password</button>';
      h += '<button class="btn btn-sm btn-b" data-us-role="'+u.id+'" data-role="'+(u.role==='admin'?'member':'admin')+'">'+(u.role==='admin'?'Set as member':'Set as admin')+'</button>';
      h += '<button class="btn btn-sm" style="background:'+(u.status==='active'?'#f59e0b':'#16a34a')+'" data-us-status="'+u.id+'" data-next="'+(u.status==='active'?'disabled':'active')+'">'+(u.status==='active'?'Disable':'Enable')+'</button>';
      if(u.status !== 'deleted'){
        h += '<button class="btn btn-sm" style="background:#dc2626" data-us-del="'+u.id+'">Delete</button>';
      }
    }
    h += '</div></div>';
  });
  h += '</div></div>';
  p.innerHTML = h;
  wireUsers(p);
}

function wireUsers(p){
  var act = p.querySelector('#licActivate');
  if(act) act.addEventListener('click', async function(){
    var inp = p.querySelector('#licKey');
    var msg = p.querySelector('#licMsg');
    if(!inp || !inp.value.trim()){ if(msg){msg.innerHTML='Paste an activation code';msg.style.color='#dc2626';} return; }
    try{
      await api('/license/activate', {method:'POST', body:{license_key: inp.value.trim()}});
      T('Activated','#16a34a');
      RUsers(p);
    }catch(e){ if(msg){msg.innerHTML=E(e.detail||e.message||String(e));msg.style.color='#dc2626';} }
  });
  var add = p.querySelector('#usAdd');
  if(add) add.addEventListener('click', async function(){
    var msg = p.querySelector('#usMsg');
    var body = {
      name: p.querySelector('#usName').value.trim(),
      email: p.querySelector('#usEmail').value.trim(),
      password: p.querySelector('#usPass').value,
      role: p.querySelector('#usRole').value
    };
    if(!body.name || !body.email || !body.password){ if(msg){msg.innerHTML='Please complete all fields';msg.style.color='#dc2626';} return; }
    try{
      await api('/auth/users', {method:'POST', body:body});
      T('Member added','#16a34a');
      RUsers(p);
    }catch(e){ if(msg){msg.innerHTML=E(e.detail||e.message||String(e));msg.style.color='#dc2626';} }
  });

  p.querySelectorAll('[data-us-pass]').forEach(function(b){
    b.addEventListener('click', async function(){
      var pw = prompt('Enter a new password (at least 6 characters)');
      if(!pw) return;
      try{ await api('/auth/users/'+b.dataset.usPass, {method:'PATCH', body:{password:pw}}); T('Password reset','#16a34a'); }
      catch(e){ T(E(e.detail||e.message||String(e)),'#dc2626'); }
    });
  });
  p.querySelectorAll('[data-us-sig]').forEach(function(b){
    b.addEventListener('click', async function(){
      var cur = '';
      try{ cur = decodeURIComponent(b.dataset.sig || ''); }catch(e){}
      var sig = prompt(
        'Set this member\'s email signature (placeholders supported: {{USER_NAME}} {{USER_EMAIL}} {{COMPANY}} {{WEBSITE}}):\n\n'
        + 'Example:\n{{USER_NAME}} | Sales Manager\n{{COMPANY}}\n{{USER_EMAIL}} | {{WEBSITE}}\n\n'
        + 'Leave blank to use the company default signature',
        cur
      );
      if(sig === null) return;
      try{
        await api('/auth/users/'+b.dataset.usSig, {method:'PATCH', body:{email_signature: sig.trim()}});
        T('Signature saved', '#16a34a');
        RUsers(p);
      }catch(e){ T('Save failed: '+(e.detail||e.message||''), '#dc2626'); }
    });
  });
  p.querySelectorAll('[data-us-role]').forEach(function(b){
    b.addEventListener('click', async function(){
      try{ await api('/auth/users/'+b.dataset.usRole, {method:'PATCH', body:{role:b.dataset.role}}); T('Role updated','#16a34a'); RUsers(p); }
      catch(e){ T(E(e.detail||e.message||String(e)),'#dc2626'); }
    });
  });
  p.querySelectorAll('[data-us-status]').forEach(function(b){
    b.addEventListener('click', async function(){
      try{ await api('/auth/users/'+b.dataset.usStatus, {method:'PATCH', body:{status:b.dataset.next}}); T('Updated','#16a34a'); RUsers(p); }
      catch(e){ T(E(e.detail||e.message||String(e)),'#dc2626'); }
    });
  });
  p.querySelectorAll('[data-us-del]').forEach(function(b){
    b.addEventListener('click', async function(){
      if(!confirm('Delete this member? Their data is kept and can be transferred later.')) return;
      try{ await api('/auth/users/'+b.dataset.usDel, {method:'DELETE'}); T('Deleted','#16a34a'); RUsers(p); }
      catch(e){ T(E(e.detail||e.message||String(e)),'#dc2626'); }
    });
  });
}
