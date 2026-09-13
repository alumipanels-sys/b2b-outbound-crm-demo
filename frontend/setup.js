// ── First-run Setup Wizard ──
// 客户自己配置：公司信息 / AI Key / SMTP / IMAP / 通知 / 发信节奏

var _setupStatus = null;

async function RSetup(p){
  if(currentUser && currentUser.role === 'member'){
    p.innerHTML = '<div class="card tc p4" style="color:#64748b;padding:48px">System Settings is only available to the owner/admin.<br><span class="fs12 c6">If needed, ask the owner to do it.</span></div>';
    return;
  }
  p.innerHTML = '<div class="empty-state card">Reading configuration status...</div>';
  var status;
  try{
    status = await api('/setup/status');
  }catch(e){
    p.innerHTML = '<div class="card tc" style="color:#dc2626;padding:40px">Unable to read configuration: '+E(e.detail||e.message||String(e))+'</div>';
    return;
  }
  _setupStatus = status;

  var steps = status.steps || [];
  var doneCount = steps.filter(function(s){return s.done}).length;
  var h = '<h2 class="fs20 fwb mb2">System Settings Wizard</h2>';
  h += '<p class="fs12 c6 mb3">Configure in order; once complete the system is ready. Keys stay in the local .env and are never uploaded.</p>';
  h += '<p class="fs11 mb3" style="color:#b45309;background:#fffbeb;border:1px solid #fde68a;border-radius:6px;padding:8px 10px">Note: AI / SMTP / IMAP changes take effect after <b>restarting the system</b> (Test connection verifies immediately, no restart needed). To restart, double-click restart.bat.</p>';

  // progress bar
  h += '<div class="card p3 mb3">';
  h += '<div class="flex jcs aic mb2"><b class="fs13">Progress '+doneCount+'/'+steps.length+'</b>';
  h += '<div class="flex g2"><button class="btn btn-sm btn-b" id="setupRefresh">Re-check</button>';
  h += '<button class="btn btn-sm" style="background:#0f766e" id="stSelfCheck">🔍 One-click self-check</button></div></div>';
  h += '<div style="background:#e2e8f0;border-radius:6px;height:10px;overflow:hidden"><div style="width:'+Math.round(doneCount/steps.length*100)+'%;height:100%;background:'+(doneCount===steps.length?'#16a34a':'#6366f1')+'"></div></div>';
  h += '<div class="flex fw g2 mt2">';
  steps.forEach(function(s){
    h += '<span class="badge" style="background:'+(s.done?'#dcfce7;color:#166534':'#e2e8f0;color:#64748b')+'">'+(s.done?'✓ ':'')+E(s.name)+'</span>';
  });
  h += '</div></div>';
  h += '<div id="stSelfCheckBox"></div>';

  h += renderCompanySection(status);
  h += renderAiSection(status);
  h += await renderEmailAccountsSection(status);
  h += await renderDemoResetSection();
  h += renderNotifySection(status);
  h += renderRhythmSection(status);
  h += renderKbSection(status);
  h += await renderProfileCatsSection(status);
  h += await renderSignatureSection();

  p.innerHTML = h;
  wireSetup(p);
}

function _inputHtml(field, status, placeholder, type){
  var f = (status.fields||{})[field] || {};
  var value = f.value || '';
  var ph = (f.filled && (f.masked || f.value !== '')) ? ((f.masked?'Configured: '+f.masked:'Configured')) : (placeholder||'');
  if(f.filled && !f.masked && f.value){ value = f.value; ph = placeholder||''; }
  return '<input id="st_'+field+'" type="'+(type||'text')+'" value="'+E(value)+'" placeholder="'+E(ph)+'"'+(type==='password'?' autocomplete="new-password"':'')+' style="padding:8px 10px;border:1px solid #d1d5db;border-radius:5px;font-size:12px;width:100%">';
}

function renderCompanySection(status){
  var h = '<div class="card p3 mb3" style="border-top:2px solid #2563eb">';
  h += '<p class="fwm fs13 mb1">1. Company info</p><p class="fs11 c6 mb2">This replaces the {{COMPANY}} placeholders in the Knowledge Base so AI speaks as your company.</p>';
  h += '<div class="grid gcol2 g2 mb2">';
  h += '<div><label class="fs11 c6">Company name</label>'+_inputHtml('company', status, 'e.g. ABC Import & Export Co.')+'</div>';
  h += '<div><label class="fs11 c6">Your name</label>'+_inputHtml('user_name', status, 'e.g. John Smith')+'</div>';
  h += '<div><label class="fs11 c6">Your email</label>'+_inputHtml('user_email', status, 'sales@company.com')+'</div>';
  h += '<div><label class="fs11 c6">Company website</label>'+_inputHtml('website', status, 'company.com')+'</div>';
  h += '</div>';
  h += '<button class="btn btn-sm" style="background:#2563eb" id="stSaveCompany">Save company info</button> <span id="stCompanyMsg" class="fs11 c6"></span>';
  h += '</div>';
  return h;
}

