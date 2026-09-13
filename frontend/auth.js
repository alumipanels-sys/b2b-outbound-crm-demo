// ── 登录 / 首次创建主账号 ──

async function RLogin(p){
  p.innerHTML = '<div class="empty-state card">Checking system status…</div>';
  var initialized = true;
  var demoMode = false;
  try{
    var st = await api('/auth/status');
    initialized = !!st.initialized;
    demoMode = !!st.demo_mode;
  }catch(e){}

  var h = '<div style="max-width:420px;margin:8vh auto">';
  h += '<div class="card" style="padding:28px">';
 h += '<h2 style="font-size:18px;font-weight:700;margin-bottom:4px">B2B Outbound OS</h2>';
  h += '<p class="fs11 mb3" style="color:#6366f1">Self-Hosted Outbound CRM · See your outreach. Keep your customers.</p>';
  if(demoMode){
    h += '<div style="background:#eef2ff;border:1px solid #c7d2fe;border-radius:8px;padding:10px 12px;margin-bottom:14px;font-size:11px;line-height:1.8">'
      + '<b style="color:#4338ca">🎯 Demo accounts</b><br>'
      + 'Owner: <b>demo@demo.com</b> / demo123456<br>'
      + 'Sales: <b>alex@demo.com</b> / demo123456</div>';
  }
  if(initialized){
    h += '<p class="fs12 c6 mb3">Sign in to continue</p>';
    h += '<div class="mb2"><label class="fs11 c6">Email</label><input id="lgEmail" type="email" style="margin-top:2px"></div>';
    h += '<div class="mb2"><label class="fs11 c6">Password</label><input id="lgPass" type="password" style="margin-top:2px"></div>';
    h += '<button class="btn" style="background:#6366f1;width:100%" id="lgBtn">Sign in</button>';
    h += '<div class="mt2 tc"><a href="#" id="lgForgot" style="font-size:11px;color:#6366f1;text-decoration:none">Forgot password?</a></div>';
  }else{
    h += '<p class="fs12 c6 mb3">First run: create your owner account (owner can add members and see all data &amp; backups)</p>';
    h += '<div class="mb2"><label class="fs11 c6">Your name</label><input id="lgName" style="margin-top:2px"></div>';
    h += '<div class="mb2"><label class="fs11 c6">Email</label><input id="lgEmail" type="email" style="margin-top:2px"></div>';
    h += '<div class="mb2"><label class="fs11 c6">Password (at least 6 characters)</label><input id="lgPass" type="password" style="margin-top:2px"></div>';
    h += '<button class="btn" style="background:#16a34a;width:100%" id="lgBtn">Create owner account</button>';
  }
  h += '<div id="lgMsg" class="fs12 mt2" style="color:#dc2626"></div>';
  h += '<p class="fs11 c6 mt3 tc">Self-Hosted Outbound CRM · Your data stays on your own computer</p>';
  h += '</div></div>';
  p.innerHTML = h;

  var btn = p.querySelector('#lgBtn');
  if(btn) btn.addEventListener('click', async function(){
    var msg = p.querySelector('#lgMsg');
    msg.innerHTML = 'Processing…'; msg.style.color = '#64748b';
    var email = p.querySelector('#lgEmail').value.trim();
    var pass = p.querySelector('#lgPass').value;
    if(!email || !pass){ msg.innerHTML = 'Please enter your email and password'; msg.style.color = '#dc2626'; return; }
    try{
      var r;
      if(initialized){
        r = await api('/auth/login', {method:'POST', body:{email:email, password:pass}});
      }else{
        var name = p.querySelector('#lgName').value.trim();
        if(!name){ msg.innerHTML = 'Please enter your name'; msg.style.color = '#dc2626'; return; }
        r = await api('/auth/setup-owner', {method:'POST', body:{name:name, email:email, password:pass}});
      }
      doLogin(r.token, r.user, r.need_activation);
    }catch(e){
      msg.innerHTML = E(e.detail||e.message||String(e));
      msg.style.color = '#dc2626';
    }
  });

  var forgot = p.querySelector('#lgForgot');
  if(forgot) forgot.addEventListener('click', function(e){
    e.preventDefault();
    RForgotPassword(p);
  });
}

