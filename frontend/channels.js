// Channels.js — Gemini-style chat per client. Each client gets a persistent chat panel.
// Left sidebar: client list. Right panel: selected client's full chat with AI + timeline.

let chSelectedPid = 0;
let chChatHistory = {}; // { pid: [{role:'user'|'ai', text:'...'}] }

async function RChannels(p) {
  var clients = [];
  try {
    var res = await api('/prospects?limit=100');
    clients = res.items || [];
    for (var i = 0; i < clients.length; i++) {
      try {
        var ix = await api('/interactions/' + clients[i].id);
        clients[i]._totalIx = ix.length;
        clients[i]._latest = ix.length > 0 ? ix[ix.length-1] : null;
      } catch(e) { clients[i]._totalIx = 0; clients[i]._latest = null; }
    }
  } catch(e) { clients = []; }

  // Show all clients — active/score at top via sort
  clients.sort(function(a, b) {
    var aTime = a._latest ? new Date(a._latest.interacted_at || 0).getTime() : 0;
    var bTime = b._latest ? new Date(b._latest.interacted_at || 0).getTime() : 0;
    return bTime - aTime || (parseInt(b.ai_score) || 0) - (parseInt(a.ai_score) || 0);
  });

  if (chSelectedPid === 0 && clients.length > 0) {
    chSelectedPid = clients[0].id;
  }

  // Restore from localStorage
  if (!chChatHistory[chSelectedPid]) {
    try {
      var saved = localStorage.getItem('ch_chat_' + chSelectedPid);
      if (saved) chChatHistory[chSelectedPid] = JSON.parse(saved);
    } catch(e) {}
  }

  var h = '';
  h += '<div style="display:flex;height:calc(100vh - 80px);gap:0">';

  // ── LEFT: Client list ──
  h += '<div style="width:280px;flex-shrink:0;overflow-y:auto;border-right:1px solid #e5e7eb;padding:8px;background:#f8fafc">';
  h += '<div style="padding:8px 4px 12px;font-size:11px;font-weight:600;color:#64748b;text-transform:uppercase;letter-spacing:.5px">Clients</div>';
  if (!clients.length) {
    h += '<div style="text-align:center;padding:24px;color:#94a3b8;font-size:12px">No clients yet.<br>Import and score prospects first.</div>';
  } else {
    clients.forEach(function(c) {
      var active = c.id === chSelectedPid;
      var scoreColor = parseInt(c.ai_score) >= 75 ? '#16a34a' : parseInt(c.ai_score) >= 50 ? '#ca8a04' : '#64748b';
      h += '<div style="padding:10px 12px;margin-bottom:2px;border-radius:6px;cursor:pointer;'+(active?'background:#e0e7ff;border:1px solid #3b82f6;':'background:#fff;border:1px solid transparent;')+'" data-ch-select="'+c.id+'">';
      h += '<div style="font-weight:600;font-size:13px">'+E(c.company)+'</div>';
      h += '<div style="display:flex;justify-content:space-between;align-items:center;margin-top:3px">';
      h += '<span style="font-size:11px;color:#64748b">'+E(c.country||'')+(c.profile_type?' | '+E(c.profile_type):'')+'</span>';
      if (c.ai_score) h += '<span style="font-size:12px;font-weight:700;color:'+scoreColor+'">'+c.ai_score+'</span>';
      h += '</div>';
      h += '<div style="font-size:10px;color:#94a3b8;margin-top:2px">'+(c._totalIx||0)+' interactions</div>';
      h += '</div>';
    });
  }
  h += '</div>';

  // ── RIGHT: Chat panel ──
  h += '<div style="flex:1;display:flex;flex-direction:column;background:#fff">';
  if (chSelectedPid > 0) {
    var prospect = null;
    try { prospect = await api('/prospects/' + chSelectedPid); } catch(e) {}
    var interactions = [];
    try { interactions = await api('/interactions/' + chSelectedPid); } catch(e) {}

    // Header
    h += '<div style="padding:12px 16px;border-bottom:1px solid #e5e7eb;background:#f8fafc;display:flex;justify-content:space-between;align-items:center">';
    h += '<div>';
    h += '<span style="font-weight:700;font-size:15px">'+E(prospect ? prospect.company : 'Client')+'</span>';
    if (prospect && prospect.ai_score) {
      var sc = parseInt(prospect.ai_score);
      var scC = sc >= 75 ? '#16a34a' : sc >= 50 ? '#ca8a04' : '#64748b';
      h += '<span style="margin-left:8px;font-size:12px;color:'+scC+';font-weight:600">'+sc+'/100</span>';
    }
    if (prospect && prospect.profile_type) {
      h += '<span style="margin-left:8px;font-size:11px;padding:1px 6px;border-radius:3px;background:#e0e7ff;color:#4338ca">'+E(prospect.profile_type)+'</span>';
    }
    h += '</div>';
    h += '<div style="display:flex;gap:6px">';
  h += '<button class="btn btn-sm" style="background:#f59e0b;color:#fff" id="chAiSuggest">AI Recommend</button>';
  h += '<button class="btn btn-sm" style="background:#6366f1" id="chUploadChat">Upload chat</button>';
    h += '</div>';
    h += '</div>';

    // Messages area
    h += '<div id="chMessages" style="flex:1;overflow-y:auto;padding:16px;background:#f9fafb">';

    // Timeline
    if (interactions.length > 0) {
      h += '<div style="margin-bottom:16px;padding:10px 12px;background:#f1f5f9;border-radius:8px;font-size:11px;color:#475569">';
      h += '<div style="font-weight:600;margin-bottom:6px">Timeline</div>';
      interactions.sort(function(a, b) { return new Date(b.interacted_at || 0) - new Date(a.interacted_at || 0); });
      interactions.slice(0, 5).forEach(function(ix) {
        var icon = ix.channel === 'linkedin' ? 'In' : ix.channel === 'whatsapp' ? 'WA' : ix.channel === 'phone' ? 'Tel' : ix.channel === 'email' ? '@' : '?';
        var dir = ix.direction === 'inbound' ? 'Received' : 'Sent';
        h += '<div style="margin-bottom:3px">'+fd(ix.interacted_at)+' | '+icon+' '+dir+': '+E((ix.subject||ix.content||'').substring(0,60))+'</div>';
      });
      if (interactions.length > 5) h += '<div style="color:#94a3b8">... '+(interactions.length-5)+' more</div>';
      h += '</div>';
    }

    // Chat messages
    var history = chChatHistory[chSelectedPid] || [];
    if (history.length === 0) {
      try {
        var s = localStorage.getItem('ch_chat_' + chSelectedPid);
        if (s) { chChatHistory[chSelectedPid] = JSON.parse(s); history = chChatHistory[chSelectedPid]; }
      } catch(e) {}
    }
    if (history.length === 0) {
      h += '<div style="text-align:center;padding:32px;color:#94a3b8">';
      h += '<div style="font-size:32px;margin-bottom:8px">?</div>';
      h += '<div style="font-size:13px;margin-bottom:4px">AI assistant ready</div>';
  h += '<div style="font-size:11px">I have full context of this client.<br>Ask anything or click "AI Recommend" for strategy.</div>';
      h += '</div>';
    } else {
      history.forEach(function(msg) {
        var isUser = msg.role === 'user';
        h += '<div style="display:flex;gap:8px;margin-bottom:12px;'+(isUser?'justify-content:flex-end':'')+'">';
        if (!isUser) h += '<div style="width:28px;height:28px;border-radius:50%;background:#6366f1;color:#fff;text-align:center;line-height:28px;font-size:12px;flex-shrink:0">AI</div>';
        h += '<div style="max-width:70%;padding:10px 14px;border-radius:12px;font-size:13px;line-height:1.6;white-space:pre-wrap;'+(isUser?'background:#3b82f6;color:#fff;':'background:#fff;border:1px solid #e5e7eb;')+'">'+E(msg.text)+'</div>';
        if (isUser) h += '<div style="width:28px;height:28px;border-radius:50%;background:#64748b;color:#fff;text-align:center;line-height:28px;font-size:12px;flex-shrink:0">You</div>';
        h += '</div>';
      });
    }
    h += '</div>';

    // Input
    h += '<div style="padding:10px 16px;border-top:1px solid #e5e7eb;background:#fff;display:flex;gap:8px">';
    h += '<input id="chInput" placeholder="Type message... (Enter to send)" style="flex:1;font-size:13px;padding:8px 12px;border-radius:8px">';
    h += '<button class="btn" style="background:#6366f1" id="chSend">Send</button>';
    h += '</div>';
  }
  h += '</div>';
  h += '</div>';

  p.innerHTML = h;

  // ── Bindings ──

  p.querySelectorAll('[data-ch-select]').forEach(function(b) {
    b.addEventListener('click', function() {
      chSelectedPid = parseInt(b.dataset.chSelect);
      RChannels(p);
    });
  });

  var sendBtn = document.getElementById('chSend');
  if (sendBtn) sendBtn.addEventListener('click', function() { doSendMessage(p, chSelectedPid, prospect, interactions); });

  var chatInput = document.getElementById('chInput');
  if (chatInput) chatInput.addEventListener('keydown', function(e) {
    if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); doSendMessage(p, chSelectedPid, prospect, interactions); }
  });

  var aiBtn = document.getElementById('chAiSuggest');
  if (aiBtn) aiBtn.addEventListener('click', function() { handleChAiSuggest(chSelectedPid); });

  var upBtn = document.getElementById('chUploadChat');
  if (upBtn) upBtn.addEventListener('click', function() { showChatUploadModal(chSelectedPid); });

  // Scroll to bottom
  var msgDiv = document.getElementById('chMessages');
  if (msgDiv) { setTimeout(function() { msgDiv.scrollTop = msgDiv.scrollHeight; }, 100); }
}