function renderAiSection(status){
  var h = '<div class="card p3 mb3" style="border-top:2px solid #7c3aed">';
  h += '<p class="fwm fs13 mb1">2. AI configuration</p><p class="fs11 c6 mb2">Fill in any one; the system auto-selects and fails over. Filling more is more stable. Gemini in China needs a proxy.</p>';
  h += '<div class="grid gcol2 g2 mb2">';
  h += '<div><label class="fs11 c6">Gemini API Key</label>'+_inputHtml('gemini_key', status, 'Leave empty if not used. Paste Gemini key here (starts with AIza)', 'password')+'</div>';
  h += '<div><label class="fs11 c6">DeepSeek API Key</label>'+_inputHtml('deepseek_key', status, 'Leave empty if not used. Paste DeepSeek key here (starts with sk-)', 'password')+'</div>';
  h += '<div><label class="fs11 c6">OpenAI API Key (optional)</label>'+_inputHtml('openai_key', status, 'Leave empty if not used. Paste OpenAI key here (starts with sk-)', 'password')+'</div>';
  h += '<div><label class="fs11 c6">Proxy URL (optional)</label>'+_inputHtml('https_proxy', status, 'http://127.0.0.1:7890')+'</div>';
  h += '</div>';
  h += '<button class="btn btn-sm" style="background:#7c3aed" id="stSaveAi">Save AI configuration</button> ';
  h += '<button class="btn btn-sm btn-b" id="stTestAi">Test AI connection</button> <span id="stAiMsg" class="fs11 c6"></span>';
  h += '</div>';
  return h;
}

function _smtpBlock(prefix, label, status){
  var h = '<div class="p3" style="border:1px solid #e2e8f0;border-radius:6px;margin-bottom:10px;background:#fafbfc">';
  h += '<p class="fwm fs12 mb2" style="color:#166534">'+label+'</p>';
  h += '<div class="grid gcol2 g2 mb2">';
  h += '<div><label class="fs11 c6">SMTP server</label>'+_inputHtml('smtp'+prefix+'_host', status, 'smtp.gmail.com')+'</div>';
  h += '<div><label class="fs11 c6">Port</label>'+_inputHtml('smtp'+prefix+'_port', status, '465')+'</div>';
  h += '<div><label class="fs11 c6">Email address</label>'+_inputHtml('smtp'+prefix+'_user', status, 'sales@company.com')+'</div>';
  h += '<div><label class="fs11 c6">Password / app password</label>'+_inputHtml('smtp'+prefix+'_pass', status, 'App password', 'password')+'</div>';
  h += '<div><label class="fs11 c6">Sender display name (optional)</label>'+_inputHtml('smtp'+prefix+'_name', status, 'e.g. ABC Import & Export')+'</div>';
  h += '</div>';
  h += '<button class="btn btn-sm" style="background:#16a34a" id="stSaveSmtp'+prefix+'">Save</button> ';
  h += '<button class="btn btn-sm btn-b" id="stTestSmtp'+prefix+'">Test connection</button> <span id="stSmtpMsg'+prefix+'" class="fs11 c6"></span>';
  h += '</div>';
  return h;
}

function renderSmtpSection(status){
  var h = '<div class="card p3 mb3" style="border-top:2px solid #16a34a">';
  h += '<p class="fwm fs13 mb1">3. Sending mailbox (SMTP)</p><p class="fs11 c6 mb2">Up to 3 sending mailboxes, one per salesperson (see Mailbox-to-user binding). The matching mailbox is used automatically. Enterprise mail normally uses an app password.</p>';
  h += _smtpBlock('', 'Work mailbox 1', status);
  h += _smtpBlock('_2', 'Work mailbox 2', status);
  h += _smtpBlock('_3', 'Work mailbox 3', status);
  h += '</div>';
  return h;
}

function _imapBlock(prefix, label, status){
  var h = '<div class="p3" style="border:1px solid #e2e8f0;border-radius:6px;margin-bottom:10px;background:#fafbfc">';
  h += '<p class="fwm fs12 mb2" style="color:#0e7490">'+label+'</p>';
  h += '<div class="grid gcol2 g2 mb2">';
  h += '<div><label class="fs11 c6">IMAP server</label>'+_inputHtml('imap'+prefix+'_host', status, 'imap.gmail.com')+'</div>';
  h += '<div><label class="fs11 c6">Port</label>'+_inputHtml('imap'+prefix+'_port', status, '993')+'</div>';
  h += '<div><label class="fs11 c6">Email address</label>'+_inputHtml('imap'+prefix+'_user', status, 'sales@company.com')+'</div>';
  h += '<div><label class="fs11 c6">Password / app password</label>'+_inputHtml('imap'+prefix+'_pass', status, 'App password', 'password')+'</div>';
  h += '</div>';
  h += '<button class="btn btn-sm" style="background:#0891b2" id="stSaveImap'+prefix+'">Save</button> ';
  h += '<button class="btn btn-sm btn-b" id="stTestImap'+prefix+'">Test connection</button> <span id="stImapMsg'+prefix+'" class="fs11 c6"></span>';
  h += '</div>';
  return h;
}

function renderImapSection(status){
  var h = '<div class="card p3 mb3" style="border-top:2px solid #0891b2">';
  h += '<p class="fwm fs13 mb1">4. Receiving mailbox (IMAP)</p><p class="fs11 c6 mb2">You can set up to 3 receiving mailboxes (matching senders). Replies are fetched and analyzed by AI.</p>';
  h += _imapBlock('', 'Work mailbox 1', status);
  h += _imapBlock('_2', 'Work mailbox 2', status);
  h += _imapBlock('_3', 'Work mailbox 3', status);
  h += '</div>';
  return h;
}