// ── 忘记密码：邮箱验证码找回 ──
async function RForgotPassword(p){
  var h = '<div style="max-width:420px;margin:8vh auto">';
  h += '<div class="card" style="padding:28px">';
  h += '<h2 style="font-size:18px;font-weight:700;margin-bottom:4px">Reset password</h2>';
  h += '<p class="fs12 c6 mb3">Enter your registered email; a verification code will be sent to it.</p>';
  h += '<div class="mb2"><label class="fs11 c6">Email</label><input id="fpEmail" type="email" style="margin-top:2px"></div>';
  h += '<div class="mb2"><label class="fs11 c6">Verification code</label><input id="fpCode" style="margin-top:2px"></div>';
  h += '<div class="mb2"><label class="fs11 c6">New password (at least 6 characters)</label><input id="fpPass" type="password" style="margin-top:2px"></div>';
  h += '<div class="flex g2 mb3">';
  h += '<button class="btn" style="background:#6366f1;flex:1" id="fpSend">Get code</button>';
  h += '<button class="btn" style="background:#16a34a;flex:1" id="fpReset">Reset password</button>';
  h += '</div>';
  h += '<div id="fpMsg" class="fs12" style="color:#dc2626"></div>';
  h += '<div class="mt3 tc"><a href="#" id="fpBack" style="font-size:11px;color:#6366f1;text-decoration:none">← Back to sign in</a></div>';
  h += '</div></div>';
  p.innerHTML = h;

  document.getElementById('fpBack').addEventListener('click', function(e){
    e.preventDefault();
    RLogin(p);
  });

  document.getElementById('fpSend').addEventListener('click', async function(){
    var msg = document.getElementById('fpMsg');
    var email = document.getElementById('fpEmail').value.trim();
    if(!email){ msg.innerHTML = 'Please enter your email'; return; }
    msg.innerHTML = 'Sending…'; msg.style.color = '#64748b';
    try{
      var r = await api('/auth/forgot-password', {method:'POST', body:{email:email}});
      msg.innerHTML = '✅ Code sent (valid for 10 minutes if this email was registered)'; msg.style.color = '#059669';
    }catch(e){
      msg.innerHTML = E(e.detail||e.message||String(e)); msg.style.color = '#dc2626';
    }
  });

  document.getElementById('fpReset').addEventListener('click', async function(){
    var msg = document.getElementById('fpMsg');
    var email = document.getElementById('fpEmail').value.trim();
    var code = document.getElementById('fpCode').value.trim();
    var pass = document.getElementById('fpPass').value;
    if(!email || !code || !pass){ msg.innerHTML = 'Please enter email, code and new password'; msg.style.color = '#dc2626'; return; }
    msg.innerHTML = 'Resetting…'; msg.style.color = '#64748b';
    try{
      await api('/auth/reset-password', {method:'POST', body:{email:email, code:code, password:pass}});
      msg.innerHTML = '✅ Password reset — sign in with your new password'; msg.style.color = '#059669';
      setTimeout(function(){ RLogin(p); }, 1200);
    }catch(e){
      msg.innerHTML = E(e.detail||e.message||String(e)); msg.style.color = '#dc2626';
    }
  });
}

// ── 交付版未激活锁屏：只显示激活页，输入激活码解锁 ──
async function RActivate(p){
  var lic = null;
  try{ lic = await api('/license/status'); }catch(e){}
  var h = '<div style="max-width:460px;margin:8vh auto">';
  h += '<div class="card" style="padding:28px;border-top:3px solid #f59e0b">';
 h += '<h2 style="font-size:18px;font-weight:700;margin-bottom:4px">B2B Outbound OS</h2>';
  h += '<p class="fs11 mb3" style="color:#6366f1">Self-Hosted Outbound CRM · See your outreach. Keep your customers.</p>';
  h += '<div style="background:#fffbeb;border:1px solid #fde68a;border-radius:8px;padding:12px;margin-bottom:16px;font-size:12px;line-height:1.8">'
    + '<b style="color:#b45309">🔒 System not activated</b><br>'
    + 'Enter the activation code provided by your vendor to unlock the system.'
    + (lic && lic.activate_by ? '<br><span class="fs11" style="color:#92400e">Activate by: '+E(lic.activate_by)+' (expires if missed)</span>' : '')
    + '</div>';
  if(lic && lic.license_company){
    h += '<div class="fs12 c6 mb3">Bound to: '+E(lic.license_company)+' ('+E(lic.license_max_users)+' accounts)</div>';
  }
  h += '<div class="mb2"><label class="fs11 c6">Activation code</label><input id="actKey" style="margin-top:2px"></div>';
  h += '<button class="btn" style="background:#f59e0b;width:100%" id="actBtn">Activate and enter</button>';
  h += '<div id="actMsg" class="fs12 mt2" style="color:#dc2626"></div>';
  h += '<p class="fs11 c6 mt3 tc">Activation code provided by your vendor · One-time license, no expiry</p>';
  h += '</div></div>';
  p.innerHTML = h;

  var btn = p.querySelector('#actBtn');
  if(btn) btn.addEventListener('click', async function(){
    var msg = p.querySelector('#actMsg');
    var key = p.querySelector('#actKey').value.trim();
    if(!key){ msg.innerHTML = 'Please enter the activation code'; return; }
    msg.innerHTML = 'Activating…'; msg.style.color = '#64748b';
    try{
      await api('/license/activate', {method:'POST', body:{license_key:key}});
      needActivation = false;
      T('Activated — welcome!','#16a34a');
      nav('today');
      showWelcomeGuide();
    }catch(e){
      msg.innerHTML = E(e.detail||e.message||String(e));
      msg.style.color = '#dc2626';
    }
  });
}
