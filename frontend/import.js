// ── Add Customer（大白话版）：手动添加 / 批量导入 ──

function RImport(p){
  var tab = localStorage.getItem('td_import_tab') || 'manual';
  var h = '<h2 class="fs20 fwb mb2">Add Customer</h2>';
  h += '<p class="fs12 c6 mb4">Record your prospects here; AI will research, score and schedule follow-ups.</p>';

  // ── 标签切换 ──
  h += '<div class="tab-bar" style="max-width:720px">'
    + '<button id="tabManual" class="'+(tab==='manual'?'active':'')+'" style="font-size:13px">✍️ Add manually</button>'
    + '<button id="tabBatch" class="'+(tab==='batch'?'active':'')+'" style="font-size:13px">📄 Batch import</button>'
    + '</div>';
  h += '<div id="importBody" style="max-width:720px"></div>';
  p.innerHTML = h;

  document.getElementById('tabManual').onclick = function(){ localStorage.setItem('td_import_tab','manual'); RImport(p); };
  document.getElementById('tabBatch').onclick = function(){ localStorage.setItem('td_import_tab','batch'); RImport(p); };

  if(tab === 'batch'){ renderBatch(document.getElementById('importBody')); }
  else { renderManual(document.getElementById('importBody')); }
}

// ── 手动添加：只留常用字段，更多信息折叠 ──
function renderManual(box){
  var h = '<div class="card p4">';
  h += '<p class="fwm mb3" style="font-size:15px">Enter one customer company</p>';
  h += '<div class="fs11 c6 mb3">Multiple contacts at the same company? Use the same company name and they will group automatically.</div>';

  h += '<div class="grid gcol2 g3 mb3">';
  h += '<div><label class="fs11 c6" style="display:block;margin-bottom:2px">Company <span style="color:#dc2626">*</span></label><input id="ma_company" placeholder="Company" style="padding:8px 10px;border:1px solid #d1d5db;border-radius:6px;font-size:13px"></div>';
  h += '<div><label class="fs11 c6" style="display:block;margin-bottom:2px">Contact</label><input id="ma_contact" placeholder="e.g. Michael Johnson" style="padding:8px 10px;border:1px solid #d1d5db;border-radius:6px;font-size:13px"></div>';
  h += '<div><label class="fs11 c6" style="display:block;margin-bottom:2px">Email</label><input id="ma_email" placeholder="e.g. info@company.com" style="padding:8px 10px;border:1px solid #d1d5db;border-radius:6px;font-size:13px"></div>';
  h += '<div><label class="fs11 c6" style="display:block;margin-bottom:2px">Country / Region</label><input id="ma_country" placeholder="e.g. Germany" style="padding:8px 10px;border:1px solid #d1d5db;border-radius:6px;font-size:13px"></div>';
  h += '<div><label class="fs11 c6" style="display:block;margin-bottom:2px">Website</label><input id="ma_website" placeholder="e.g. www.company.com" style="padding:8px 10px;border:1px solid #d1d5db;border-radius:6px;font-size:13px"></div>';
  h += '<div><label class="fs11 c6" style="display:block;margin-bottom:2px">Source</label><select id="ma_source_channel" style="padding:8px 10px;border:1px solid #d1d5db;border-radius:6px;font-size:13px">';
  ['','LinkedIn','Email','Google','Google Maps','Trade Show','Industry directory','Referral','Website','WhatsApp','Existing customer','Other'].forEach(function(v){ h += '<option value="'+v+'">'+(v||'— Select —')+'</option>'; });
  h += '</select></div>';
  h += '</div>';

  // 更多信息（选填）折叠
  h += '<div class="mb3"><a href="#" id="maMoreToggle" style="font-size:12px;color:#7c3aed;text-decoration:none">+ More fields (optional)</a></div>';
  h += '<div id="maMore" style="display:none">';
  h += '<div class="grid gcol2 g3 mb3">';
  h += '<div><label class="fs11 c6" style="display:block;margin-bottom:2px">Title</label><input id="ma_title" placeholder="e.g. Purchasing Manager" style="padding:8px 10px;border:1px solid #d1d5db;border-radius:6px;font-size:13px"></div>';
  h += '<div><label class="fs11 c6" style="display:block;margin-bottom:2px">Company size</label><input id="ma_size" placeholder="e.g. 50-100 employees" style="padding:8px 10px;border:1px solid #d1d5db;border-radius:6px;font-size:13px"></div>';
  h += '<div><label class="fs11 c6" style="display:block;margin-bottom:2px">Industry</label><input id="ma_industry" placeholder="e.g. Auto parts" style="padding:8px 10px;border:1px solid #d1d5db;border-radius:6px;font-size:13px"></div>';
  h += '<div><label class="fs11 c6" style="display:block;margin-bottom:2px">Phone</label><input id="ma_phone" placeholder="e.g. +49 1234 5678" style="padding:8px 10px;border:1px solid #d1d5db;border-radius:6px;font-size:13px"></div>';
  h += '<div><label class="fs11 c6" style="display:block;margin-bottom:2px">Note</label><input id="ma_note" placeholder="Anything worth remembering" style="padding:8px 10px;border:1px solid #d1d5db;border-radius:6px;font-size:13px"></div>';
  h += '</div></div>';

  h += '<button class="btn" style="background:#2563eb;padding:8px 22px;font-size:14px" id="addBtn">Save customer</button><span id="addR" class="ml2 fs12"></span>';
  h += '</div>';
  box.innerHTML = h;

  document.getElementById('maMoreToggle').onclick = function(e){
    e.preventDefault();
    var el = document.getElementById('maMore');
    var show = el.style.display !== 'block';
    el.style.display = show ? 'block' : 'none';
    this.textContent = show ? '- Collapse more fields' : '+ More fields (optional)';
  };

  document.getElementById('addBtn').onclick = async function(){
    var company = document.getElementById('ma_company').value.trim();
    if(!company){ T('Please fill in the company name', '#dc2626'); return; }
    var data = { company: company };
    ['contact','title','country','size','industry','website','email','phone','note'].forEach(function(k){
      var v = document.getElementById('ma_' + k).value.trim();
      if(v) data[k] = v;
    });
    var sc = document.getElementById('ma_source_channel').value;
    if(sc) data.source_channel = sc;
    try{
      var r = await api('/prospects/create', {method:'POST', body:data});
      var msg = document.getElementById('addR');
      msg.innerHTML = '<span style="color:#059669">✅ Saved ' + (r.company || '') + '</span>';
      T('Customer added');
      ['company','contact','title','country','size','industry','website','email','phone','note'].forEach(function(k){
        document.getElementById('ma_' + k).value = '';
      });
      document.getElementById('ma_source_channel').value = '';
      showNextStep('Customer added', 'Next: go to <b>Customer List</b>, or open the customer for AI research and scoring.', 'Go to Customer List', 'list');
    }catch(e){
      var em = 'Add failed';
      if(e.detail) em += ': ' + String(e.detail).substring(0,120);
      else if(e.message) em += ': ' + String(e.message).substring(0,120);
      T(em, '#dc2626');
    }
  };
}