async function renderSenderBindingSection(status){
  if(!currentUser || currentUser.role === 'member') return '';
  var senders = [], users = [];
  try{ var r = await api('/email/senders'); senders = r || []; }catch(e){}
  try{ var u = await api('/auth/users'); users = (u && u.users) || []; }catch(e){}
  if(!senders.length) return '';
  var h = '<div class="card p3 mb3" style="border-top:2px solid #0ea5e9">';
  h += '<div class="flex aic g2 mb2"><span class="dot" style="width:8px;height:8px;border-radius:50%;background:#0ea5e9"></span><span class="fs14 fwb" style="color:#0f172a">Mailbox-to-user binding</span></div>';
  h += '<p class="fs11 c6 mb2">Bind each sending address to one user (owner/manager/sales). Replies count toward that user. One mailbox per person.</p>';
  senders.forEach(function(s){
    h += '<div class="flex aic g2 mb2 fw" style="background:#f8fafc;border:1px solid #eef1f6;border-radius:8px;padding:8px 10px">';
    h += '<div style="flex:1;min-width:220px"><div class="fs12 fwm">'+E(s.label)+'</div><div class="fs11 c6">'+E(s.email)+'</div></div>';
    h += '<select data-sb="'+E(s.key)+'" style="max-width:240px"><option value="">Unassigned</option>';
    users.forEach(function(u){
      h += '<option value="'+u.id+'" '+(s.bound_user_id===u.id?'selected':'')+'>'+E(u.name)+' ('+E(u.email)+')</option>';
    });
    h += '</select>';
    h += '</div>';
  });
  h += '<button class="btn btn-sm" style="background:#0ea5e9" id="sbSave">Save bindings</button> <span id="sbMsg" class="fs11 c6"></span>';
  h += '</div>';
  return h;
}

async function renderEmailAccountsSection(status){
  if(!currentUser || currentUser.role === 'member') return '';
  var accounts = [], users = [];
  try{ var r = await api('/email/accounts'); accounts = r || []; }catch(e){}
  try{ var u = await api('/auth/users'); users = (u && u.users) || []; }catch(e){}
  var h = '<div class="card p3 mb3" style="border-top:2px solid #16a34a">';
  h += '<div class="flex aic jcs fw g2 mb2"><div class="flex aic g2"><span class="dot" style="width:8px;height:8px;border-radius:50%;background:#16a34a"></span><span class="fs14 fwb" style="color:#0f172a">Mailbox accounts (unlimited)</span></div>';
  h += '<button class="btn btn-sm" style="background:#16a34a" id="eaAdd">+ Add mailbox</button></div>';
  h += '<p class="fs11 c6 mb2">Add one mailbox per salesperson, each can be assigned to a user. SMTP sends; IMAP receives.</p>';
  h += '<div id="eaList">';
  accounts.forEach(function(a){ h += eaCard(a, users); });
  h += '</div></div>';
  return h;
}

async function renderDemoResetSection(){
  try{
    var dm = await api('/setup/demo-mode');
    if(!dm.enabled) return '';
  }catch(e){ return ''; }
  if(!currentUser || currentUser.role === 'member') return '';
  var h = '<div class="card p3 mb3" style="border-top:2px solid #dc2626">';
  h += '<div class="flex aic g2 mb2"><span class="dot" style="width:8px;height:8px;border-radius:50%;background:#dc2626"></span><span class="fs14 fwb" style="color:#0f172a">Demo data (one-click reset)</span></div>';
  h += '<p class="fs11 c6 mb2">This is the demo version. Reset restores 40 demo customers covering scoring, emails, deals, samples, follow-ups and the knowledge base.</p>';
  h += '<button class="btn btn-sm" style="background:#dc2626" id="demoResetBtn">Reset demo data</button> <span id="demoResetMsg" class="fs11 c6"></span>';
  h += '</div>';
  return h;
}

function eaCard(a, users){
  var h = '<div class="ea-card" data-eaid="'+E(a.id||'new')+'" data-key="'+E(a.key||'')+'" style="border:1px solid #e2e8f0;border-radius:8px;margin-bottom:10px;background:#fafbfc;padding:12px">';
  h += '<div class="flex aic g2 fw mb2"><input data-f="name" value="'+E(a.name||'')+'" style="max-width:240px;font-weight:600" placeholder="Mailbox name, e.g. Sales - John Smith">';
  h += '<span class="fs11 c6">'+E(a.smtp_user||'')+'</span><span style="flex:1"></span>';
  h += '<button class="btn btn-sm btn-b" data-act="test">Test</button>';
  h += '<button class="btn btn-sm" style="background:#16a34a" data-act="save">Save</button>';
  h += '<button class="btn btn-sm" style="background:#7c3aed;color:#fff" data-act="default">Set as default sender</button>';
  if(currentUser && currentUser.default_sender && a.key && a.key === currentUser.default_sender){
    h += '<span class="fs11 fwb" style="color:#7c3aed">★ Current default</span>';
  }
  h += '<button class="btn btn-sm" style="background:#dc2626" data-act="del">Delete</button></div>';
  h += '<div class="grid gcol2 g2 mb1">';
  h += '<div><label class="fs11 c6">SMTP server (sending)</label><input data-f="smtp_host" value="'+E(a.smtp_host||'')+'" placeholder="smtp.gmail.com"></div>';
  h += '<div><label class="fs11 c6">SMTP Port</label><input data-f="smtp_port" value="'+E(a.smtp_port||465)+'"></div>';
  h += '<div><label class="fs11 c6">Sending address</label><input data-f="smtp_user" value="'+E(a.smtp_user||'')+'" placeholder="sales@company.com"></div>';
  h += '<div><label class="fs11 c6">Password / app password</label><input data-f="smtp_pass" type="password" value="'+E(a.smtp_pass||'')+'" placeholder="'+(a.smtp_pass==='****'?'Configured - leave blank to keep':'')+'"></div>';
  h += '<div><label class="fs11 c6">Sender display name (optional)</label><input data-f="smtp_name" value="'+E(a.smtp_name||'')+'" placeholder="e.g. John Smith"></div>';
  h += '<div><label class="fs11 c6">Assigned user</label><select data-f="bound_user_id"><option value="">Unassigned</option>';
  users.forEach(function(u){ h += '<option value="'+u.id+'" '+((a.bound_user_id===u.id)?'selected':'')+'>'+E(u.name)+' ('+E(u.email)+')</option>'; });
  h += '</select></div>';
  h += '</div>';
  h += '<div class="grid gcol2 g2 mb1" style="border-top:1px dashed #e2e8f0;padding-top:8px">';
  h += '<div><label class="fs11 c6">IMAP server (receiving, optional)</label><input data-f="imap_host" value="'+E(a.imap_host||'')+'" placeholder="imap.gmail.com"></div>';
  h += '<div><label class="fs11 c6">IMAP Port</label><input data-f="imap_port" value="'+E(a.imap_port||993)+'"></div>';
  h += '<div><label class="fs11 c6">Inbox address</label><input data-f="imap_user" value="'+E(a.imap_user||'')+'"></div>';
  h += '<div><label class="fs11 c6">Password / app password</label><input data-f="imap_pass" type="password" value="'+E(a.imap_pass||'')+'" placeholder="'+(a.imap_pass==='****'?'Configured - leave blank to keep':'')+'"></div>';
  h += '</div>';
  h += '<div class="fs11" style="color:#94a3b8">'+E(a.key||'New account')+'</div>';
  h += '</div>';
  return h;
}