// Separate send function — uses getElementById so it works after re-renders
async function doSendMessage(p, pid, prospect, interactions) {
  var inp = document.getElementById('chInput');
  if (!inp) return;
  var msg = inp.value.trim();
  if (!msg) return;
  inp.value = '';

  if (!chChatHistory[pid]) chChatHistory[pid] = [];
  chChatHistory[pid].push({role: 'user', text: msg});
  localStorage.setItem('ch_chat_'+pid, JSON.stringify(chChatHistory[pid]));

  // Show thinking
  chChatHistory[pid].push({role: 'ai', text: '...'});
  RChannels(p);

  var ctx = '';
  if (prospect) {
    ctx += 'Client: ' + E(prospect.company) + ' | Country: ' + E(prospect.country) + ' | Industry: ' + E(prospect.industry) + '\n';
    ctx += 'Size: ' + E(prospect.size) + ' | Website: ' + E(prospect.website) + '\n';
    ctx += 'Score: ' + (prospect.ai_score||'?') + '/100 | ' + E(prospect.profile_type||'') + ' | ' + E(prospect.value_level||'') + '\n';
    ctx += 'Reason: ' + E(prospect.score_reason||'').substring(0,300) + '\n';
    if (prospect.note) ctx += 'Note: ' + E(prospect.note) + '\n';
  }
  ctx += '\nAll interactions:\n';
  (interactions||[]).forEach(function(ix, i) {
    ctx += (i+1) + '. ' + (ix.direction==='inbound'?'[IN]':'[OUT]') + ' ' + (ix.channel||'email') + ' ' + (ix.interacted_at||'') + '\n';
    if (ix.subject) ctx += '   Subject: ' + ix.subject + '\n';
    if (ix.content) ctx += '   ' + ix.content.substring(0,400) + '\n';
  });
  ctx += '\nUser: ' + msg;

  try {
    var res = await api('/ai/chat', {method: 'POST', body: {prompt: 'You are an expert B2B sales assistant. Context:\n' + ctx + '\n\nAnswer in Chinese. Be concise and actionable. If asked for strategy, recommend specific channels and draft messages.', prospect_id: pid}});
    var reply = (res.model?'['+res.model+'] ':'') + (res.result || res.content || JSON.stringify(res));
    chChatHistory[pid].pop();
    chChatHistory[pid].push({role: 'ai', text: reply});
    localStorage.setItem('ch_chat_'+pid, JSON.stringify(chChatHistory[pid]));
  } catch(e) {
    chChatHistory[pid].pop();
    chChatHistory[pid].push({role: 'ai', text: 'AI call failed.'});
  }
  RChannels(p);
}