// ── 批量导入：上传/粘贴 → AI 整理校验 → 预览确认 ──
function renderBatch(box){
  var mode = window._impMode === 'paste' ? 'paste' : 'file';
  var h = '<div class="card p4">';
  h += '<p class="fwm mb2" style="font-size:15px">Batch import customers</p>';
  h += '<div class="fs11 c6 mb3" style="line-height:1.7">Supports Excel / CSV files, or just <b>paste anything</b>: tables, web pages, JSON, trade-show lists, chat logs. The AI cleans it into the standard format and flags anything wrong.</div>';

  // 来源切换
  h += '<div class="flex g2 aic mb2">'
    + '<button class="btn btn-sm '+(mode!=='paste'?'btn-pri':'btn-b')+'" id="impModeFile">📄 Upload file</button>'
    + '<button class="btn btn-sm '+(mode==='paste'?'btn-pri':'btn-b')+'" id="impModePaste">📋 Paste list</button>'
    + '</div>';

  h += '<div id="impFileBox" style="display:'+(mode==='paste'?'none':'block')+'">';
  h += '<div style="display:flex;gap:10px;align-items:center;flex-wrap:wrap;margin-bottom:10px">';
  h += '<input type="file" id="impCsv" accept=".csv,.xlsx,.xls,.json" style="flex:1;max-width:380px;font-size:13px">';
  h += '</div></div>';

  h += '<div id="impPasteBox" style="display:'+(mode==='paste'?'block':'none')+'">';
  h += '<div class="fs11 c6 mb1">Copy anything from Excel, web pages, JSON or lists and paste it here:</div>';
  h += '<textarea id="impPaste" rows="6" placeholder="ABC GmbH, Hans, hans@abc.de, Germany&#10;or paste JSON / web content / chat logs directly&#10;AI cleans it into a standard format" style="width:100%;font-size:13px;padding:10px 12px;border:1px solid #d1d5db;border-radius:6px;font-family:Consolas,monospace"></textarea>';
  h += '</div>';

  h += '<div class="mb3"><label class="fs11 c6" style="display:block;margin-bottom:2px">Where are these customers from?<span class="fs10" style="color:#94a3b8">(pick one for later stats)</span></label>';
  h += '<select id="impSource" style="max-width:300px;padding:8px 10px;border:1px solid #d1d5db;border-radius:6px;font-size:13px">';
  ['Trade Show','Industry directory','Website / online','Referral','My own list','Customs data','Other'].forEach(function(v){
    h += '<option value="'+v+'">'+v+'</option>';
  });
  h += '</select></div>';

  h += '<button class="btn" style="background:#2563eb;font-size:13px" id="impPreviewBtn">🤖 Read & organize with AI</button>';
  h += '<div id="impPreview" class="mt3"></div>';
  h += '<div id="impCsvR" class="mt2"></div>';
  h += '</div>';
  box.innerHTML = h;

  document.getElementById('impModeFile').onclick = function(){ window._impMode='file'; renderBatch(box); };
  document.getElementById('impModePaste').onclick = function(){ window._impMode='paste'; renderBatch(box); };

  function validEmail(s){ return /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(String(s||'').trim()); }
  function normCompany(s){ return String(s||'').trim().toLowerCase().replace(/[^a-z0-9\u4e00-\u9fa5]/g,''); }

  // 格式嗅探：JSON/网页内容直接拦下，不当作表格
  function parseRows(text){
    var t = String(text||'').trim();
    if(!t) return {error:'Content is empty - paste table content or choose a file'};
    if(/^[\{\[]/.test(t)){
      var parsed = null;
      try { parsed = JSON.parse(t); }
      catch(e){ return {error:'Invalid JSON - please fix and retry'}; }
      var arr = null;
      if(Array.isArray(parsed)) arr = parsed;
      else if(parsed && typeof parsed === 'object'){
        var wrap = ['customers','contacts','leads','rows','data','items','results'];
        for(var wi=0; wi<wrap.length; wi++){
          if(Array.isArray(parsed[wrap[wi]])){ arr = parsed[wrap[wi]]; break; }
        }
        if(!arr && (parsed.company || parsed.email || parsed.contact || parsed['Company'] || parsed['Email'])) arr = [parsed];
      }
      if(!arr || !arr.length) return {error:'No customer array found in the JSON'};
      var order = ['company','contact','title','phone','email','country','website','industry','size','linkedin','note','source_channel','development_batch','timezone','parent_company','first_name','last_name','decision_maker','dm_title','dm_email','dm_linkedin','status','sales_stage'];
      var header = order.filter(function(k){ return arr.some(function(o){ return o && o[k] !== undefined && o[k] !== null && String(o[k]).trim() !== ''; }); });
      var extra = [];
      arr.forEach(function(o){ if(o && typeof o === 'object'){ Object.keys(o).forEach(function(k){ if(order.indexOf(k)<0 && extra.indexOf(k)<0 && String(o[k]||'').trim()) extra.push(k); }); } });
      header = header.concat(extra);
      var rows = [header];
      arr.forEach(function(o){
        if(!o || typeof o !== 'object') return;
        rows.push(header.map(function(k){ return (o[k] === undefined || o[k] === null) ? '' : String(o[k]); }));
      });
      return {rows: rows};
    }
    if(/<[a-z][\s\S]*>/i.test(t) && !/,/.test(t)) return {error:'This looks like web/code content, not a table. Copy Excel/CSV table content instead.'};
    return {rows: Papa.parse(t, {header:false, skipEmptyLines:true}).data};
  }

  // 按系统字段识别列：别名全量 + 关键词兜底，尽量把表头都认出来
  function mapColumns(header){
    var aliases = {
      company: ['company','company_name','company name','organization','organisation','客户名','客户名称','Company','企业名称','企业','单位','firma','exhibitor'],
      contact: ['contact','contact_name','contact person','contact name','person','name','full name','Contact','Contact姓名','姓名','名字','负责人','代表','联系名','ansprechpartner','kunde'],
      title: ['title','position','job_title','job title','job','role','function','Title','职务','头衔','岗位','职称','funktion','beruf','jobtitel'],
      phone: ['phone','tel','telephone','mobile','cell','contact number','联系Phone','Phone','手机','手机号','手机号码','Phone号码','telefon','handy','telefonnummer'],
      email: ['email','e-mail','e mail','mail','email address','Email','邮件','电子邮件','信箱','e-mail-adresse','email adresse'],
      country: ['country','nation','国家','地区','Country / Region','country/region','land','国'],
      website: ['website','url','web','domain','网址','Website','主页','homepage','site','webseite'],
      industry: ['industry','sector','Industry','领域','类别','category','branche'],
      size: ['size','company size','employees','employee count','no of employees','人数','员工数','规模','团队规模','mitarbeiter'],
      linkedin: ['linkedin','linkedin url','linkedin profile','领英','领英链接'],
      note: ['note','notes','remarks','remark','Note','说明','补充','address','地址','sonstiges'],
      first_name: ['first_name','first name','firstname','名','given name','vorname'],
      last_name: ['last_name','last name','lastname','姓','surname','family name','nachname'],
      source_channel: ['source','source channel','Source','来源','渠道','source_channel'],
      development_batch: ['batch','development batch','开发批次','批次','Trade Show名','Trade Show','trade show'],
      timezone: ['timezone','time zone','时区','zone'],
      parent_company: ['parent company','parent','母公司','集团','总公司','holding'],
      decision_maker: ['decision maker','decision-maker','dm name','决策人','决策人姓名','主要负责人','key decision maker'],
      dm_title: ['dm title','decision maker title','决策人Title','决策人职务'],
      dm_email: ['dm email','decision maker email','决策人Email','决策人邮件'],
      dm_linkedin: ['dm linkedin','decision maker linkedin','决策人领英']
    };
    var norm = [];
    for(var i=0;i<header.length;i++) norm.push(String(header[i]||'').toLowerCase().trim());
    var colMap = {}, used = {};
    // 第一轮：完整别名精确匹配
    for(var f in aliases){
      for(var j=0;j<aliases[f].length;j++){
        var idx = norm.indexOf(aliases[f][j]);
        if(idx>=0 && !used[idx]){ colMap[f]=idx; used[idx]=true; break; }
      }
    }
    // 第二轮：关键词兜底（带排除，避免“Company称”被当成姓名）
    function fuzzy(field, regexes, exclude){
      if(colMap[field]!==undefined) return;
      for(var k=0;k<norm.length;k++){
        var hh = norm[k];
        if(used[k] || !hh) continue;
        if(exclude && exclude.test(hh)) continue;
        for(var r=0;r<regexes.length;r++){
          if(regexes[r].test(hh)){ colMap[field]=k; used[k]=true; return; }
        }
      }
    }
    fuzzy('company', [/公司|企业|客户|firma|exhibitor|organisation|organization/i]);
    fuzzy('contact', [/Contact|姓名|名字|负责人|代表|contact|person|^name$/i], /公司|企业|客户|firma/i);
    fuzzy('title', [/Title|职务|头衔|岗位|职称|title|position|job|role|funktion|beruf/i]);
    fuzzy('phone', [/Phone|手机|phone|tel|mobile|handy|telefon/i]);
    fuzzy('email', [/Email|邮件|信箱|email|e-mail|mail/i]);
    fuzzy('country', [/国家|地区|country|nation|land/i]);
    fuzzy('website', [/网址|Website|主页|website|url|web|homepage|site/i], /linkedin/i);
    fuzzy('industry', [/Industry|领域|类别|industry|sector|branche/i]);
    fuzzy('size', [/规模|人数|员工|employees|company size|mitarbeiter/i]);
    fuzzy('linkedin', [/领英|linkedin/i]);
    fuzzy('note', [/Note|说明|地址|note|remarks|address/i]);
    fuzzy('first_name', [/^名$|first.?name|given name|vorname/i]);
    fuzzy('last_name', [/^姓$|last.?name|surname|family name|nachname/i]);
    fuzzy('source_channel', [/来源|渠道|source/i]);
    fuzzy('development_batch', [/批次|Trade Show|batch|trade show/i]);
    fuzzy('timezone', [/时区|timezone|time zone/i]);
    fuzzy('parent_company', [/母公司|集团|总公司|parent/i]);
    fuzzy('decision_maker', [/决策人|decision.?maker/i]);
    fuzzy('dm_title', [/决策人Title|决策人职务|dm title/i]);
    fuzzy('dm_email', [/决策人Email|决策人邮件|dm email/i]);
    fuzzy('dm_linkedin', [/决策人领英|dm linkedin/i]);
    // 没有公司列时的保底：取第一列（尽量不把“姓名”当公司）
    if(colMap.company===undefined && header.length>=1 && colMap.contact!==0) colMap.company=0;
    return colMap;
  }

  // 内容级兜底：表头没标出来的Email/领英/网址/Phone，从单元格内容里自动认
  function detectByContent(row, colMap, cust){
    var used = {};
    for(var f in colMap) used[colMap[f]] = 1;
    for(var i=0;i<row.length;i++){
      if(used[i]) continue;
      var v = String(row[i]||'').trim();
      if(!v) continue;
      if(!cust.email && /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(v)){ cust.email=v; used[i]=1; continue; }
      if(!cust.linkedin && /linkedin\.com\/in\//i.test(v)){ cust.linkedin=v; used[i]=1; continue; }
      if(!cust.website && !cust.linkedin && /^(https?:\/\/)?([\w-]+\.)+[a-z]{2,}(\/\S*)?$/i.test(v) && !/linkedin/i.test(v)){ cust.website=v; used[i]=1; continue; }
      if(!cust.phone && /^\+?[0-9][\d\s\-().]{6,}$/.test(v) && !/[a-z\u4e00-\u9fa5]/i.test(v)){ cust.phone=v; used[i]=1; continue; }
    }
    // 名 + 姓 分列时合并成Contact
    if(!cust.contact && (cust.first_name || cust.last_name)){
      cust.contact = String(cust.first_name||'').trim() + (cust.first_name && cust.last_name ? ' ' : '') + String(cust.last_name||'').trim();
    }
    delete cust.first_name;
    delete cust.last_name;
  }

  // 逐行校验：必填 / Email格式 / Duplicate in batch
  function validateCustomers(customers){
    var seen = {}, rows = [];
    customers.forEach(function(c){
      var st = 'ok', reason = '';
      // 清理Email转义：\@ → @（粘贴内容里常见）
      if(c.email) c.email = String(c.email).replace(/\\@/g, '@').trim();
      var hasKey = (c.company||'').trim() || (c.email||'').trim() || (c.website||'').trim();
      if(!hasKey){ st='error'; reason='Missing Company/Email/website'; }
      else if(c.email && !validEmail(c.email)){ st='error'; reason='Invalid Email format'; }
      else {
        // 去重键：优先Email；没Email才用 公司+Contact（同一家公司不同人不是重复）
        var k = (c.email||'').toLowerCase() || (normCompany(c.company) + '|' + normCompany(c.contact||''));
        if(k && seen[k]){ st='dup'; reason='Duplicate in batch (same Email/Contact)'; }
        else if(k){ seen[k]=true; }
      }
      rows.push({status: st, reason: reason, data: c});
    });
    return rows;
  }

  function processRows(rows){
    if(!rows || rows.length < 2){ T('No data found - first row should be the header', '#eab308'); return; }
    var header = rows[0].map(function(x){ return String(x||''); });
    var colMap = mapColumns(header);
    if(!colMap.company && !colMap.email && !colMap.website){
      T('Could not recognize the header - first row needs column names like Company / Email / website', '#dc2626'); return;
    }
    var customers = [];
    for(var ri=1; ri<rows.length; ri++){
      var row = rows[ri];
      if(!row || !row.length) continue;
      var cust = {};
      for(var f in colMap){
        var v = String(row[colMap[f]]||'').trim();
        if(v) cust[f] = v;
      }
      detectByContent(row, colMap, cust);
      // 只有Email没有Company时，用Email域名推断（结果里会标注待确认）
      if(!cust.company && cust.email){
        var dm = (cust.email.split('@')[1]||'').split('.')[0]||'';
        if(dm){
          cust.company = dm.replace(/[-_]/g,' ').replace(/\b\w/g, function(ch){ return ch.toUpperCase(); });
          cust.note = ((cust.note||'') + ' Company name inferred from email domain - pending confirmation').trim();
        }
      }
      if(cust.company || cust.email || cust.website) customers.push(cust);
    }
    if(!customers.length){ T('No customer info recognized - make sure the table has Company, Email or website', '#eab308'); return; }

    showPreview(customers);
  }

  // 校验 + 统计标色预览 + 确认
  function showPreview(customers){
    var validated = validateCustomers(customers);
    var ok = validated.filter(function(r){ return r.status==='ok'; }).length;
    var dup = validated.filter(function(r){ return r.status==='dup'; }).length;
    var bad = validated.filter(function(r){ return r.status==='error'; }).length;

    var ph = '<div class="card" style="border-top:2px solid #2563eb;padding:14px 16px">';
    ph += '<div class="fs12 mb2">✅ Organized <b>' + customers.length + '</b>  customers</div>';
    ph += '<div class="flex g2 fw mb2">'
      + '<span style="font-size:11px;padding:2px 10px;border-radius:10px;background:#ecfdf5;color:#047857">✅ OK ' + ok + '</span>'
      + '<span style="font-size:11px;padding:2px 10px;border-radius:10px;background:#fffbeb;color:#b45309">⚠️ Duplicates ' + dup + '</span>'
      + '<span style="font-size:11px;padding:2px 10px;border-radius:10px;background:#fef2f2;color:#b91c1c">🔴 Issues ' + bad + '</span>'
      + '</div>';
    ph += '<div class="fs11 c6 mb1">Preview the result (first 15 rows):</div>';
    ph += '<table style="font-size:11px;width:100%;border-collapse:collapse">'
      + '<tr style="color:#64748b"><th style="text-align:left">Company</th><th>Contact</th><th>Title</th><th>Country</th><th>Email</th><th>Phone</th><th>Status</th></tr>';
    validated.slice(0,15).forEach(function(r){
      var c = r.data;
      var bg = r.status==='ok' ? '' : r.status==='dup' ? '#fffbeb' : '#fef2f2';
      var stl = r.status==='ok' ? '✅' : r.status==='dup' ? '⚠️ Duplicate in batch' : '🔴 ' + r.reason;
      ph += '<tr style="background:'+bg+'"><td>'+(c.company||'—')+'</td><td>'+(c.contact||'—')+'</td><td>'+(c.title||'—')+'</td><td>'+(c.country||'—')+'</td><td>'+(c.email||'—')+'</td><td>'+(c.phone||'—')+'</td><td>'+stl+'</td></tr>';
    });
    if(validated.length > 15) ph += '<tr><td colspan="7" style="color:#94a3b8">... and ' + (validated.length-15) + ' more rows</td></tr>';
    ph += '</table>';

    var toImport = validated.filter(function(r){ return r.status !== 'error'; }).map(function(r){ return r.data; });
    ph += '<div class="mt3"><button class="btn" style="background:#059669" id="impDoBtn">Import ' + toImport.length + ' customers</button>'
      + ' <button class="btn btn-b" id="impCancelBtn">Cancel, start over</button></div>';
    ph += '<div class="fs11 c6 mt2">Duplicates in the batch are removed automatically; rows with issues are excluded and will not be imported.</div>';
    ph += '</div>';
    document.getElementById('impPreview').innerHTML = ph;
    window._pendingImport = toImport;

    document.getElementById('impDoBtn').onclick = function(){
      var source = document.getElementById('impSource').value;
      doBatchImport(window._pendingImport, source);
    };
    document.getElementById('impCancelBtn').onclick = function(){
      document.getElementById('impPreview').innerHTML = '';
      window._pendingImport = null;
    };
  }

  document.getElementById('impPreviewBtn').onclick = function(){
    if(mode === 'paste'){
      var txt = document.getElementById('impPaste').value;
      if(!txt.trim()){ T('Paste something first', '#eab308'); return; }
      T('AI is organizing...', '#7c3aed');
      api('/ai/import-parse', {method:'POST', body:{text: txt}}).then(function(r){
        if(r && r.customers && r.customers.length){ showPreview(r.customers); }
        else if(r && r.error){ T(r.error, '#dc2626'); }
        else { T('AI could not recognize it - try pasting in table format', '#eab308'); }
      }).catch(function(){
        // AI 失败兜底：按表格解析
        var p = parseRows(txt);
        if(p.error){ T(p.error, '#dc2626'); return; }
        processRows(p.rows);
      });
      return;
    }
    var file = document.getElementById('impCsv').files[0];
    if(!file){ T('Choose a file first, or switch to Paste list', '#eab308'); return; }
    T('Reading file...', '#2563eb');
    var reader = new FileReader();
    reader.onload = function(e){
      var rows = [];
      try{
        if(/\.xlsx?$/i.test(file.name)){
          var wb = XLSX.read(e.target.result, {type:'array'});
          var sheet = wb.Sheets[wb.SheetNames[0]];
          rows = XLSX.utils.sheet_to_json(sheet, {header:1});
        }else{
          var text = new TextDecoder('utf-8').decode(e.target.result);
          var pr = parseRows(text);
          if(pr.error){ T(pr.error, '#dc2626'); return; }
          rows = pr.rows;
        }
      }catch(err){ T('Cannot read file: ' + err.message, '#dc2626'); return; }
      processRows(rows);
    };
    reader.readAsArrayBuffer(file);
  };
}

function doBatchImport(customers, source){
  T('Importing ' + customers.length + '  customers...', '#2563eb');
  api('/prospects/import-show-list', {method:'POST', body:{
    customers: customers,
    source: source,
    auto_score: true
  }}).then(function(r){
    var html = '<div class="mt2" style="color:#059669;font-size:14px">✅ Import complete: ' + r.imported + '  new customers';
    if(r.skipped) html += '  | Skipped: ' + r.skipped;
    html += '</div>';
    if(r.warnings && r.warnings.length) html += '<div class="fs11 mt1" style="color:#b45309">⚠ ' + r.warnings.slice(0,5).join('; ') + (r.warnings.length>5 ? '; +' + r.warnings.length + ' more' : '') + '</div>';
    if(r.scored) html += '<div class="fs11 mt1" style="color:#7c3aed">✨ ' + r.scored + '  customers auto-researched and scored</div>';
    if(r.errors && r.errors.length) html += '<div class="fs11 mt1" style="color:#dc2626">⚠ ' + r.errors.slice(0,3).join('; ') + '</div>';
    document.getElementById('impCsvR').innerHTML = html;
    T('Import complete: ' + r.imported + ' customers');
    showNextStep('Import complete', 'Imported <b>' + r.imported + '</b>  customers - go to <b>Customer List</b> and contact the highest-scored first.', 'Go to Customer List', 'list');
  }).catch(function(e){
    var msg = 'Import failed';
    if(e.detail) msg += ': ' + String(e.detail).substring(0,150);
    else if(e.message) msg += ': ' + String(e.message).substring(0,150);
    T(msg, '#dc2626');
  });
}