function renderNotifySection(status){
  var h = '<div class="card p3 mb3" style="border-top:2px solid #f59e0b">';
  h += '<p class="fwm fs13 mb1">5. Alert notifications (optional)</p><p class="fs11 c6 mb2">When enabled, daily follow-up reminders and weekly knowledge-health reports are pushed to your phone. Only needed if you use the ServerChan push service (WeChat). Most users can skip this step.</p>';
  h += '<div class="mb2"><label class="fs11 c6">Push service key (ServerChan SendKey, optional)</label>'+_inputHtml('serverchan_key', status, 'sctp...', 'password')+'</div>';
  h += '<button class="btn btn-sm" style="background:#f59e0b" id="stSaveNotify">Save</button> <span id="stNotifyMsg" class="fs11 c6"></span>';
  h += '</div>';
  return h;
}

function renderRhythmSection(status){
  var h = '<div class="card p3 mb3" style="border-top:2px solid #475569">';
  h += '<p class="fwm fs13 mb1">6. Sending rhythm & security</p><p class="fs11 c6 mb2">The daily limit protects your account from spam flags. For local-only use, set Listen address to 127.0.0.1.</p>';
  h += '<div class="grid gcol2 g2 mb2">';
  h += '<div><label class="fs11 c6">Daily sending limit</label>'+_inputHtml('daily_limit', status, '25')+'</div>';
  h += '<div><label class="fs11 c6">Minimum interval (minutes)</label>'+_inputHtml('email_min_interval', status, '30')+'</div>';
  h += '<div><label class="fs11 c6">Maximum interval (minutes)</label>'+_inputHtml('email_max_interval', status, '90')+'</div>';
  h += '<div><label class="fs11 c6">Listen address</label>'+_inputHtml('host', status, '0.0.0.0')+'</div>';
  h += '<div><label class="fs11 c6">Login user (optional)</label>'+_inputHtml('app_user', status, 'admin')+'</div>';
  h += '<div><label class="fs11 c6">Login password (optional)</label>'+_inputHtml('app_password', status, 'Requires login once set', 'password')+'</div>';
  h += '<div style="grid-column:1/-1"><label class="fs11 c6">Cloud backup folder (optional; e.g. OneDrive/Dropbox/Google Drive)</label>'+_inputHtml('backup_cloud_dir', status, 'e.g. D:\\Backups\\Company or your OneDrive/Dropbox folder')+'</div>';
  h += '<div style="grid-column:1/-1"><label class="fs11 c6">Backup encryption password (optional; auto-generated if empty)</label>'+_inputHtml('backup_password', status, 'Leave blank to auto-generate a strong password', 'password')+'<div class="fs11 c6" style="margin-top:2px">Local and cloud backups use AES-256 encryption. Restart to apply; keep the password safe.</div></div>';
  h += '</div>';
  h += '<button class="btn btn-sm" style="background:#475569" id="stSaveRhythm">Save</button> <span id="stRhythmMsg" class="fs11 c6"></span>';
  h += '</div>';
  return h;
}

function renderKbSection(status){
  var kbStep = (status.steps||[]).filter(function(s){return s.key==='knowledge'})[0] || {};
  var done = kbStep.done;
  var h = '<div class="card p3 mb3" style="border-top:2px solid #dc2626">';
  h += '<p class="fwm fs13 mb1">7. Knowledge base (most important - keep updating)</p>';
  h += '<p class="fs11 c6 mb2">The knowledge base is the only source AI uses to understand your company。<b style="color:#dc2626">It is not a one-time setup</b>——'
     + 'The system auto-checks weekly and reminds you to fill gaps; gaps are recorded as AI finds them. Keep refining it.</p>';
  h += '<div class="flex aic g2"><button class="btn btn-sm" style="background:'+(done?'#16a34a':'#dc2626')+'" id="stGoKb">'
     + (done?'Continue in Knowledge Base':'Start setting up Knowledge Base')+'</button>';
  h += '<span class="fs11 c6">'+(done?'Knowledge base is healthy (score >=65); still update weekly':'Not ready yet - finish knowledge base initialization first')+'</span></div>';
  h += '</div>';
  return h;
}

