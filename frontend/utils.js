// ═══ GLOBAL STATE ═══
const BASE='/api';
let view='list',prospects=[],totalResults=0,page=1,totalPages=1;
let drawerOpen=false,dp=null,ed={},dtab='info',drIntel={},drSeqs=[],drInts=[],drCaseMatches=[],scrResult=null,msgResult=null;
let drDrafts=[];
let _intChatSaved = '';
let _intChatScrollTop = 0;
let _seqChatSaved = '';
let emailFilter='inbox',eqData=[],eqInbox=[];
let filters={status:'',sales_stage:'',source_channel:'',profile_type:'',profile_source:'',value_level:'',kbCat:'',sort:'',order:'desc'};
let _listLoaded=false,_emailLoaded=false;
let activeModel='auto';
let authToken=localStorage.getItem('td_token')||'';
let currentUser=null;
let needActivation=false;   // 交付版未激活：只显示激活页
try{ currentUser=JSON.parse(localStorage.getItem('td_user')||'null'); }catch(e){ currentUser=null; }
let usersMap={};
let _kbGuide = { show: false, guidelinesScore: 100 };

// HELPERS
function T(m,c,d){c=c||'#059669';var e=document.createElement('div');e.className='toast';e.style.background=c;e.textContent=m;document.body.appendChild(e);setTimeout(function(){e.remove()},d||2500)}

// ── 草稿去向提示：任何地方“存入草稿”后，告诉客户下一步去哪发送 ──
function showDraftHint(msg){
  T(msg || 'Saved to drafts', '#f59e0b', 4000);
  showNextStep('📝 ' + (msg || 'Saved to drafts'), 'Next: review and edit in <b>Email Center > Drafts</b>, then click Confirm and Send.', 'Go to Email Center', 'email');
}