async function handleChAiSuggest(pid) {
  if (!chChatHistory[pid]) chChatHistory[pid] = [];
  chChatHistory[pid].push({role: 'user', text: 'Analyze all interactions and recommend the best next action across all channels (email, LinkedIn, WhatsApp, phone).'});
  chChatHistory[pid].push({role: 'ai', text: '...'});
  var p = document.getElementById('mainPane');
  if (p) RChannels(p);

  try {
    var interactions = await api('/interactions/' + pid);
    var prospect = null;
    try { prospect = await api('/prospects/' + pid); } catch(e) {}

    var ctx = '';
    if (prospect) {
      ctx += 'Client: ' + E(prospect.company) + ' | ' + E(prospect.country) + ' | Score: ' + (prospect.ai_score||'?') + '/100 ' + E(prospect.profile_type||'') + '\n\n';
    }
    ctx += 'Full timeline:\n';
    interactions.forEach(function(ix, i) {
      ctx += (i+1) + '. ' + (ix.direction==='inbound'?'[IN]':'[OUT]') + ' ' + (ix.channel||'email') + ' ' + (ix.interacted_at||'') + '\n';
      if (ix.content) ctx += '   ' + ix.content.substring(0,300) + '\n';
    });

    var prompt = 'Based on all interactions, recommend the best next step:\n' + ctx + '\n\nAnswer in Chinese. Include: current stage, key signals, recommended channel (pick among: email, linkedin, whatsapp, phone), why, draft message.';
    var res = await api('/ai/chat', {method: 'POST', body: {prompt: prompt, prospect_id: pid}});
    var reply = (res.model?'['+res.model+'] ':'') + (res.result || res.content || JSON.stringify(res));
    chChatHistory[pid].pop();
    chChatHistory[pid].push({role: 'ai', text: reply});
    localStorage.setItem('ch_chat_'+pid, JSON.stringify(chChatHistory[pid]));
    if (p) RChannels(p);
  } catch(e) {
    chChatHistory[pid].pop();
    chChatHistory[pid].push({role: 'ai', text: 'Analysis failed.'});
    RChannels(p);
  }
}