async function renderProfileCatsSection(status){
  var cats = [];
  try{
    var r = await api('/setup/profile-categories');
    cats = (r && r.categories) || [];
  }catch(e){}
  if(cats.length) window._profileCats = cats;
  var h = '<div class="card p3 mb3" style="border-top:2px solid #7c3aed">';
  h += '<p class="fwm fs13 mb1">8. Customer profile categories (define them for your industry)</p>';
  h += '<p class="fs11 c6 mb2">Defaults are examples - change them to your own customer types (e.g. machinery: brand / distributor / assembler / repair service; auto: OEM / importer / distributor / repair chain). '
     + 'Customer details, AI scoring and list filters use these categories. Rename A-E or add your own.</p>';
  h += '<div id="profileCatsList" style="display:flex;flex-direction:column;gap:6px;margin-bottom:10px">';
  cats.forEach(function(c){
    h += '<div style="display:flex;align-items:center;gap:8px;background:#f8fafc;border:1px solid #e4e9f2;border-radius:8px;padding:7px 10px">';
    h += '<span class="badge" style="background:#7c3aed;color:#fff">'+E(c.key)+'</span>';
    h += '<span style="flex:1;font-size:13px">'+E(c.label)+'</span>';
    h += '<span class="fs11 c6">'+(c.custom?'Custom':'Default')+'</span>';
    h += '<button class="btn btn-sm btn-b" data-ren-cat="'+E(c.key)+'" style="font-size:10px">Rename</button>';
    if(c.custom) h += '<button class="btn btn-sm" style="background:#dc2626;font-size:10px" data-del-cat="'+E(c.key)+'">Delete</button>';
    h += '</div>';
  });
  h += '</div>';
  h += '<div class="flex g2 aic fw"><input id="newCatName" placeholder="Add category, e.g. Distributor" style="max-width:300px"><button class="btn btn-sm" style="background:#7c3aed" id="addCatBtn">+ Add category</button> <span id="catMsg" class="fs11 c6"></span></div>';
  h += '</div>';
  return h;
}

async function renderSignatureSection(){
  var sigs = {};
  try{
    var r = await api('/setup/signatures');
    sigs = (r && r.signatures) || {};
  }catch(e){}
  window._profileSignatures = sigs;
  var cats = window._profileCats || [];
  var catLabel = function(key){
    for(var i=0;i<cats.length;i++){ if(String(cats[i].key) === String(key)) return cats[i].label; }
    return null;
  };
  var fallbackName = {
    A: 'A - Engineering', B: 'B - Brand / OEM importer', C: 'C - Sales-oriented',
    D: 'D - Service', E: 'E - Flexible', DEFAULT: 'General signature',
  };
  var fixedHint = {
    A: 'Technical customers (coating/plating plants, engineers)',
    B: 'Brand/import customers who value stable quality and delivery',
    C: 'Emerging-market customers who value responsiveness and samples',
    D: 'Repair services that value stock and fast delivery',
    E: 'Repair centers / small batches needing broad stock and any quantity',
    DEFAULT: 'Fallback when no profile matches',
  };
  var titleMap = {};
  var hintMap = {};
  Object.keys(fallbackName).forEach(function(key){
    var lbl = catLabel(key);
    titleMap[key] = lbl || fallbackName[key];
    hintMap[key] = lbl ? 'Auto-matched for this profile tier when sending' : (fixedHint[key] || '');
  });
  var h = '<div class="card p3 mb3" style="border-top:2px solid #0ea5e9">';
  h += '<p class="fwm fs13 mb1">9. Email signatures (auto-matched by profile)</p>';
  h += '<p class="fs11 c6 mb2">Each signature is auto-selected by profile. {{USER_NAME}} {{USER_EMAIL}} {{COMPANY}} {{WEBSITE}} are replaced with your real info when sending.' +
       'Design one per profile, or edit the general one. Save to apply.</p>';
  Object.keys(titleMap).forEach(function(key){
    var val = sigs[key] || '';
    h += '<div style="border:1px solid #e4e9f2;border-radius:8px;margin-bottom:10px;overflow:hidden">';
    h += '<div style="padding:8px 12px;background:#f8fafc;border-bottom:1px solid #e4e9f2;display:flex;align-items:center;gap:8px">';
    h += '<span class="badge" style="background:#0ea5e9;color:#fff">'+E(titleMap[key])+'</span>';
    h += '<span class="fs11 c6">'+E(hintMap[key])+'</span>';
    h += '</div>';
    h += '<div style="padding:10px 12px">';
    h += '<textarea id="sigTpl_'+key+'" rows="4" style="width:100%;padding:8px 10px;border:1px solid #d1d5db;border-radius:6px;font-size:12px;line-height:1.6;resize:vertical" placeholder="Signature content...">'+E(val)+'</textarea>';
    h += '<div style="display:flex;align-items:center;gap:8px;margin-top:6px;flex-wrap:wrap">';
    h += '<button class="btn btn-sm btn-b" data-sig-preview="'+E(key)+'">Preview</button>';
    h += '<button class="btn btn-sm" style="background:#0ea5e9" data-sig-save="'+E(key)+'">Save this signature</button>';
    h += '<span id="sigPrev_'+E(key)+'" class="fs11 c6" style="font-family:monospace;white-space:pre-wrap"></span>';
    h += '</div></div></div>';
  });
  h += '<button class="btn btn-sm" style="background:#16a34a" id="sigSaveAll">Save all signatures</button> <span id="sigMsg" class="fs11 c6"></span>';
  h += '</div>';
  return h;
}