// ── 通用“下一步”引导：任何操作完成后，告诉客户下一步去哪 ──
function showNextStep(title, body, btnLabel, targetView){
  var old = document.getElementById('draftHintBox');
  if(old) old.remove();
  var box = document.createElement('div');
  box.id = 'draftHintBox';
  box.style.cssText = 'position:fixed;right:16px;bottom:16px;z-index:9999;background:#fff;border:1px solid #f59e0b;border-left:4px solid #f59e0b;border-radius:10px;box-shadow:0 8px 30px rgba(0,0,0,.16);padding:14px 16px;max-width:330px';
  box.innerHTML = '<div style="font-size:13px;font-weight:600;color:#0f172a">' + E(title) + '</div>'
    + '<div style="font-size:12px;color:#64748b;margin-top:5px;line-height:1.6">' + body + '</div>'
    + '<div style="display:flex;gap:8px;margin-top:10px">'
    + '<button class="btn btn-sm" style="background:#f59e0b" id="draftHintGo">' + E(btnLabel || 'View') + '</button>'
    + '<button class="btn btn-sm btn-b" id="draftHintClose">Got it</button></div>';
  document.body.appendChild(box);
  var go = box.querySelector('#draftHintGo');
  if(go) go.onclick = function(){ box.remove(); nav(targetView || 'list'); };
  var close = box.querySelector('#draftHintClose');
  if(close) close.onclick = function(){ box.remove(); };
  setTimeout(function(){ if(box.parentNode) box.remove(); }, 12000);
}
async function api(p,o){o=o||{};if(o.body&&typeof o.body!=='string')o.body=JSON.stringify(o.body);var ctrl=new AbortController(),timer=setTimeout(function(){ctrl.abort()},o.timeout||120000);try{var hdrs={'Content-Type':'application/json'};if(authToken)hdrs.Authorization='Bearer '+authToken;var r=await fetch(BASE+p,{headers:hdrs,method:o.method||'GET',body:o.body,signal:ctrl.signal});clearTimeout(timer);if(!r.ok){var t=await r.text();try{t=JSON.parse(t).detail||t}catch(e){t=t||r.statusText};var e=new Error(t);e.status=r.status;e.detail=t;if(e.status===401&&p.indexOf('/auth/')!==0){authToken='';localStorage.removeItem('td_token');currentUser=null;localStorage.removeItem('td_user');if(view!=='login'){view='login';render();}}throw e}return r.json()}catch(e){clearTimeout(timer);throw e}}
function E(s){if(s==null)return'';return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;')}

// fetch wrapper that injects the login token; used by flows that upload files
// or download blobs, where the api() helper's JSON handling does not fit.
async function authFetch(url, opts){
  opts = opts || {};
  var hdrs = opts.headers || {};
  if(authToken) hdrs.Authorization = 'Bearer ' + authToken;
  opts.headers = hdrs;
  return fetch(url, opts);
}

// ── AI 文本 → 干净 HTML（压缩空行/空段落，markdown 粗体→b）──
function cleanAiHtml(text){
  if(!text) return '';
  var t = String(text);
  // 提取 <body>...</body> 内容（AI 排版可能返回完整 HTML 文档，丢弃框架）
  var bodyMatch = t.match(/<body[^>]*>([\s\S]*?)<\/body>/i);
  if(bodyMatch){ t = bodyMatch[1]; }
  else {
    // 没有 body 但有 <html> 框架时，去掉 <head> 和 <html> 标签
    t = t.replace(/<!DOCTYPE[^>]*>/gi, '');
    t = t.replace(/<head[\s\S]*?<\/head>/gi, '');
    t = t.replace(/<\/?html[^>]*>/gi, '');
  }
  // HTML 标签之间的空白（换行/缩进）压缩掉，避免 pre-wrap 渲染出空白行
  if(/<[a-z][\s\S]*>/i.test(t)){
    // 用 DOM 解析：把文本节点里的连续空白/换行/缩进折叠成单个空格
    try {
      var _div = document.createElement('div');
      _div.innerHTML = t;
      (function collapse(node){
        var kids = node.childNodes;
        for(var i=0;i<kids.length;i++){
          var n = kids[i];
          if(n.nodeType === 3){ // 文本节点
            n.nodeValue = n.nodeValue.replace(/\s+/g, ' ');
          } else if(n.nodeType === 1){
            collapse(n);
          }
        }
      })(_div);
      t = _div.innerHTML;
    } catch(e){}
    // 兜底：标签之间的空白再压一遍
    t = t.replace(/>\s+</g, '><');
    t = t.replace(/^\s+|\s+$/g, '');
  }
  // 去掉 markdown 代码块围栏
  t = t.replace(/```[a-zA-Z]*\n?/g, '');
  // 去掉表格分隔行（| --- | --- |）
  t = t.replace(/^\s*\|?[\s:|-]+\|[\s:|-]*$/gm, '');
  // markdown 表格行 → 简洁列表（去管道符）
  t = t.replace(/^\s*\|(.+)\|\s*$/gm, '$1');
  t = t.replace(/\|/g, ' · ');
  // markdown 标题 ## → <b>
  t = t.replace(/^#{1,4}\s*(.+)$/gm, '<b>$1</b>');
  // 编号列表 1. 2. 保留数字
  t = t.replace(/^\s*(\d+)[.)]\s+/gm, '$1. ');
  // 空段落（含 &nbsp;）→ 空
  t = t.replace(/<p>\s*(&nbsp;|\s)*<\/p>/gi, '');
  // 连续 <br>（2+）→ 1 个
  t = t.replace(/(<br\s*\/?>\s*){2,}/gi, '<br>');
  // markdown 粗体 → <b>
  t = t.replace(/\*\*(.+?)\*\*/g, '<b>$1</b>');
  // 单星号斜体 → <i>（避免撞上普通星号）
  t = t.replace(/(^|[^*])\*([^*\n]+)\*/g, '$1<i>$2</i>');
  // 行首 - 或 • → 列表点
  t = t.replace(/^\s*[-•]\s+/gm, '• ');
  // 连续换行（3+）→ 2 个（段落间距）
  t = t.replace(/\n{3,}/g, '\n\n');
  // 纯文本换行 → <br>（仅当输入不含 HTML 标签时）
  if(!/<[a-z][\s\S]*>/i.test(t)){
    t = t.replace(/\n/g, '<br>');
  }
  // 去掉开头结尾多余空白
  return t.trim();
}

// ── 本地确定性排版（替代 AI 排版：稳定、立即生效、不烧 token）──
function _isPriceRow(line){
  // 价格行：行内含 ≥2 个小数价格，如 "82.86     78.72     74.57"
  // 排除含 pcs / 说明词的普通行（如 "Rod Lens ... 300 pcs - USD 6.50/pc"）
  if(/(pcs|moq|lead time|shipping|spec:|below table|quantity)/i.test(line)) return false;
  var nums = line.match(/\d+\.\d{2}/g) || [];
  return nums.length >= 2;
}

function _isTableHeader(line){
  // 表头必须像 "10-19 pcs  20-49 pcs  50+ pcs" 这种数量区间格式
  return /(\d+\s*[-–]\s*\d+\s*pcs|\d+\+\s*pcs)/i.test(line);
}

function _splitRow(line){
  // 按 2+ 空格切列（价格表）
  return line.split(/\s{2,}/).map(function(s){ return s.trim(); }).filter(Boolean);
}

function _renderTable(rows){
  var cols = [];
  rows.forEach(function(r){
    _splitRow(r).forEach(function(c, i){ cols[i] = true; });
  });
  var n = cols.length;
  var html = '<table style="border-collapse:collapse;margin:6px 0;font-size:12px">';
  rows.forEach(function(r, ri){
    var cells = _splitRow(r);
    html += '<tr>';
    cells.forEach(function(c, ci){
      var isHead = ri === 0 && _isTableHeader(rows[0]);
      var tag = isHead ? 'th' : 'td';
      html += '<'+tag+' style="border:1px solid #d7dee8;padding:5px 10px;text-align:left;'+(isHead?'background:#f7f9fc;font-weight:600;':'')+'">'+E(c)+'</'+tag+'>';
      // 补齐空列保持对齐
      if(ci === cells.length - 1 && cells.length < n){
        for(var k = cells.length; k < n; k++) html += '<'+tag+' style="border:1px solid #d7dee8;padding:5px 10px"></'+tag+'>';
      }
    });
    html += '</tr>';
  });
  html += '</table>';
  return html;
}

function formatEmailBody(text){
  if(!text) return '';
  // 把现有 HTML/换行统一成纯文本行
  var plain = String(text)
    .replace(/<br\s*\/?>/gi, '\n')
    .replace(/<\/p>\s*/gi, '\n\n')
    .replace(/<\/div>\s*/gi, '\n\n')
    .replace(/<\/tr>\s*/gi, '\n')
    .replace(/<\/td>\s*/gi, '\t')
    .replace(/<\/li>\s*/gi, '\n')
    .replace(/<li[^>]*>/gi, '- ')
    .replace(/<[^>]+>/g, '')
    .replace(/&nbsp;/g, ' ')
    .replace(/&lt;/g, '<').replace(/&gt;/g, '>').replace(/&amp;/g, '&')
    .replace(/&quot;/g, '"')
    .replace(/\r/g, '');
  var lines = plain.split('\n').map(function(s){ return s.replace(/\s+$/,''); });
  var out = [];
  var i = 0;
  while(i < lines.length){
    var line = lines[i].trim();
    if(!line){ i++; continue; }
    // 价格表格块（表头行或价格行，且不是普通段落）
    if(_isTableHeader(line) || _isPriceRow(line)){
      var rows = [];
      while(i < lines.length){
        var l = lines[i].trim();
        if(!l) break;
        if(_isTableHeader(l) || _isPriceRow(l)){
          // 缩进说明行（如 "(our spec: ...)"）并入上一行单元格
          if(/^\(/.test(l) && rows.length){ rows[rows.length-1] += ' ' + l; }
          else rows.push(l);
          i++;
        } else if(/^\(/.test(l) && rows.length){
          rows[rows.length-1] += ' ' + l; i++;
        } else break;
      }
      if(rows.length >= 1) out.push(_renderTable(rows));
      continue;
    }
    // 圆点列表
    if(/^[-•]\s+/.test(line)){
      var items = [];
      while(i < lines.length && /^[-•]\s+/.test(lines[i].trim())){
        items.push(lines[i].trim().replace(/^[-•]\s+/, ''));
        i++;
      }
      out.push('<ul style="margin:6px 0;padding-left:20px">'+items.map(function(x){ return '<li>'+E(x)+'</li>'; }).join('')+'</ul>');
      continue;
    }
    // 普通段落：收集连续非空行
    var para = [];
    while(i < lines.length){
      var l2 = lines[i].trim();
      if(!l2) break;
      if(_isTableHeader(l2) || _isPriceRow(l2) || /^[-•]\s+/.test(l2)) break;
      para.push(l2); i++;
    }
    if(para.length) out.push('<p style="margin:6px 0">'+E(para.join(' '))+'</p>');
  }
  return out.join('\n');
}

// ── 清理富文本编辑器产生的垃圾，保留有价值的 HTML 结构（表格/段落/列表）──
function cleanRichHtml(raw){
  if(!raw) return '';
  var t = String(raw);
  // 去掉空块（只有空白的 div/p/li）
  t = t.replace(/<(div|p|li|tr|td|th)[^>]*>\s*(<br\s*\/?>)?\s*<\/(div|p|li|tr|td|th)>/gi, '');
  // 去掉纯空 div 包裹
  t = t.replace(/<div[^>]*><\/div>/gi, '');
  // div → 换行（富文本编辑器常用 div 分段）
  t = t.replace(/<\/div>\s*/gi, '\n');
  t = t.replace(/<div[^>]*>/gi, '');
  // 保留 <br> 但清理连续多个
  t = t.replace(/(<br\s*\/?>\s*){2,}/gi, '<br>');
  // 去掉 span 的垃圾内联样式（保留文本）
  t = t.replace(/<span[^>]*>/gi, '').replace(/<\/span>/gi, '');
  // 去掉空 <b>/<strong>/<i>/<u>
  t = t.replace(/<(b|strong|i|u)[^>]*>\s*<\/(b|strong|i|u)>/gi, '');
  // 压缩段落间空白
  t = t.replace(/>\s+</g, '><');
  t = t.trim();
  return t;
}

// ── HTML → 纯文本（开发计划编辑框显示用，避免标签露出来）──
function htmlToPlain(text){
  if(!text) return '';
  var t = String(text)
    .replace(/<br\s*\/?>/gi, '\n')
    .replace(/<\/p>/gi, '\n')
    .replace(/<\/div>/gi, '\n')
    .replace(/<\/tr>/gi, '\n')
    .replace(/<\/td>/gi, '\t')
    .replace(/<\/li>/gi, '\n')
    .replace(/<[^>]+>/g, '')
    .replace(/&nbsp;/g, ' ')
    .replace(/&lt;/g, '<').replace(/&gt;/g, '>').replace(/&amp;/g, '&')
    .replace(/&quot;/g, '"');
  return t.replace(/\n{3,}/g, '\n\n').trim();
}
function fd(d){if(!d)return'';try{var s=String(d);if(!/[Zz]/.test(s)&&!/[+-]\d{2}:?\d{2}$/.test(s)&&/\d:\d/.test(s))s+='Z';return new Date(s).toLocaleString('zh-CN')}catch(e){return d}}
function bindSafe(parent,sel,ev,fn){var el=parent.querySelector(sel);if(el)el.addEventListener(ev,fn)}
// NAV
function nav(v){
  view=v; page=1;
  document.querySelectorAll('.nv').forEach(function(a){
    a.classList.toggle('active', a.dataset.v===v);
  });
  render();
  if(location.hash !== '#'+v){
    try{ location.hash = v; }catch(e){}
  }
}
function render(){
  var m=document.getElementById('mainPane');m.innerHTML='';
  if(authToken && currentUser && needActivation){
    RActivate(m);
    return;
  }
  if(authToken && currentUser && view!=='login'){
    var today = new Date().toISOString().slice(0,10);
    var keyDay = 'td_kb_day_'+currentUser.id;
    var remindedToday = localStorage.getItem(keyDay) === today;
    if(_kbGuide.show && localStorage.getItem('td_kb_hide_'+currentUser.id)!=='1'){
      m.innerHTML = '<div style="background:#fffbeb;border:1px solid #fde68a;border-radius:8px;padding:10px 14px;margin-bottom:12px;display:flex;align-items:center;gap:10px;flex-wrap:wrap">'
        + '<span>🎯 Your <b>customer profile</b> is not defined yet——AI does not know who to develop for you yet.</span>'
        + '<button class="btn btn-sm" style="background:#0f766e" onclick="goProfileCoach()">Define profiles</button></div>' + m.innerHTML;
    } else if(!_kbGuide.show && _kbGuide.guidelinesScore < 100 && !remindedToday){
      m.innerHTML = '<div style="background:#ecfdf5;border:1px solid #a7f3d0;border-radius:8px;padding:10px 14px;margin-bottom:12px;display:flex;align-items:center;gap:10px;flex-wrap:wrap">'
        + '<span>📈 Did you <b>refine your customer profile</b> today? The more the AI knows you, the sharper your outreach — add a little every week and results keep improving.</span>'
        + '<button class="btn btn-sm" style="background:#0f766e" onclick="goProfileCoach()">Refine</button>'
        + '<a href="#" style="font-size:11px;color:#b45309" onclick="hideKbRemindToday();return false">Not today</a></div>' + m.innerHTML;
    }
  }
  if(view==='login'){RLogin(m);return;}
  if(view==='import')RImport(m);
  else if(view==='list'){
    if(authToken && currentUser && !_listLoaded){ m.innerHTML='<div class="empty-state card">Loading customer list...</div>'; loadList(); }
    else RList(m);
  }
  else if(view==='ops')ROps(m);
  else if(view==='deals')RDeals(m);
  else if(view==='reminders')RReminders(m);
  else if(view==='today')RToday(m);
  else if(view==='email'){
    if(authToken && currentUser && !_emailLoaded){ m.innerHTML='<div class="empty-state card">Loading emails...</div>'; loadEmail().then(function(){ render(); }).catch(function(){ render(); }); }
    else REmail(m);
  }
  else if(view==='knowledge')RKB(m);
  else if(view==='backup')RBackup(m);
  else if(view==='setup')RSetup(m);
  else if(view==='team')RTeam(m);
  else if(view==='analytics')RAnalytics(m);
  else if(view==='members')RMembers(m);
}


// ── 合并页：数据分析（复盘 / 业绩 / 案例）──
async function RAnalytics(p){
  var tabs=[['review','Review'],['performance','Performance'],['case','Win Cases'],['ops','Auto Research']];
  if(currentUser && currentUser.role==='member'){
    tabs = tabs.filter(function(t){ return t[0] !== 'review'; });
  }
  var cur=localStorage.getItem('td_an_tab')||'review';
  if(cur==='review' && currentUser && currentUser.role==='member') cur='performance';
  p.innerHTML='<div class="tab-bar">'+tabs.map(function(t){return '<button data-an="'+t[0]+'" class="'+(t[0]===cur?'active':'')+'" style="font-size:13px">'+t[1]+'</button>';}).join('')+'</div><div id="anBody"></div>';
  p.querySelectorAll('[data-an]').forEach(function(b){ b.onclick=function(){ localStorage.setItem('td_an_tab',b.dataset.an); RAnalytics(p); }; });
  var body=document.getElementById('anBody');
  if(cur==='review')await RReview(body);
  else if(cur==='performance')await RPerformance(body);
  else if(cur==='case')await RCaseIntel(body);
  else if(cur==='ops')await ROps(body);
}


// ── 合并页：成员与权限（用户 / Audit Log）──
async function RMembers(p){
  var tabs=[['users','User Management'],['audit','Audit Log']];
  var cur=localStorage.getItem('td_mb_tab')||'users';
  p.innerHTML='<div class="tab-bar">'+tabs.map(function(t){return '<button data-mb="'+t[0]+'" class="'+(t[0]===cur?'active':'')+'" style="font-size:13px">'+t[1]+'</button>';}).join('')+'</div><div id="mbBody"></div>';
  p.querySelectorAll('[data-mb]').forEach(function(b){ b.onclick=function(){ localStorage.setItem('td_mb_tab',b.dataset.mb); RMembers(p); }; });
  var body=document.getElementById('mbBody');
  if(cur==='users')await RUsers(body);else await RAudit(body);
}


// ── Model switcher ──
async function initModelSwitcher(){
  try{var r=await api('/ai/model');activeModel=r.active_model||'auto';var eff=r.effective_default||activeModel}catch(e){activeModel='auto';eff='auto'}
  var sel=document.getElementById('modelSwitcher');
  if(sel){sel.value=activeModel;sel.addEventListener('change',async function(){try{var r=await api('/ai/model',{method:'POST',body:{model:sel.value}});if(r.success){activeModel=r.active_model;T('AI model switched: '+modelLabel(activeModel),'#6366f1');updateModelIndicator()}else{T(r.error||'Failed','#f87171');sel.value=activeModel}}catch(e){T('Switch failed','#f87171');sel.value=activeModel}})}
  updateModelIndicator();
}
function updateModelIndicator(){
  var sel=document.getElementById('modelSwitcher');
  if(sel)sel.value=activeModel;
  var badge=document.getElementById('modelBadge');
  if(!badge)return;
  var c={auto:'#64748b',deepseek:'#22d3ee',openai:'#059669',gemini:'#a78bfa'}[activeModel]||'#64748b';
  var n={auto:'Auto',deepseek:'DS',openai:'GPT',gemini:'Gem'}[activeModel]||activeModel;
  badge.textContent=n;badge.style.background=c;badge.style.display='inline-block';
}
function modelLabel(m){return ({auto:'Smart',deepseek:'DeepSeek',openai:'OpenAI',gemini:'Gemini'})[m]||m}

// ── Per-panel model selector helpers ──
function renderModelSelector(key, labelText){
  var val = localStorage.getItem(key) || 'auto';
  var label = labelText || '';
  var h = label ? '<span class="fs11 c6" style="margin-right:2px">'+label+'</span>' : '';
  return h+'<select class="panel-model-sel" data-model-key="'+key+'" style="font-size:10px;padding:1px 4px;border:1px solid #d1d5db;border-radius:4px;background:#fff;color:#6b7280;cursor:pointer;max-width:46px" onchange="localStorage.setItem(\''+key+'\',this.value)">'
    + '<option value="auto"'+(val==='auto'?' selected':'')+'>Auto</option>'
    + '<option value="deepseek"'+(val==='deepseek'?' selected':'')+'>DS</option>'
    + '<option value="openai"'+(val==='openai'?' selected':'')+'>GPT</option>'
    + '<option value="gemini"'+(val==='gemini'?' selected':'')+'>Gem</option>'
    + '</select>';
}
function getPanelModel(key){
  return localStorage.getItem(key) || 'auto';
}
// ── Sender selector (dual email) ──
window._senderList = null;
async function loadSenders(){
  try{
    var r = await api('/email/senders');
    if(Array.isArray(r)) window._senderList = r;
  }catch(e){}
}
function senderLabel(key){
  if(window._senderList){
    for(var i=0;i<window._senderList.length;i++){
      if(window._senderList[i].key===key){
        return window._senderList[i].email || window._senderList[i].label || fallbackSenderLabel(key);
      }
    }
  }
  return fallbackSenderLabel(key);
}
function fallbackSenderLabel(key){
  return key==='primary' ? 'Work mailbox 1' : (key==='secondary' ? 'Work mailbox 2' : (key==='third' ? 'Work mailbox 3' : key));
}
function renderSenderSelector(savedKey, labelText, preferKey){
  var label = labelText || 'Sender';
  var keys = ['primary','secondary','third'];
  if(window._senderList && window._senderList.length){
    keys = window._senderList.map(function(s){ return s.key; });
  }
  // 成员只能看到自己绑定的邮箱（绑定由主账号配置）
  if(currentUser && currentUser.role === 'member' && window._senderList){
    var mine = window._senderList.filter(function(s){ return s.bound_user_id === currentUser.id; });
    if(mine.length){
      keys = mine.map(function(s){ return s.key; });
    }else{
      keys = [];
    }
  }
  if(!keys.length){
    return '<span class="fs11" style="color:#dc2626">⚠ No sending mailbox bound; ask the owner to bind one in System Settings > Email Accounts</span>';
  }
  var stored = null; try{ stored = localStorage.getItem(savedKey); }catch(e){}
  // 优先级：该客户上次用的 > 全局默认 > 本机上次选的 > 第一个可用
  var val = keys[0];
  if(preferKey && keys.indexOf(preferKey) >= 0) val = preferKey;
  else if(currentUser && currentUser.default_sender && keys.indexOf(currentUser.default_sender) >= 0) val = currentUser.default_sender;
  else if(stored && keys.indexOf(stored) >= 0) val = stored;
  if(preferKey){ try{ localStorage.setItem(savedKey, val); }catch(e){} }
  var opts = keys.map(function(k){
    return '<option value="'+k+'"'+(val===k?' selected':'')+'>'+E(senderLabel(k))+'</option>';
  }).join('');
  var hint = '';
  if(preferKey) hint = '（Last used for this customer; you can change）';
  else if(currentUser && currentUser.default_sender) hint = '（Default sender）';
  else if(currentUser && currentUser.role !== 'member') hint = '（First choice is remembered for this customer）';
  var hintHtml = hint ? '<span class="fs11" style="color:#94a3b8">'+hint+'</span>' : '';
  return '<span class="fs11 c6" style="margin-right:2px">'+label+':</span>'
    + '<select class="sender-sel" data-sender-key="'+savedKey+'" style="font-size:10px;padding:1px 4px;border:1px solid #d1d5db;border-radius:4px;background:#fff;color:#6b7280;cursor:pointer;max-width:200px" onchange="rememberSender(\''+savedKey+'\',this.value)">'
    + opts
    + '</select>' + hintHtml;
}
// 记住发件选择：① 存到当前客户（下次给该客户发默认用它）② 没设全局默认则顺手设为默认
async function rememberSender(savedKey, key){
  try{ localStorage.setItem(savedKey, key); }catch(e){}
  if(!currentUser || currentUser.role === 'member') return;
  var saved = false;
  try{
    if(typeof dp !== 'undefined' && dp && dp.id){
      await api('/prospects/'+dp.id, {method:'PATCH', body:{sender_key:key}});
      dp.sender_key = key;
      saved = true;
    }
  }catch(e){}
  try{
    if(!currentUser.default_sender){
      var r = await api('/auth/default-sender', {method:'POST', body:{sender_key:key}});
      if(r && r.user) currentUser.default_sender = r.user.default_sender || '';
      try{ localStorage.setItem('td_user', JSON.stringify(currentUser)); }catch(e){}
    }
  }catch(e){}
  T('Remembered: '+senderLabel(key)+(saved ? '（default for this customer next time）' : '（Default sender）'), '#16a34a');
}
function getSenderKey(savedKey){
  var s = null; try{ s = localStorage.getItem(savedKey); }catch(e){}
  if(s) return s;
  if(currentUser && currentUser.default_sender){
    return currentUser.default_sender;
  }
  return 'primary';
}
// ── END sender selector helpers ──

// ── 客户画像分类（默认 + 客户自定义）──
window._profileCats = null;
async function loadProfileCats(){
  try{
    var r = await api('/setup/profile-categories');
    if(r && Array.isArray(r.categories)) window._profileCats = r.categories;
  }catch(e){}
}

// ── 邮件签名模板（按客户画像 A-E，系统配置可编辑）──
window._profileSignatures = null;
async function loadProfileSignatures(){
  try{
    var r = await api('/setup/signatures');
    if(r && r.signatures) window._profileSignatures = r.signatures;
  }catch(e){}
}
function profileCatLabel(key){
  if(window._profileCats){
    for(var i=0;i<window._profileCats.length;i++){
      if(window._profileCats[i].key===key) return window._profileCats[i].label;
    }
  }
  return ({A:'A - High-value target',B:'B - OEM / integrator',C:'C - Emerging-market brand',D:'D - Niche assembler',E:'E - Repair / service'})[key] || key;
}
function profileCatKeys(){
  if(window._profileCats && window._profileCats.length) return window._profileCats.map(function(c){ return c.key; });
  return ['A','B','C','D','E'];
}
function profileCatOptionsHtml(selectedKey){
  var h = '';
  profileCatKeys().forEach(function(k){
    h += '<option value="'+E(k)+'" '+(selectedKey===k?'selected':'')+'>'+E(profileCatLabel(k))+'</option>';
  });
  return h;
}

// ── Email verification ──
async function verifySingleEmail(id){
  var btn = document.getElementById('verifyBtn'+id);
  if(btn){ btn.disabled = true; btn.textContent = 'Verifying...'; }
  try {
    var r = await api('/prospects/'+id+'/verify-email', {method:'POST'});
    if(r.success){
      var v = r.result.verdict;
      if(v==='valid') T('✅ '+r.result.recommendation, '#16a34a');
      else if(v==='risky') T('⚠️ '+r.result.recommendation, '#f59e0b');
      else T('❌ '+r.result.recommendation, '#dc2626');
      // Refresh drawer if open for this prospect
      if(dp && dp.id===id){ try{ openDrawer(id); }catch(e){} }
      loadList();
    } else {
      T('Verification failed: '+E(r.error||''), '#dc2626');
    }
  } catch(e){
    T('Verification error: '+E(e.detail||e.message||''), '#dc2626');
  }
  if(btn){ btn.disabled = false; btn.textContent = 'Verify'; }
}

async function batchVerifyEmails(ids, btn){
  if(!ids.length){ T('No email addresses to verify', '#f59e0b'); return; }
  btn.disabled = true;
  btn.textContent = 'Verifying...';
  try {
    var r = await api('/prospects/verify-emails', {method:'POST', body:{ids:ids}});
    if(r.success){
      var valid = r.valid || 0;
      var invalid = r.invalid || 0;
      var risky = r.risky || 0;
      T('Bulk verification done: ✅'+valid+' valid, '+risky+' risky, '+invalid+' invalid', invalid>0?'#dc2626':'#16a34a');
      loadList();
    } else {
      T('Bulk verification failed: '+E(r.error||''), '#dc2626');
    }
  } catch(e){
    T('Bulk verification error: '+E(e.detail||e.message||''), '#dc2626');
  }
  btn.disabled = false;
  btn.textContent = 'Verify email addresses';
}

async function init(){
  var hv=(location.hash||'').replace(/^#\/?/,'');
  var validViews=['today','list','import','deals','reminders','email','knowledge','backup','ops','setup','team','analytics','members'];
  if(authToken){
    try{
      var me=await api('/auth/me');
      currentUser=me.user;
      needActivation=!!me.need_activation;
      localStorage.setItem('td_user',JSON.stringify(currentUser));
    }catch(e){
      authToken='';localStorage.removeItem('td_token');currentUser=null;localStorage.removeItem('td_user');
      needActivation=false;
    }
  }
  if(!authToken){ view='login'; }
  else if(validViews.indexOf(hv)!==-1) view=hv;
  initModelSwitcher();
  if(authToken && !needActivation){
    await loadSenders();
    await loadList();await loadEmail();updateHiringBadge();
    loadProfileCats();
    loadProfileSignatures();
    await loadKbGuide();
    maybeShowFirstGuide();
  }
  initVersion();
  applyUserUI();
  render();
}
window.addEventListener('hashchange',function(){
  var hv=(location.hash||'').replace(/^#\/?/,'');
  if(hv && hv!==view && (hv==='login'||hv==='team'||['today','list','import','deals','reminders','email','knowledge','backup','ops','setup','analytics','members'].indexOf(hv)!==-1)){
    if(!authToken){ view='login'; document.querySelectorAll('.nv').forEach(function(a){a.classList.toggle('active',a.dataset.v==='login')}); render(); return; }
    view=hv;page=1;
    document.querySelectorAll('.nv').forEach(function(a){a.classList.toggle('active',a.dataset.v===hv)});
    render();
  }
});

function doLogin(token,user,needAct){
  authToken=token;currentUser=user;
  needActivation=!!needAct;
  localStorage.setItem('td_token',token);
  localStorage.setItem('td_user',JSON.stringify(user));
  applyUserUI();
  if(needActivation){
    nav('login');  // 渲染逻辑会拦截并显示激活页
  }else{
    nav('today');
    showWelcomeGuide();
  }
}

// ── 老板首次登录四步向导：添加业务员 → 配邮箱/API → 导入客户 → 完善知识库 ──
function showWelcomeGuide(){
  try{
    if(!currentUser || currentUser.role !== 'owner') return;
    var em = (currentUser.email||'').toLowerCase();
    if(em.indexOf('@demo.com') !== -1) return;          // 演示账号不弹
    var key = 'td_welcome_'+currentUser.id;
    if(localStorage.getItem(key)==='1') return;         // 已点“Got it”
    var box = document.createElement('div');
    box.id = 'welcomeBox';
    box.style.cssText = 'position:fixed;right:16px;bottom:16px;z-index:9999;background:#fff;border:1px solid #c7d2fe;border-left:4px solid #6366f1;border-radius:10px;box-shadow:0 8px 30px rgba(0,0,0,.16);padding:16px 18px;max-width:360px';
 box.innerHTML = '<div style="font-size:14px;font-weight:700;color:#1e1b4b">🎉 Welcome to B2B Outbound OS!</div>'
      + '<div style="font-size:12px;color:#64748b;margin-top:4px;line-height:1.7">Four steps to get started:</div>'
      + '<div style="margin-top:8px;display:flex;flex-direction:column;gap:6px">'
      + '<button class="btn btn-sm" style="background:#eef2ff;color:#3730a3;border:1px solid #c7d2fe;text-align:left" onclick="nav(\'users\');hideWelcomeGuide(false)">① Add a sales rep (team account)</button>'
      + '<button class="btn btn-sm" style="background:#eef2ff;color:#3730a3;border:1px solid #c7d2fe;text-align:left" onclick="nav(\'setup\');hideWelcomeGuide(false)">② Configure email / AI keys</button>'
      + '<button class="btn btn-sm" style="background:#eef2ff;color:#3730a3;border:1px solid #c7d2fe;text-align:left" onclick="nav(\'import\');hideWelcomeGuide(false)">③ Import your customers</button>'
      + '<button class="btn btn-sm" style="background:#eef2ff;color:#3730a3;border:1px solid #c7d2fe;text-align:left" onclick="nav(\'knowledge\');hideWelcomeGuide(false)">④ Build your knowledge base (the AI gets smarter)</button>'
      + '</div>'
      + '<div style="display:flex;justify-content:space-between;margin-top:12px">'
      + '<a href="#" style="font-size:11px;color:#94a3b8" onclick="hideWelcomeGuide(false);return false">Later</a>'
      + '<a href="#" style="font-size:11px;color:#6366f1" onclick="hideWelcomeGuide(true);return false">Got it — don\'t show again</a></div>';
    document.body.appendChild(box);
  }catch(e){}
}
function hideWelcomeGuide(remember){
  var box = document.getElementById('welcomeBox');
  if(box) box.remove();
  if(remember && currentUser){
    try{ localStorage.setItem('td_welcome_'+currentUser.id, '1'); }catch(e){}
  }
}
function doLogout(){
  authToken='';currentUser=null;
  _listLoaded=false;_emailLoaded=false;prospects=[];eqData=[];eqInbox=[];
  localStorage.removeItem('td_token');localStorage.removeItem('td_user');
  try{ api('/auth/logout',{method:'POST',body:{}}); }catch(e){}
  applyUserUI();
  view='login';render();
  if(location.hash){ try{ location.hash=''; }catch(e){} }
}
async function downloadApi(path){
  var hdrs={};
  if(authToken)hdrs.Authorization='Bearer '+authToken;
  var r=await fetch(BASE+path,{headers:hdrs});
  if(!r.ok){var t=await r.text();try{t=JSON.parse(t).detail||t}catch(e){t=t||r.statusText}throw new Error(t)}
  var blob=await r.blob();
  var url=URL.createObjectURL(blob);
  var a=document.createElement('a');a.href=url;a.download=path.split('/').pop()||'export.json';document.body.appendChild(a);a.click();a.remove();
  setTimeout(function(){URL.revokeObjectURL(url)},8000);
}
async function uploadApi(path, file, extraFields){
  var fd=new FormData(); fd.append('file', file);
  if(extraFields) Object.keys(extraFields).forEach(function(k){ fd.append(k, extraFields[k]); });
  var hdrs={}; if(authToken)hdrs.Authorization='Bearer '+authToken;
  var r=await fetch(BASE+path,{method:'POST',body:fd,headers:hdrs});
  var t=await r.text(); var j=null; try{j=JSON.parse(t)}catch(e){}
  if(!r.ok){ var e=new Error((j&&j.detail)||t||r.statusText); e.detail=(j&&j.detail)||t; throw e; }
  return j;
}
function applyUserUI(){
  var userBox=document.getElementById('sidebarUser');
  if(userBox){
    if(currentUser){ userBox.innerHTML='<div style="font-size:10px;color:#e2e8f0">'+E(currentUser.name)+' <span style="color:#64748b">('+(currentUser.role==='owner'?'Owner':currentUser.role==='admin'?'Admin':'Member')+')</span></div><a href="#" style="font-size:10px;color:#94a3b8" onclick="doLogout();return false">Log out</a>'; }
    else{ userBox.innerHTML=''; }
  }
  var teamLink=document.querySelector('.nv[data-v="team"]');
  if(teamLink){ teamLink.style.display=(!currentUser||currentUser.role!=='member')?'':'none'; }
  var membersLink=document.querySelector('.nv[data-v="members"]');
  if(membersLink){ membersLink.style.display=(!currentUser||currentUser.role!=='member')?'':'none'; }
  var setupLink=document.querySelector('.nv[data-v="setup"]');
  if(setupLink){ setupLink.style.display=(!currentUser||currentUser.role!=='member')?'':'none'; }
}

async function loadKbGuide(){
  _kbGuide = { show: false, guidelinesScore: 100 };
  try{
    var cov = await api('/knowledge/coverage');
    var g = (cov.categories||[]).filter(function(c){ return c.category==='guidelines'; })[0];
    if(g){
      _kbGuide.guidelinesScore = g.score || 0;
      if(g.score < 65) _kbGuide.show = true;
    }
  }catch(e){}
}

function goProfileCoach(){
  if(currentUser) localStorage.setItem('td_kb_hide_'+currentUser.id, '1');
  _kbGuide.show = false;
  nav('knowledge');
  setTimeout(function(){
    var b = document.querySelector('#kbCoachBtn');
    if(b) b.click();
  }, 400);
}

function hideKbGuide(){
  if(currentUser) localStorage.setItem('td_kb_hide_'+currentUser.id, '1');
  _kbGuide.show = false;
  render();
}

function hideKbRemindToday(){
  if(currentUser){
    var today = new Date().toISOString().slice(0,10);
    localStorage.setItem('td_kb_day_'+currentUser.id, today);
  }
  render();
}

function maybeShowFirstGuide(){
  if(!authToken || !currentUser || localStorage.getItem('td_guide_v1')) return;
  localStorage.setItem('td_guide_v1', '1');
  setTimeout(function(){
    var m = document.getElementById('mainPane');
    if(!m) return;
    var h = '<div id="firstGuide" style="position:fixed;inset:0;background:rgba(15,23,42,.5);z-index:99;display:flex;align-items:center;justify-content:center">';
    h += '<div style="background:#fff;border-radius:12px;max-width:520px;width:92%;padding:24px">';
 h += '<h3 style="font-size:16px;font-weight:700;margin-bottom:4px">Welcome to B2B Outbound OS - 3 steps to teach AI about your company</h3>';
    h += '<p class="fs12 c6 mb3">AI can only work well once it knows what you sell and who you want to reach. Fill these in order.</p>';
    h += '<div class="mb2" style="background:#f8fafc;border:1px solid #e2e8f0;border-radius:8px;padding:12px"><b class="fs13">1. Company positioning</b><div class="fs11 c6">One line on what you sell and to whom</div>';
    h += '<button class="btn btn-sm" style="background:#2563eb;margin-top:8px" onclick="firstGuideGo(\'profile\')">Fill in</button></div>';
    h += '<div class="mb2" style="background:#f8fafc;border:1px solid #e2e8f0;border-radius:8px;padding:12px"><b class="fs13">2. Customer profile</b><div class="fs11 c6">Define your ideal customer (the most important one)</div>';
    h += '<button class="btn btn-sm" style="background:#0f766e;margin-top:8px" onclick="firstGuideGo(\'coach\')">Use profile coach</button></div>';
    h += '<div class="mb2" style="background:#f8fafc;border:1px solid #e2e8f0;border-radius:8px;padding:12px"><b class="fs13">3. Product specs</b><div class="fs11 c6">Give the AI real specs to cite in outreach emails</div>';
    h += '<button class="btn btn-sm" style="background:#7c3aed;margin-top:8px" onclick="firstGuideGo(\'product\')">Fill in</button></div>';
    h += '<div style="text-align:right"><a href="#" style="font-size:12px;color:#94a3b8" onclick="closeFirstGuide();return false">Later</a></div>';
    h += '</div></div>';
    m.insertAdjacentHTML('beforebegin', h);
  }, 600);
}

function firstGuideGo(which){
  closeFirstGuide();
  nav('knowledge');
  setTimeout(function(){
    if(which === 'coach'){
      var b = document.querySelector('#kbCoachBtn');
      if(b) b.click();
    }else{
      var w = document.querySelector('#kbWizardBtn');
      if(w) w.click();
    }
  }, 400);
}

function closeFirstGuide(){
  var el = document.getElementById('firstGuide');
  if(el) el.remove();
}

async function initVersion(){
  var box = document.getElementById('appVersion');
  if(!box) return;
  var ver = '1.0.0';
  try{
    var h = await api('/health');
    ver = h.version || ver;
  }catch(e){}
  box.innerHTML = '<span id="verText" style="cursor:pointer" title="Check update">v'+E(ver)+'</span>'
    + '<a href="#" style="color:#546e7a;cursor:pointer" onclick="checkUpdate();return false">Update</a>'
    + '<a href="#" style="color:#546e7a;cursor:pointer" onclick="downloadDiagnostic();return false">Diagnostics</a>';
}

async function checkUpdate(){
  try{
    var u = await api('/update/check');
    if(!u.enabled){ T('Already latest version v'+E(u.current),'#16a34a'); return; }
    if(u.error){ T('Check for updates failed: '+E(u.error),'#dc2626'); return; }
    if(u.has_update){
      var msg = 'New version found: v'+E(u.latest)+(u.notes?': '+E(u.notes):'');
      if(u.url) msg += '. Download the update package, unzip it into the update folder, and double-click update.bat';
      T(msg, '#f59e0b', 8000);
    }else{
      T('Already latest version v'+E(u.current),'#16a34a');
    }
  }catch(e){ T('Check for updates failed','#dc2626'); }
}

async function downloadDiagnostic(){
  try{
    await downloadApi('/support/diagnostic');
    T('Diagnostics package created — send it to support','#0891b2');
  }catch(e){ T('Failed to create the diagnostics package: '+E(e.message||String(e)),'#dc2626'); }
}
async function updateHiringBadge(){try{var r=await api('/prospects/stats');if(r.source_breakdown){var hc=r.source_breakdown['Hiring signal']||0;var bd=document.getElementById('hiringBadge');if(bd){if(hc>0){bd.textContent=hc;bd.style.display='inline'}else bd.style.display='none'}}}catch(e){}}

// ── Sell export ──
async function exportSellList(minScore){
  var s = prompt('Minimum AI score (1-10, default 5):', '5');
  if(s === null) return;
  var score = parseFloat(s) || 5;
  try {
    var resp = await authFetch('/api/prospects/sell-export?min_score='+score+'&limit=200', {method:'POST'});
    if(!resp.ok) { T('Export failed: HTTP ' + resp.status, '#dc2626'); return; }
    var blob = await resp.blob();
    var url = window.URL.createObjectURL(blob);
    var a = document.createElement('a');
    a.href = url;
    var disp = resp.headers.get('Content-Disposition') || '';
    var m = disp.match(/filename[^;=\n]*=((['"]).*?\2|[^;\n]*)/);
    a.download = (m && m[1]) ? m[1].replace(/['"]/g, '') : 'tuodan_sell_export.xlsx';
    document.body.appendChild(a);
    a.click();
    a.remove();
    window.URL.revokeObjectURL(url);
    var count = resp.headers.get('X-Exported-Count') || '?';
    T('Directory downloaded (' + count + ' entries)', '#16a34a');
  } catch(e) {
    T('Export error: ' + E(e.message||''), '#dc2626');
  }
}