function showChatUploadModal(pid) {
  var oldM = document.getElementById('chUpMask'); if (oldM) oldM.remove();
  var oldC = document.getElementById('chUpModal'); if (oldC) oldC.remove();
  var h = '<div class="mask" style="z-index:80" id="chUpMask"></div>';
  h += '<div id="chUpModal" class="card" style="position:fixed;top:10%;left:50%;transform:translateX(-50%);width:550px;max-width:90vw;z-index:90;padding:24px;background:#fff">';
  h += '<div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:16px"><h3>Upload Conversation</h3><button style="border:none;background:none;font-size:20px;cursor:pointer" onclick="document.getElementById(\'chUpMask\').remove();document.getElementById(\'chUpModal\').remove()">&times;</button></div>';
  h += '<label style="font-size:11px;color:#64748b">Channel</label><select id="chUpChan" style="margin-bottom:8px"><option value="linkedin">LinkedIn</option><option value="whatsapp">WhatsApp</option><option value="phone">Phone</option><option value="other">Other</option></select>';
  h += '<label style="font-size:11px;color:#64748b">Paste conversation</label><textarea id="chUpContent" rows="10" style="margin-bottom:8px;font-size:12px" placeholder="Paste the full chat here. AI will understand both sides of the conversation."></textarea>';
  h += '<button class="btn" style="background:#16a34a" id="chUpSave">Save & Notify AI</button>';
  h += '</div>';
  document.body.insertAdjacentHTML('beforeend', h);
  document.getElementById('chUpMask').onclick = function() { document.getElementById('chUpMask').remove(); document.getElementById('chUpModal').remove(); };

  document.getElementById('chUpSave').addEventListener('click', async function() {
    var chan = document.getElementById('chUpChan').value;
    var content = document.getElementById('chUpContent').value.trim();
    if (!content) { T('Paste content first'); return; }
    try {
      await api('/interactions', {method: 'POST', body: {direction: 'inbound', channel: chan, content: content, prospect_id: pid}});
      T('Saved');
      document.getElementById('chUpMask').remove();
      document.getElementById('chUpModal').remove();
      if (!chChatHistory[pid]) chChatHistory[pid] = [];
      chChatHistory[pid].push({role: 'user', text: '[Uploaded '+chan+' conversation]\n'+content.substring(0,200)+(content.length>200?'...':'')});
      chChatHistory[pid].push({role: 'ai', text: 'Loaded this '+chan+' conversation into context.'});
      localStorage.setItem('ch_chat_'+pid, JSON.stringify(chChatHistory[pid]));
      var p = document.getElementById('mainPane');
      if (p) RChannels(p);
    } catch(e) { T('Save failed'); }
  });
}