function wireSetup(p){
  var refresh = p.querySelector('#setupRefresh');
  if(refresh) refresh.addEventListener('click', function(){ RSetup(p); });

  var selfCheck = p.querySelector('#stSelfCheck');
  if(selfCheck) selfCheck.addEventListener('click', async function(){
    var box = p.querySelector('#stSelfCheckBox');
    if(!box) return;
    box.innerHTML = '<div class="card p3 mt2" style="color:#64748b">Self-check running (AI/email tests take up to about 20 seconds)...</div>';
    selfCheck.disabled = true;
    try{
      var r = await api('/setup/self-check', {method:'POST', body:{}});
      box.innerHTML = renderSelfCheck(r);
    }catch(e){
      box.innerHTML = '<div class="card p3 mt2" style="color:#dc2626">Self-check failed: '+E(e.detail||e.message||String(e))+'</div>';
    }
    selfCheck.disabled = false;
  });

  var goKb = p.querySelector('#stGoKb');
  if(goKb) goKb.addEventListener('click', function(){ nav('knowledge'); });

  wireSave(p, 'stSaveCompany', 'applyCompany', 'stCompanyMsg', ['company','user_name','user_email','website']);
  wireSave(p, 'stSaveAi', 'save', 'stAiMsg', ['gemini_key','deepseek_key','openai_key','https_proxy']);
  wireSave(p, 'stSaveNotify', 'save', 'stNotifyMsg', ['serverchan_key']);
  wireSave(p, 'stSaveRhythm', 'save', 'stRhythmMsg', ['daily_limit','email_min_interval','email_max_interval','host','app_user','app_password','backup_cloud_dir','backup_password']);

  wireTest(p, 'stTestAi', 'test-ai', 'stAiMsg', ['gemini_key','deepseek_key','openai_key','https_proxy'], renderAiResults);
  wireProfileCats(p);
  wireEmailAccounts(p);
  wireSignatures(p);
  var drBtn = p.querySelector('#demoResetBtn');
  if(drBtn) drBtn.addEventListener('click', async function(){
    if(!confirm('Reset demo data? All demo customers, emails, deals and knowledge will return to the initial demo state.')) return;
    var msg = p.querySelector('#demoResetMsg');
    if(msg){ msg.innerHTML = 'Resetting...'; msg.style.color = '#64748b'; }
    drBtn.disabled = true;
    try{
      var r = await api('/setup/demo-reset', {method:'POST', body:{}});
      if(msg){ msg.innerHTML = '✓ Reset - '+r.prospects+' demo customers created (covering all features)'; msg.style.color = '#16a34a'; }
      T('Demo data reset', '#16a34a');
      RSetup(p);
    }catch(e){
      if(msg){ msg.innerHTML = 'Reset failed: '+E(e.detail||e.message||String(e)); msg.style.color = '#dc2626'; }
    }
    drBtn.disabled = false;
  });
}

function wireSignatures(p){
  // Preview
  p.querySelectorAll('[data-sig-preview]').forEach(function(btn){
    btn.addEventListener('click', function(){
      var key = btn.dataset.sigPreview;
      var tpl = (p.querySelector('#sigTpl_'+key) || {}).value || '';
      var prev = p.querySelector('#sigPrev_'+key);
      if(prev){
        prev.textContent = 'Preview:\n' + tpl
          .replace(/\{\{USER_NAME\}\}/g, (currentUser && currentUser.name) || 'Your Name')
          .replace(/\{\{USER_EMAIL\}\}/g, (currentUser && currentUser.email) || 'you@company.com')
          .replace(/\{\{COMPANY\}\}/g, 'Your Company')
          .replace(/\{\{WEBSITE\}\}/g, 'www.company.com');
      }
    });
  });
  // 单个Save
  p.querySelectorAll('[data-sig-save]').forEach(function(btn){
    btn.addEventListener('click', async function(){
      var key = btn.dataset.sigSave;
      var tpl = (p.querySelector('#sigTpl_'+key) || {}).value || '';
      btn.disabled = true;
      try{
        await api('/setup/signatures', {method:'PUT', body:{profile:key, template:tpl}});
        var msg = p.querySelector('#sigMsg');
        if(msg){ msg.textContent = '✓ '+key+' signature saved'; msg.style.color = '#16a34a'; }
        await loadProfileSignatures();
      }catch(e){
        var msg2 = p.querySelector('#sigMsg');
        if(msg2){ msg2.textContent = 'Save failed: '+E(e.detail||e.message||String(e)); msg2.style.color = '#dc2626'; }
      }
      btn.disabled = false;
    });
  });
  // 全部Save
  var saveAll = p.querySelector('#sigSaveAll');
  if(saveAll) saveAll.addEventListener('click', async function(){
    saveAll.disabled = true;
    try{
      ['A','B','C','D','E','DEFAULT'].forEach(function(key){
        var tpl = (p.querySelector('#sigTpl_'+key) || {}).value || '';
        // 逐个Save（PUT 单画像接口）
        api('/setup/signatures', {method:'PUT', body:{profile:key, template:tpl}});
      });
      // 等全部完成
      await new Promise(function(res){ setTimeout(res, 1200); });
      await loadProfileSignatures();
      var msg = p.querySelector('#sigMsg');
      if(msg){ msg.textContent = 'All signatures saved'; msg.style.color = '#16a34a'; }
      T('All signatures saved', '#16a34a');
    }catch(e){
      var msg3 = p.querySelector('#sigMsg');
      if(msg3){ msg3.textContent = 'Save failed: '+E(e.detail||e.message||String(e)); msg3.style.color = '#dc2626'; }
    }
    saveAll.disabled = false;
  });
}

function wireEmailAccounts(p){
  var addBtn = p.querySelector('#eaAdd');
  if(addBtn) addBtn.addEventListener('click', function(){
    var list = p.querySelector('#eaList');
    if(!list) return;
    list.insertAdjacentHTML('beforeend', eaCard({id:'new', smtp_port:465, imap_port:993, name:'', smtp_host:'', smtp_user:'', smtp_pass:'', smtp_name:'', imap_host:'', imap_user:'', imap_pass:'', bound_user_id:null, key:''}, []));
    wireOneAccount(p, list.lastElementChild);
    list.lastElementChild.scrollIntoView({behavior:'smooth', block:'center'});
  });
  p.querySelectorAll('.ea-card').forEach(function(card){ wireOneAccount(p, card); });
}

function wireOneAccount(p, card){
  var defBtn = card.querySelector('[data-act="default"]');
  if(defBtn) defBtn.addEventListener('click', async function(){
    var key = card.dataset.key;
    if(!key || card.dataset.eaid === 'new'){ T('Save this mailbox first, then set as default sender', '#f59e0b'); return; }
    try{
      await api('/auth/default-sender', {method:'POST', body:{sender_key:key}});
      if(currentUser){ currentUser.default_sender = key; try{ localStorage.setItem('td_user', JSON.stringify(currentUser)); }catch(e){} }
      T('Default sender updated', '#16a34a');
      RSetup(p);
    }catch(e){ T('Update failed: '+(e.detail||e.message||''), '#dc2626'); }
  });
  var saveBtn = card.querySelector('[data-act="save"]');
  if(saveBtn) saveBtn.addEventListener('click', async function(){
    var payload = {};
    card.querySelectorAll('[data-f]').forEach(function(inp){
      var f = inp.dataset.f, v = inp.value;
      if(f === 'bound_user_id') payload[f] = v ? parseInt(v, 10) : null;
      else if(f === 'smtp_port' || f === 'imap_port') payload[f] = parseInt(v || 0, 10);
      else if(f === 'smtp_pass' || f === 'imap_pass'){ if(v !== '****') payload[f] = v; }
      else payload[f] = v;
    });
    var eaid = card.dataset.eaid;
    saveBtn.disabled = true; saveBtn.textContent = 'Saving...';
    try{
      if(eaid === 'new'){
        await api('/email/accounts', {method:'POST', body:payload});
      }else{
        await api('/email/accounts/'+eaid, {method:'PUT', body:payload});
      }
      T('Saved', '#16a34a');
      RSetup(p);
    }catch(e){ T('Save failed: '+(e.detail||e.message||''), '#dc2626'); }
    saveBtn.disabled = false; saveBtn.textContent = 'Save';
  });
  var testBtn = card.querySelector('[data-act="test"]');
  if(testBtn) testBtn.addEventListener('click', async function(){
    var eaid = card.dataset.eaid;
    if(eaid === 'new'){ T('Save before testing', '#f59e0b'); return; }
    testBtn.disabled = true; testBtn.textContent = 'Testing...';
    try{
      var r = await api('/email/accounts/'+eaid+'/test', {method:'POST', body:{}});
      var parts = [];
      if(r.results && r.results.smtp) parts.push('Sending '+(r.results.smtp.ok?'✓':'✗ '+(r.results.smtp.error||'')));
      if(r.results && r.results.imap) parts.push('Receiving '+(r.results.imap.ok?'✓':'✗ '+(r.results.imap.error||'')));
      T(parts.join(' ｜ ') || 'Nothing configured to test', r.ok ? '#16a34a' : '#dc2626', 6000);
    }catch(e){ T('Test failed: '+(e.detail||e.message||''), '#dc2626'); }
    testBtn.disabled = false; testBtn.textContent = 'Test';
  });
  var delBtn = card.querySelector('[data-act="del"]');
  if(delBtn) delBtn.addEventListener('click', async function(){
    var eaid = card.dataset.eaid;
    if(eaid === 'new'){ card.remove(); return; }
    if(!confirm('Delete this mailbox account? Sent email records are unaffected.')) return;
    try{
      await api('/email/accounts/'+eaid, {method:'DELETE'});
      T('Deleted', '#16a34a');
      RSetup(p);
    }catch(e){ T('Delete failed: '+(e.detail||e.message||''), '#dc2626'); }
  });
}

function wireProfileCats(p){
  var addBtn = p.querySelector('#addCatBtn');
  if(addBtn) addBtn.addEventListener('click', async function(){
    var input = p.querySelector('#newCatName');
    var name = input ? input.value.trim() : '';
    var msg = p.querySelector('#catMsg');
    if(!name){ if(msg){ msg.innerHTML = 'Enter a category name'; msg.style.color = '#dc2626'; } return; }
    addBtn.disabled = true;
    try{
      var r = await api('/setup/profile-categories', {method:'POST', body:{label:name}});
      window._profileCats = (r && r.categories) || window._profileCats;
      if(msg){ msg.innerHTML = 'Added - add more or rename'; msg.style.color = '#16a34a'; }
      T('Category added: '+name, '#16a34a');
      RSetup(p);
    }catch(e){
      if(msg){ msg.innerHTML = 'Add failed: '+E(e.detail||e.message||String(e)); msg.style.color = '#dc2626'; }
    }
    addBtn.disabled = false;
  });
  p.querySelectorAll('[data-ren-cat]').forEach(function(btn){
    btn.addEventListener('click', async function(){
      var key = btn.dataset.renCat;
      var cats = window._profileCats || [];
      var cur = '';
      cats.forEach(function(c){ if(c.key === key) cur = c.label; });
      var name = prompt('New category name:', cur);
      if(!name || !name.trim()) return;
      try{
        var r = await api('/setup/profile-categories/'+encodeURIComponent(key), {method:'PUT', body:{label:name.trim()}});
        window._profileCats = (r && r.categories) || window._profileCats;
        T('Renamed', '#16a34a');
        RSetup(p);
      }catch(e){ T('Rename failed: '+(e.detail||e.message||''), '#dc2626'); }
    });
  });
  p.querySelectorAll('[data-del-cat]').forEach(function(btn){
    btn.addEventListener('click', async function(){
      var key = btn.dataset.delCat;
      if(!confirm('Delete this category?')) return;
      try{
        var r = await api('/setup/profile-categories/'+encodeURIComponent(key), {method:'DELETE'});
        window._profileCats = (r && r.categories) || window._profileCats;
        T('Deleted', '#16a34a');
        RSetup(p);
      }catch(e){ T('Delete failed: '+(e.detail||e.message||''), '#dc2626'); }
    });
  });
}

function wireSave(p, btnId, action, msgId, fields){
  var btn = p.querySelector('#'+btnId);
  if(!btn) return;
  btn.addEventListener('click', async function(){
    var values = {};
    fields.forEach(function(f){
      var el = p.querySelector('#st_'+f);
      if(el) values[f] = el.value.trim();
    });
    var msg = p.querySelector('#'+msgId);
    if(msg){ msg.innerHTML = 'Saving...'; msg.style.color = '#64748b'; }
    try{
      var endpoint = action === 'applyCompany' ? '/setup/apply-company' : '/setup/save';
      var r = await api(endpoint, {method:'POST', body: action === 'applyCompany' ? values : {values:values}});
      if(msg){
        msg.innerHTML = '✓ Saved' + (r.backup ? ' (backup '+E(r.backup)+')' : '') + (r.remaining_placeholders && r.remaining_placeholders.count ? '; remaining placeholders '+r.remaining_placeholders.count+'' : '');
        msg.style.color = '#16a34a';
      }
      T('Configuration saved', '#16a34a');
      RSetup(p);
    }catch(e){
      if(msg){ msg.innerHTML = 'Save failed: '+E(e.detail||e.message||String(e)); msg.style.color = '#dc2626'; }
    }
  });
}

function wireTest(p, btnId, endpoint, msgId, fields, formatter){
  var btn = p.querySelector('#'+btnId);
  if(!btn) return;
  btn.addEventListener('click', async function(){
    var values = {};
    fields.forEach(function(f){
      var el = p.querySelector('#st_'+f);
      if(el) values[f] = el.value.trim();
    });
    var msg = p.querySelector('#'+msgId);
    if(msg){ msg.innerHTML = 'Testing (about 5-15 seconds)...'; msg.style.color = '#64748b'; }
    btn.disabled = true;
    try{
      var r = await api('/setup/'+endpoint, {method:'POST', body:{values:values}});
      if(msg){
        var text = formatter ? formatter(r) : (r.ok ? '✓ '+E(r.message||'Connected') : '✗ '+E(r.error||'Test failed'));
        msg.innerHTML = text;
        msg.style.color = r.ok ? '#16a34a' : '#dc2626';
      }
    }catch(e){
      if(msg){ msg.innerHTML = 'Test error: '+E(e.detail||e.message||String(e)); msg.style.color = '#dc2626'; }
    }
    btn.disabled = false;
  });
}

function renderAiResults(r){
  if(!r || !r.providers) return '✗ '+E((r&&r.error)||'Test failed');
  var parts = [];
  Object.keys(r.providers).forEach(function(k){
    var p = r.providers[k] || {};
    parts.push((p.ok?'✓ ':'✗ ')+k+(p.ok?' Connected':' '+E(p.error||'')));
  });
  return parts.join('<br>');
}

function renderSelfCheck(r){
  var names = {database:'Database', scheduler:'Scheduler', ai:'AI service', smtp:'Sending mailbox', imap:'Inbox address', knowledge:'Knowledge base', backup:'Data backup'};
  var h = '<div class="card p3 mt2">';
  h += '<p class="fwm fs13 mb2">Self-check result:'+(r.ok?'<span style="color:#16a34a">All OK</span>':'<span style="color:#dc2626">Issues found - see below</span>')+'</p>';
  Object.keys(r.results||{}).forEach(function(k){
    var v = r.results[k] || {};
    var ok = v.ok === true;
    var detail = v.error || v.message || v.detail || (ok ? 'OK' : 'Error');
    h += '<div class="flex jcs aic" style="padding:6px 0;border-bottom:1px solid #f1f5f9">';
    h += '<b class="fs12">'+(names[k]||k)+'</b>';
    h += '<span class="fs11" style="color:'+(ok?'#16a34a':'#dc2626')+'">'+(ok?'✓ ':'✗ ')+E(String(detail))+'</span></div>';
  });
  h += '</div>';
  return h;
}
