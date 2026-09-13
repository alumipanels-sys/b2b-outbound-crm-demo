async function RKB(p){
  var h = '<h2 class="fs20 fwb mb3">Knowledge Base</h2>';
  var cov = null;
  var gaps = [];
  try{ cov = await api('/knowledge/coverage'); }catch(e){}
  try{ gaps = await api('/knowledge/gaps?status=open') || []; }catch(e){}
  if(cov) h += renderKbHealth(p, cov, gaps);

  // ── Search bar ──
  h += '<div class="card p3 mb3" style="display:flex;gap:8px;align-items:center">';
  h += '<input id="kbSearch" placeholder="Search Knowledge Base (title + body)" style="flex:1;padding:9px 12px;border:2px solid #d1d5db;border-radius:6px;font-size:14px" value="'+(filters.kbSearch||'')+'">';
  h += '<button class="btn btn-sm" style="background:#6b7280" id="kbSearchClear">Clear</button>';
  h += '</div>';

  // ── Editor card ──
  h += '<div class="card p3 mb3" style="border:2px solid #2563eb;border-radius:8px">';
  h += '<p class="fwm mb2" style="font-size:14px">Add / edit knowledge entry  <span id="kbEditMsg" class="fs11 c6"></span></p>';
  h += '<div class="grid gcol2 g2 mb2">';
  h += '<div><label class="fs11 c6">Category</label><select id="kbCat" style="padding:7px 10px;border:1px solid #d1d5db;border-radius:4px;font-size:12px;width:100%"><option value="">Select category</option><option value="product">Product specs</option><option value="profile">Company positioning</option><option value="forbidden">Do not</option><option value="guidelines">Guidelines</option><option value="case_study">Case studies</option><option value="system_prompt">System prompt (AI behavior control)</option></select>';
  h += '<span id="kbCatHint" class="fs11" style="color:#64748b;margin-top:4px;display:block">Category auto-maps to AI features</span></div>';
  h += '<div><label class="fs11 c6">Title</label><input id="kbTitle" placeholder="Title" style="padding:7px 10px;border:1px solid #d1d5db;border-radius:4px;font-size:12px"></div>';
  h += '</div>';
  h += '<div class="mb2"><label class="fs11 c6">Tags <span style="color:#64748b;font-weight:400">leave empty to auto-generate, or use AI classify</span></label><input id="kbTags" placeholder="leave empty to auto-generate, or type tags, e.g. edge chipping, German customer" style="padding:7px 10px;border:1px solid #d1d5db;border-radius:4px;font-size:12px"></div>';
  h += '<div class="mb2"><label class="fs11 c6">Content</label><textarea id="kbContent" rows="15" placeholder="Content" style="padding:8px 10px;border:1px solid #d1d5db;border-radius:4px;font-size:13px;resize:vertical;font-family:monospace;line-height:1.5"></textarea></div>';
  h += '<div class="mb2"><label class="fs11 c6">Source URL (optional)</label><input id="kbUrl" placeholder="Source URL" style="padding:7px 10px;border:1px solid #d1d5db;border-radius:4px;font-size:12px"></div>';
  h += '<div class="flex g2 fw aic"><button class="btn btn-sm" style="background:#7c3aed" id="kbClassifyBtn">AI classify</button><button class="btn btn-sm" style="background:#2563eb" id="kbSaveBtn">Save new entry</button><button class="btn btn-sm btn-b" id="kbCancelBtn" style="display:none">Cancel edit</button><span class="fs11 c6">AI classifies and suggests; you review content before saving</span></div>';
  h += '<input type="hidden" id="kbEditId" value="">';
  h += '<input type="hidden" id="kbSource" value="manual">';
  h += '</div>';
  // ── AI 修改意见展示框 ──
  h += '<div id="kbSuggestBox" class="card p3 mb3" style="display:none;border:1px solid #c4b5fd;background:#faf5ff"></div>';

  try{
    var kb = await api('/knowledge');
    kb = kb || [];
    // 系统核心 Skill 提示词对客户隐藏（后端也已过滤，这里双保险）
    kb = kb.filter(function(k){ return (k.title||'').indexOf('Skill') === -1; });

    // Search filter
    var searchTerm = (filters.kbSearch||'').toLowerCase();
    if(searchTerm){
      kb = kb.filter(function(k){
        var inTitle = (k.title||'').toLowerCase().indexOf(searchTerm) !== -1;
        var inContent = (k.content||'').toLowerCase().indexOf(searchTerm) !== -1;
        var inTags = (k.tags||'').toLowerCase().indexOf(searchTerm) !== -1;
        return inTitle || inContent || inTags;
      });
    }

    // Category filter
    if(filters.kbCat){
      kb = kb.filter(function(k){ return k.category === filters.kbCat; });
    }

    var headerHTML = '<div class="flex aic jcs mb3"><p class="fs13 c6">';
    headerHTML += 'Total <strong style="color:#334155">'+kb.length+'</strong> entries';
    if(searchTerm) headerHTML += ' (search: <strong style="color:#2563eb">'+E(searchTerm)+'</strong>)';
    headerHTML += ' - category: ';

    // Count categories from ALL entries (pre-search)
    var allKb = await api('/knowledge');
    allKb = allKb || [];
    allKb = allKb.filter(function(k){ return (k.title||'').indexOf('Skill') === -1; });
    var cats = {};
    allKb.forEach(function(k){ cats[k.category] = (cats[k.category]||0)+1; });
    headerHTML += '<span class="badge mr2" style="cursor:pointer;background:'+(filters.kbCat?'#f3f4f6;color:#64748b':'#2563eb;color:#fff')+'" onclick="filters.kbCat=\'\';filters.kbSearch=\'\';RKB(document.getElementById(\'mainPane\'))">All</span> ';
    Object.keys(cats).forEach(function(c){
      var isActive = filters.kbCat === c;
      headerHTML += '<span class="badge mr2" style="cursor:pointer;background:'+(isActive?'#2563eb;color:#fff':'#e0e7ff;color:#3730a3')+'" onclick="filters.kbCat=\''+c+'\';RKB(document.getElementById(\'mainPane\'))">'+c+' ('+cats[c]+')</span> ';
    });
    headerHTML += '</p></div>';
    h += headerHTML;

    if(kb.length === 0){
      h += '<div class="card tc p4" style="color:#64748b">No matching entries</div>';
    }

    kb.forEach(function(k){
      var contentDisplay = E(k.content);
      var isLong = contentDisplay.length > 400;
      // Highlight search matches in content preview
      if(searchTerm && !isLong){
        contentDisplay = highlightText(contentDisplay, searchTerm);
      }

      if(isLong){
        var previewContent = E(k.content.substring(0,400));
        if(searchTerm) previewContent = highlightText(previewContent, searchTerm);
        h += '<div class="card p3 mb2" style="border-left:4px solid '+getKBCat(k.category)+'">';
        h += '<div class="flex jcs aic mb1"><div><span class="badge" style="background:#e0e7ff;color:#3730a3">'+E(k.category)+'</span> <strong class="fs14">'+(searchTerm?highlightText(E(k.title),searchTerm):E(k.title))+'</strong>';
        if(k.source_url) h += ' <a href="'+E(k.source_url)+'" target="_blank" class="fs11 c6" style="text-decoration:underline">Source link</a>';
        h += '</div><div class="flex g2"><button class="btn btn-sm" style="background:#6b7280;font-size:10px;padding:1px 8px" data-kid="'+k.id+'" data-kcat="'+E(k.category)+'" data-ktitle="'+E(k.title)+'" data-kcontent="'+E(k.content)+'" data-ktags="'+E(k.tags||'')+'">Edit</button><button class="btn btn-sm" style="background:#475569;font-size:10px;padding:1px 8px" data-hist="'+k.id+'">History</button><button class="btn btn-sm" style="background:#dc2626;font-size:10px;padding:1px 8px" data-del-kb="'+k.id+'">Delete</button></div></div>';
        h += '<pre id="kbPrev'+k.id+'" class="fs12 c6" style="white-space:pre-wrap;line-height:1.5;max-height:120px;overflow:hidden;margin:0">'+previewContent+'</pre>';
        h += '<pre id="kbFull'+k.id+'" class="fs12 c6" style="white-space:pre-wrap;line-height:1.5;display:none;margin:0">'+contentDisplay+'</pre>';
        h += '<a href="#" class="fs11" style="color:#2563eb" data-expand="'+k.id+'">Expand full content ('+E(k.content).length+' characters)</a>';
        if(k.tags){ try{ var tgs=JSON.parse(k.tags); if(tgs.length){h+='<div class="mt1">';tgs.forEach(function(t){h+='<span class="badge mr1" style="font-size:10px;background:#f1f5f9;color:#64748b">'+E(t)+'</span>'});h+='</div>';}}catch(e){} }
        h += '</div><div id="kbHist'+k.id+'" class="mb2" style="display:none"></div>';
      }else{
        var fullContent = contentDisplay;
        h += '<div class="card p3 mb2" style="border-left:4px solid '+getKBCat(k.category)+'">';
        h += '<div class="flex jcs aic mb1"><div><span class="badge" style="background:#e0e7ff;color:#3730a3">'+E(k.category)+'</span> <strong class="fs14">'+(searchTerm?highlightText(E(k.title),searchTerm):E(k.title))+'</strong>';
        if(k.source_url) h += ' <a href="'+E(k.source_url)+'" target="_blank" class="fs11 c6" style="text-decoration:underline">Source link</a>';
        h += '</div><div class="flex g2"><button class="btn btn-sm" style="background:#6b7280;font-size:10px;padding:1px 8px" data-kid="'+k.id+'" data-kcat="'+E(k.category)+'" data-ktitle="'+E(k.title)+'" data-kcontent="'+E(k.content)+'" data-ktags="'+E(k.tags||'')+'">Edit</button><button class="btn btn-sm" style="background:#475569;font-size:10px;padding:1px 8px" data-hist="'+k.id+'">History</button><button class="btn btn-sm" style="background:#dc2626;font-size:10px;padding:1px 8px" data-del-kb="'+k.id+'">Delete</button></div></div>';
        h += '<p class="fs12 c6" style="white-space:pre-wrap;line-height:1.6">'+fullContent+'</p>';
        if(k.tags){ try{ var tgs2=JSON.parse(k.tags); if(tgs2.length){h+='<div class="mt1">';tgs2.forEach(function(t){h+='<span class="badge mr1" style="font-size:10px;background:#f1f5f9;color:#64748b">'+E(t)+'</span>'});h+='</div>';}}catch(e){} }
        h += '</div><div id="kbHist'+k.id+'" class="mb2" style="display:none"></div>';
      }
    });
    p.innerHTML = h;
  }catch(e){
    p.innerHTML = h + '<div class="card tc" style="color:#999;padding:40px">Load failed</div>';
  }

  // ── Search handler (debounced) ──
  var searchInput = p.querySelector('#kbSearch');
  if(searchInput){
    var searchTimer = null;
    searchInput.addEventListener('input', function(){
      clearTimeout(searchTimer);
      searchTimer = setTimeout(function(){
        filters.kbSearch = searchInput.value.trim();
        RKB(p);
      }, 300);
    });
    // Focus at end
    searchInput.focus();
    searchInput.setSelectionRange(searchInput.value.length, searchInput.value.length);
  }

  var clearBtn = p.querySelector('#kbSearchClear');
  if(clearBtn){
    clearBtn.addEventListener('click', function(){
      filters.kbSearch = '';
      RKB(p);
    });
  }

  // ── Category hint: show what each category maps to ──
  var catSelect = p.querySelector('#kbCat');
  var catHint = p.querySelector('#kbCatHint');
  var catInfo = {
    'product': 'Auto-used by scoring and emails',
    'profile': 'Auto-used by scoring and emails',
    'guidelines': 'Auto-used by scoring and emails',
    'case_study': 'Auto-used by scoring and emails',
    'methodology': 'Auto-used by scoring and emails',
    'forbidden': 'Auto-used by scoring and emails',
    'system_prompt': 'Directly controls AI behavior',
    '': 'Select a category above'
  };
  if(catSelect && catHint){
    catSelect.addEventListener('change', function(){
      var val = this.value;
      catHint.textContent = catInfo[val] || 'Auto-matched';
      catHint.style.color = val === 'system_prompt' ? '#7c3aed' : (val ? '#16a34a' : '#6b7280');
    });
    if(catSelect.value) catSelect.dispatchEvent(new Event('change'));
  }

  var saveBtn = p.querySelector('#kbSaveBtn');
  if(saveBtn) saveBtn.addEventListener('click',async function(){
    var cat = p.querySelector('#kbCat').value.trim();
    var title = p.querySelector('#kbTitle').value.trim();
    var content = p.querySelector('#kbContent').value.trim();
    var editId = p.querySelector('#kbEditId').value;
    var urlEl = p.querySelector('#kbUrl'); var url = urlEl ? urlEl.value.trim() : null;
    if(!cat || !title || !content){ T('Fill in category, title and content'); return; }
    var tagsRaw = p.querySelector('#kbTags').value.trim();
    var tags = tagsRaw ? JSON.stringify(tagsRaw.split(',').map(function(t){return t.trim()})) : null;

    // Show loading if tags empty (AI will generate)
    var tagsInput = p.querySelector('#kbTags');
    if(!tags && content.length > 20){
      T('AI is generating tags...', '#2563eb');
      tagsInput.placeholder = 'AI generating...';
    }

    var srcEl = p.querySelector('#kbSource');
    var body = {category:cat,title:title,content:content,tags:tags,source_url:url||null,source:(srcEl?srcEl.value:'manual')};
    try{
      if(editId){
        await api('/knowledge/'+editId,{method:'PUT',body:body});
        T('Updated');
        p.querySelector('#kbEditId').value = '';
        if(srcEl) srcEl.value = 'manual';
        p.querySelector('#kbEditMsg').innerHTML = '';
        saveBtn.textContent = 'Save new entry';
      }else{
        await api('/knowledge',{method:'POST',body:body});
        T('Added');
        if(srcEl) srcEl.value = 'manual';
      }
      p.querySelector('#kbCat').value = '';
      p.querySelector('#kbTitle').value = '';
      p.querySelector('#kbContent').value = '';
      p.querySelector('#kbTags').value = '';
      if(urlEl) urlEl.value = '';
      RKB(p);
    }catch(e){T('Save failed','#dc2626');}
  });

  // ── AI  pts类整理：人工先写Content，AI 只建议 Category/Title/Tags ──
  var clsBtn = p.querySelector('#kbClassifyBtn');
  if(clsBtn) clsBtn.addEventListener('click', async function(){
    var contentEl = p.querySelector('#kbContent');
    var content = contentEl ? contentEl.value.trim() : '';
    if(!content){ T('Write content first, then let AI classify', '#f59e0b'); return; }
    clsBtn.disabled = true; clsBtn.textContent = 'AI classifying...';
    var titleEl = p.querySelector('#kbTitle');
    var catEl = p.querySelector('#kbCat');
    var body = {
      content: content,
      title: titleEl ? titleEl.value.trim() : '',
      category: catEl ? catEl.value.trim() : ''
    };
    try{
      var r = await api('/knowledge/classify', {method:'POST', body:body});
      if(!r || !r.success){ T('Classification failed: '+(r&&r.error||''), '#dc2626'); clsBtn.disabled=false; clsBtn.textContent='AI classify'; return; }
      var res = r.result || {};
      if(catEl && res.category) catEl.value = res.category;
      if(catEl) catEl.dispatchEvent(new Event('change'));
      if(titleEl && res.title) titleEl.value = res.title;
      var tagsEl = p.querySelector('#kbTags');
      if(tagsEl && Array.isArray(res.tags) && res.tags.length) tagsEl.value = res.tags.join(',');
      renderKbSuggestions(res.suggestions);
      T('AI classified as: '+(res.category||'')+'，'+(Array.isArray(res.tags)?res.tags.length+' tags':'')+' — review the suggestions before saving', '#7c3aed', 5000);
    }catch(e){
      T('Classification failed: '+(e.detail||e.message||''), '#dc2626');
    }
    clsBtn.disabled = false; clsBtn.textContent = 'AI classify';
  });

  // ── 渲染 AI 修改意见（仅供参考，用户审核决定改不改）──
  function renderKbSuggestions(sugs){
    var box = p.querySelector('#kbSuggestBox');
    if(!box) return;
    if(!sugs || !sugs.length){ box.style.display='none'; box.innerHTML=''; return; }
    var h = '<div class="flex aic jcs mb2"><span class="fs13 fwb" style="color:#6d28d9">AI suggestions</span>';
    h += '<span class="fs11 c6">For reference only - decide whether to apply; AI will not edit your content automatically</span></div>';
    h += '<div style="display:flex;flex-direction:column;gap:6px">';
    sugs.forEach(function(s){ h += '<div style="font-size:12px;color:#475569;background:#fff;border:1px solid #ede9fe;border-radius:6px;padding:7px 10px">· '+E(s)+'</div>'; });
    h += '<div style="text-align:right"><button class="btn btn-sm btn-b" id="kbSugClose" style="font-size:10px">Ignore all</button></div>';
    h += '</div>';
    box.innerHTML = h;
    box.style.display = 'block';
    var close = box.querySelector('#kbSugClose');
    if(close) close.addEventListener('click', function(){ box.style.display='none'; box.innerHTML=''; });
  }

  p.querySelectorAll('[data-kid]').forEach(function(b){
    b.addEventListener('click',function(){
      var sugBox = p.querySelector('#kbSuggestBox');
      if(sugBox){ sugBox.style.display='none'; sugBox.innerHTML=''; }
      p.querySelector('#kbEditId').value = b.dataset.kid;
      p.querySelector('#kbCat').value = b.dataset.kcat;
      // Trigger hint update
      var catSel = p.querySelector('#kbCat');
      if(catSel) catSel.dispatchEvent(new Event('change'));
      p.querySelector('#kbTitle').value = b.dataset.ktitle;
      p.querySelector('#kbContent').value = b.dataset.kcontent;
      var tagStr = b.dataset.ktags;
      if(tagStr && tagStr !== 'null'){
        try{ var parsed = JSON.parse(tagStr); p.querySelector('#kbTags').value = parsed.join(','); }
        catch(e){ p.querySelector('#kbTags').value = tagStr.replace(/[\[\]"]/g,''); }
      }
      var saveBtn = p.querySelector('#kbSaveBtn');
      if(saveBtn) saveBtn.textContent = 'Update entry';
      var cancelBtn = p.querySelector('#kbCancelBtn');
      if(cancelBtn) cancelBtn.style.display = '';
      p.querySelector('#kbEditMsg').innerHTML = '<span style="color:#f59e0b">Editing #'+b.dataset.kid+'</span>';
      window.scrollTo(0,0);
    });
  });

  p.querySelectorAll('[data-del-kb]').forEach(function(b){
    b.addEventListener('click',async function(){
      if(!confirm('Delete this knowledge entry?')) return;
      try{ await api('/knowledge/'+b.dataset.delKb,{method:'DELETE'}); T('Deleted'); RKB(p); }
      catch(e){T('Delete failed','#dc2626');}
    });
  });

  // Expand / collapse long content
  p.querySelectorAll('[data-expand]').forEach(function(a){
    a.addEventListener('click',function(e){
      e.preventDefault();
      var kid = a.dataset.expand;
      var prev = p.querySelector('#kbPrev'+kid);
      var full = p.querySelector('#kbFull'+kid);
      if(!prev || !full) return;
      if(full.style.display === 'none'){
        prev.style.display = 'none';
        full.style.display = '';
        a.textContent = 'Collapse';
      }else{
        prev.style.display = '';
        full.style.display = 'none';
        a.textContent = 'Expand full content ('+(full.textContent||'').length+' characters)';
      }
    });
  });

  // Cancel editing
  var cancelBtn = p.querySelector('#kbCancelBtn');
  if(cancelBtn){
    cancelBtn.addEventListener('click',function(){
      p.querySelector('#kbEditId').value = '';
      p.querySelector('#kbCat').value = '';
      p.querySelector('#kbTitle').value = '';
      p.querySelector('#kbContent').value = '';
      p.querySelector('#kbTags').value = '';
      var urlEl = p.querySelector('#kbUrl'); if(urlEl) urlEl.value = '';
      p.querySelector('#kbEditMsg').innerHTML = '';
      var saveBtn = p.querySelector('#kbSaveBtn');
      if(saveBtn) saveBtn.textContent = 'Save new entry';
      cancelBtn.style.display = 'none';
      // Reset hint
      var catSel = p.querySelector('#kbCat');
      if(catSel) catSel.dispatchEvent(new Event('change'));
    });
  }

  // ── Self-evolution controls ──
  var suggestBtn = p.querySelector('#kbSuggestBtn');
  if(suggestBtn) suggestBtn.addEventListener('click', function(){ loadKbSuggest(p); });
  var caseBtn = p.querySelector('#kbCaseBtn');
  if(caseBtn) caseBtn.addEventListener('click', function(){ loadKbCase(p); });
  var wizardBtn = p.querySelector('#kbWizardBtn');
  if(wizardBtn) wizardBtn.addEventListener('click', function(){
    var w = p.querySelector('#kbWizard');
    if(w){
      var show = (w.style.display === 'none' || !w.style.display);
      w.style.display = show ? '' : 'none';
      if(show) loadKbWizard(p);
    }
  });

  var coachBtn = p.querySelector('#kbCoachBtn');
  if(coachBtn) coachBtn.addEventListener('click', function(){
    var w = p.querySelector('#kbCoach');
    if(w){
      var show = (w.style.display === 'none' || !w.style.display);
      w.style.display = show ? '' : 'none';
      if(show) loadKbCoach(p);
    }
  });

  var tplBtn = p.querySelector('#kbTemplateBtn');
  if(tplBtn) tplBtn.addEventListener('click', function(){
    var w = p.querySelector('#kbTemplate');
    if(w){
      var show = (w.style.display === 'none' || !w.style.display);
      w.style.display = show ? '' : 'none';
      if(show) loadKbTemplates(p);
    }
  });

  var upBtn = p.querySelector('#kbUploadBtn');
  if(upBtn) upBtn.addEventListener('click', function(){
    var w = p.querySelector('#kbUpload');
    if(w){
      var show = (w.style.display === 'none' || !w.style.display);
      w.style.display = show ? '' : 'none';
      if(show) loadKbUpload(p);
    }
  });

  p.querySelectorAll('[data-gap-resolve]').forEach(function(b){
    b.addEventListener('click', async function(){
      try{ await api('/knowledge/gaps/'+b.dataset.gapResolve+'/resolve', {method:'POST', body:{}}); T('Gap marked done','#16a34a'); RKB(p); }
      catch(e){ T('Operation failed','#dc2626'); }
    });
  });
  p.querySelectorAll('[data-gap-ignore]').forEach(function(b){
    b.addEventListener('click', async function(){
      try{ await api('/knowledge/gaps/'+b.dataset.gapIgnore+'/ignore', {method:'POST', body:{}}); T('Ignored'); RKB(p); }
      catch(e){ T('Operation failed','#dc2626'); }
    });
  });
  p.querySelectorAll('[data-gap-fill]').forEach(function(b){
    b.addEventListener('click', function(){
      fillKbEditor(p, decodeURIComponent(b.dataset.gapFill), b.dataset.gapCat, '');
      var msg = p.querySelector('#kbEditMsg');
      if(msg) msg.innerHTML = '<span style="color:#f59e0b">Filling gap: '+E(decodeURIComponent(b.dataset.gapFill))+' (fill in and save)</span>';
    });
  });
  // 画像进化建议 → 回画像教练修订
  p.querySelectorAll('[data-gap-coach]').forEach(function(b){
    b.addEventListener('click', function(){
      var c = p.querySelector('#kbCoachBtn');
      if(c) c.click();
      setTimeout(function(){
        var coach = p.querySelector('#kbCoach');
        if(coach) coach.scrollIntoView({behavior:'smooth', block:'start'});
      }, 400);
    });
  });
  // 画像体检：数据驱动进化
  var reviewBtn = p.querySelector('#kbReviewBtn');
  if(reviewBtn) reviewBtn.addEventListener('click', async function(){
    var box = p.querySelector('#kbReview');
    if(!box) return;
    box.style.display = '';
    box.innerHTML = '<div class="card p3" style="background:#f8fafc">AI is analyzing profile performance data (about 10-20 seconds)...</div>';
    reviewBtn.disabled = true;
    try{
      var r = await api('/knowledge/profile-review', {method:'POST', body:{}});
      var sugs = (r && r.suggestions) || [];
      await RKB(p);
      var box2 = p.querySelector('#kbReview');
      if(box2){
        box2.style.display = '';
        box2.innerHTML = renderKbReview(sugs);
        box2.scrollIntoView({behavior:'smooth', block:'start'});
      }
    }catch(e){
      box.innerHTML = '<div class="card p3" style="color:#dc2626">Profile health check failed: '+E(e.detail||e.message||String(e))+'</div>';
    }
    reviewBtn.disabled = false;
  });
  p.querySelectorAll('[data-hist]').forEach(function(b){
    b.addEventListener('click', function(){ loadKbHistory(p, b.dataset.hist); });
  });
}

// Highlight search term matches in text
function highlightText(text, term){
  if(!term) return text;
  var escaped = term.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
  var regex = new RegExp('('+escaped+')', 'gi');
  return text.replace(regex, '<mark style="background:#fef08a;color:#334155;padding:0 2px;border-radius:2px">$1</mark>');
}

function getKBCat(cat){
  var colors = {product:'#16a34a',profile:'#2563eb',guidelines:'#ca8a04',case_study:'#7c3aed',forbidden:'#dc2626',system_prompt:'#8b5cf6',voice:'#f97316'};
  return colors[cat] || '#6b7280';
}

// ── Self-evolution helpers ─────────────────────────────────

function renderKbHealth(p, cov, gaps){
  var score = cov.score || 0;
  var levelName = ({excellent:'Excellent',good:'Good',developing:'Developing',empty:'Empty'})[cov.level] || cov.level;
  var levelColor = score>=85?'#16a34a':score>=65?'#ca8a04':score>=40?'#f59e0b':'#dc2626';
  var h = '<div class="card p3 mb3" style="border-top:2px solid #6366f1">';
  h += '<div class="flex jcs aic fw g2 mb2">';
  h += '<div><b class="fs20" style="color:'+levelColor+'">'+score+'/100</b> <span class="badge" style="background:'+levelColor+';color:#fff">'+levelName+'</span>';
  h += '<div class="fs11 c6 mt1">How well AI understands your company. <b style="color:#dc2626">Knowledge Base needs continuous updates</b>：The system auto-checks weekly, logs gaps AI finds, and you can add more anytime.</div></div>';
  h += '<div class="flex g2 fw">';
  h += '<button class="btn btn-sm" style="background:#7c3aed" id="kbWizardBtn">Setup wizard</button>';
  h += '<button class="btn btn-sm" style="background:#0f766e" id="kbCoachBtn">Profile coach</button>';
  h += '<button class="btn btn-sm" style="background:#7c3aed" id="kbTemplateBtn">Industry template</button>';
  h += '<button class="btn btn-sm" style="background:#0891b2" id="kbUploadBtn">Upload materials</button>';
  h += '<button class="btn btn-sm" style="background:#2563eb" id="kbSuggestBtn">AI suggestions</button>';
  h += '<button class="btn btn-sm" style="background:#16a34a" id="kbCaseBtn">Extract from practice</button>';
  h += '<button class="btn btn-sm" style="background:#d97706" id="kbReviewBtn">Profile health</button>';
  h += '</div></div>';
  (cov.categories||[]).forEach(function(c){
    var color = c.score>=65?'#16a34a':c.score>=35?'#f59e0b':'#dc2626';
    h += '<div class="flex aic g2" style="margin-top:6px"><span class="fs11 c6" style="width:88px">'+E(c.name)+'</span>';
    h += '<div style="flex:1;background:#e2e8f0;border-radius:4px;height:8px;overflow:hidden"><div style="width:'+c.score+'%;height:100%;background:'+color+'"></div></div>';
    h += '<span class="fs11" style="width:56px;color:'+color+'">'+c.score+' pts</span></div>';
  });
  h += '<div id="kbWizard" style="display:none" class="mt3"></div>';
  h += '<div id="kbTemplate" style="display:none" class="mt3"></div>';
  h += '<div id="kbUpload" style="display:none" class="mt3"></div>';
  h += '<div id="kbCoach" style="display:none" class="mt3"></div>';
  h += '<div id="kbSuggest" style="display:none" class="mt3"></div>';
  h += '<div id="kbCase" style="display:none" class="mt3"></div>';
  h += '<div id="kbReview" style="display:none" class="mt3"></div>';
  if(gaps && gaps.length){
    h += '<div class="mt3" style="border-top:1px solid #f1f5f9;padding-top:10px">';
    h += '<p class="fwm fs12 mb1" style="color:#dc2626">Gaps to fill: '+gaps.length+' (AI needs these when writing content)</p>';
    gaps.forEach(function(g){
      var isReview = g.source === 'ai_profile_review';
      h += '<div class="flex aic jcs fw g2 mb1" style="background:#fef2f2;border:1px solid #fee2e2;border-radius:6px;padding:8px 10px">';
      h += '<div style="flex:1;min-width:200px"><span class="badge" style="background:#fee2e2;color:#b91c1c">'+E(g.category)+'</span>'+(isReview?' <span class="badge" style="background:#fef3c7;color:#92400e">Data-driven</span>':'')+' <b class="fs12">'+E(g.question)+'</b>';
      if(g.reason) h += '<div class="fs11 c6">'+E(g.reason)+'</div>';
      h += '</div><div class="flex g2">';
      if(isReview){
        h += '<button class="btn btn-sm" style="background:#0f766e" data-gap-coach="'+g.id+'">Revise via profile coach</button>';
      }else{
        h += '<button class="btn btn-sm" style="background:#2563eb" data-gap-fill="'+encodeURIComponent(g.question)+'" data-gap-cat="'+E(g.category)+'">Fill in</button>';
      }
      h += '<button class="btn btn-sm" style="background:#16a34a" data-gap-resolve="'+g.id+'">Done</button>';
      h += '<button class="btn btn-sm btn-b" data-gap-ignore="'+g.id+'">Ignore</button>';
      h += '</div></div>';
    });
    h += '</div>';
  }
  h += '</div>';
  return h;
}

function fillKbEditor(p, title, cat, content, source){
  var t = p.querySelector('#kbTitle'); if(t) t.value = title||'';
  var c = p.querySelector('#kbCat'); if(c){ c.value = cat||''; c.dispatchEvent(new Event('change')); }
  var x = p.querySelector('#kbContent'); if(x) x.value = content||'';
  var s = p.querySelector('#kbSource'); if(s) s.value = source||'manual';
  var saveBtn = p.querySelector('#kbSaveBtn'); if(saveBtn) saveBtn.textContent = 'Save new entry';
  var cancelBtn = p.querySelector('#kbCancelBtn'); if(cancelBtn) cancelBtn.style.display = 'none';
  var editMsg = p.querySelector('#kbEditMsg'); if(editMsg) editMsg.innerHTML = '';
  window.scrollTo(0,0);
}

function renderKbReview(sugs){
  var h = '<div class="card p3" style="border:1px solid #fcd34d;background:#fffbeb">';
  h += '<p class="fwm fs12 mb2" style="color:#92400e">Profile health: AI suggestions from your real outreach data</p>';
  if(!sugs || !sugs.length){
    h += '<div class="fs12 c6">Not enough data yet (each profile needs at least 3 reached customers). Keep developing; suggestions appear automatically.</div>';
  }else{
    sugs.forEach(function(s){
      h += '<div style="background:#fff;border:1px solid #fde68a;border-radius:6px;padding:8px 10px;margin-bottom:6px">';
      h += '<b class="fs12">'+E(s.label||s.profile)+'</b> — '+E(s.title);
      h += '<div class="fs11 c6 mt1">'+E(s.suggestion)+'</div>';
      h += '</div>';
    });
    h += '<div class="fs11 c6 mt1">Logged as a gap. To revise profiles, use the profile coach button in the gap.</div>';
  }
  h += '</div>';
  return h;
}

async function loadKbSuggest(p){
  var box = p.querySelector('#kbSuggest');
  if(!box) return;
  box.style.display = '';
  box.innerHTML = 'AI is analyzing knowledge gaps...';
  try{
    var r = await api('/knowledge/suggest', {method:'POST', body:{}});
    var qs = r.questions || [];
    if(!qs.length){
      box.innerHTML = '<div class="card p3" style="background:#f0fdf4;color:#166534">Knowledge base is solid - no urgent gaps 🎉 Keep updating weekly。</div>';
      return;
    }
    var h = '<div class="card p3"><p class="fwm fs12 mb2">AI suggests filling these questions (“Fill in” fills them directly; “Add gap” sends them to your to-do list)</p>';
    qs.forEach(function(q){
      h += '<div class="flex aic jcs fw g2 mb1" style="background:#f8fafc;border:1px solid #e2e8f0;border-radius:6px;padding:8px 10px">';
      h += '<div style="flex:1;min-width:200px"><span class="badge" style="background:#ede9fe;color:#5b21b6">'+E(q.category)+'</span> <b class="fs12">'+E(q.question)+'</b>';
      if(q.reason) h += '<div class="fs11 c6">'+E(q.reason)+'</div>';
      h += '</div><div class="flex g2">';
      h += '<button class="btn btn-sm" style="background:#2563eb" data-sug-fill="'+encodeURIComponent(q.question)+'" data-sug-cat="'+E(q.category)+'">Fill in</button>';
      h += '<button class="btn btn-sm btn-b" data-sug-add="'+encodeURIComponent(q.question)+'" data-sug-cat="'+E(q.category)+'" data-sug-reason="'+encodeURIComponent(q.reason||'')+'">Add gap</button>';
      h += '</div></div>';
    });
    h += '</div>';
    box.innerHTML = h;
    box.querySelectorAll('[data-sug-fill]').forEach(function(b){
      b.addEventListener('click', function(){
        fillKbEditor(p, decodeURIComponent(b.dataset.sugFill), b.dataset.sugCat, '');
        box.style.display = 'none';
      });
    });
    box.querySelectorAll('[data-sug-add]').forEach(function(b){
      b.addEventListener('click', async function(){
        try{
          await api('/knowledge/gaps', {method:'POST', body:{category:b.dataset.sugCat, question:decodeURIComponent(b.dataset.sugAdd), reason:decodeURIComponent(b.dataset.sugReason||''), source:'ai_detected'}});
          T('Added to gap todo','#16a34a');
          box.innerHTML = '<div class="card p3" style="background:#f0fdf4;color:#166534">Added to todo - refresh to see it at the top.</div>';
        }catch(e){ T('Operation failed','#dc2626'); }
      });
    });
  }catch(e){
    box.innerHTML = '<div class="card p3" style="color:#dc2626">AI suggestion failed: '+E(e.detail||e.message||String(e))+'</div>';
  }
}

async function loadKbCase(p){
  var box = p.querySelector('#kbCase');
  if(!box) return;
  box.style.display = '';
  box.innerHTML = 'AI is extracting lessons from your won/sample/high-reply customers...';
  try{
    var r = await api('/knowledge/from-case');
    var cands = r.candidates || [];
    if(!cands.length){
      box.innerHTML = '<div class="card p3" style="color:#64748b">Not enough won/sample/reply data yet. Once you have more, candidate knowledge will appear here.</div>';
      return;
    }
    var h = '<div class="card p3"><p class="fwm fs12 mb2">Knowledge extracted from practice (confirm before saving)</p>';
    cands.forEach(function(c){
      h += '<div class="mb2" style="background:#f0fdf4;border:1px solid #bbf7d0;border-radius:6px;padding:10px">';
      h += '<span class="badge" style="background:#dcfce7;color:#166534">'+E(c.category)+'</span> <b class="fs13">'+E(c.title)+'</b>';
      h += '<pre class="fs11 c6" style="white-space:pre-wrap;max-height:140px;overflow:auto;margin:6px 0">'+E(c.content)+'</pre>';
      h += '<div class="flex g2"><button class="btn btn-sm" style="background:#2563eb" data-case-edit="'+encodeURIComponent(JSON.stringify(c))+'" data-case-cat="'+E(c.category)+'">Adopt & Edit</button>';
      h += '<button class="btn btn-sm" style="background:#16a34a" data-case-save="'+encodeURIComponent(JSON.stringify(c))+'">Save directly</button></div>';
      h += '</div>';
    });
    h += '</div>';
    box.innerHTML = h;
    box.querySelectorAll('[data-case-edit]').forEach(function(b){
      b.addEventListener('click', function(){
        var c = JSON.parse(decodeURIComponent(b.dataset.caseEdit));
        fillKbEditor(p, c.title, c.category, c.content, 'from_case');
        var tagsEl = p.querySelector('#kbTags');
        if(tagsEl && Array.isArray(c.tags) && c.tags.length) tagsEl.value = c.tags.join(',');
        box.style.display = 'none';
      });
    });
    box.querySelectorAll('[data-case-save]').forEach(function(b){
      b.addEventListener('click', async function(){
        var c = JSON.parse(decodeURIComponent(b.dataset.caseSave));
        try{
          var tags = Array.isArray(c.tags) && c.tags.length ? JSON.stringify(c.tags) : null;
          await api('/knowledge', {method:'POST', body:{category:c.category, title:c.title, content:c.content, tags:tags, source:'from_case', confidence:'medium'}});
          T('Saved (source: practice)','#16a34a');
          RKB(p);
        }catch(e){ T('Save failed','#dc2626'); }
      });
    });
  }catch(e){
    box.innerHTML = '<div class="card p3" style="color:#dc2626">Extraction failed: '+E(e.detail||e.message||String(e))+'</div>';
  }
}

async function loadKbWizard(p){
  var box = p.querySelector('#kbWizard');
  if(!box) return;
  box.innerHTML = 'Loading...';
  try{
    var r = await api('/knowledge/onboarding');
    var steps = r.steps || {};
    var keys = Object.keys(steps);
    var doneCount = keys.filter(function(k){return steps[k].done}).length;
    var current = keys.filter(function(k){return !steps[k].done})[0];
    var h = '<div class="card p3" style="background:#faf5ff;border:1px solid #e9d5ff">';
    h += '<p class="fwm fs13 mb1">Knowledge Base setup wizard ('+doneCount+'/'+keys.length+'）</p>';
    h += '<p class="fs11 c6 mb2">Every company has a different Knowledge Base. Add your real details so AI can work like your own team.<b>This is not one-time; update it weekly.</b></p>';
    keys.forEach(function(k){
      var st = steps[k];
      h += '<span class="badge" style="background:'+(st.done?'#dcfce7;color:#166534':'#e9d5ff;color:#6b21a8')+';margin-right:4px">'+(st.done?'✓ ':'')+E(st.name)+'</span> ';
    });
    if(!current){
      h += '<div class="mt2" style="background:#f0fdf4;color:#166534;padding:10px;border-radius:6px">🎉 Core categories complete! The system auto-checks weekly and reminds you of gaps. Keep it up.</div>';
    }else{
      var meta = steps[current];
      h += '<div class="mt2" style="background:#fff;border:1px solid #e9d5ff;border-radius:8px;padding:12px">';
      h += '<b class="fs13">Current step: '+E(meta.name)+'</b>';
      h += '<textarea id="wizRaw" rows="4" placeholder="Write any raw information you can think of; AI will organize it into knowledge entries.e.g. We make precision machine parts, 1-8cm diameter, two-week lead time, selling mainly to Germany and Turkey..." style="margin-top:8px"></textarea>';
      h += '<div class="mt1"><button class="btn btn-sm" style="background:#7c3aed" id="wizGen">AI organize into entries</button></div>';
      h += '<div class="mt2"><label class="fs11 c6">Title</label><input id="wizTitle" placeholder="Auto-generate or type" style="margin-top:2px"></div>';
      h += '<div class="mt2"><label class="fs11 c6">Content (AI result is editable)</label><textarea id="wizContent" rows="6" style="margin-top:2px"></textarea></div>';
      h += '<div class="flex g2 mt2"><button class="btn btn-sm" style="background:#16a34a" id="wizSave">Save and mark done</button>';
      h += '<button class="btn btn-sm btn-b" id="wizSkip">Later</button></div>';
      h += '</div>';
    }
    h += '</div>';
    box.innerHTML = h;

    var genBtn = box.querySelector('#wizGen');
    if(genBtn) genBtn.addEventListener('click', async function(){
      var raw = box.querySelector('#wizRaw').value.trim();
      if(!raw){ T('Write some raw information first','#dc2626'); return; }
      genBtn.disabled = true; genBtn.textContent = 'AI organizing...';
      try{
        var d = await api('/knowledge/draft', {method:'POST', body:{category:current, raw:raw}});
        box.querySelector('#wizTitle').value = d.title || '';
        box.querySelector('#wizContent').value = d.content || '';
      }catch(e){ T('AI generation failed: '+(e.detail||e.message||String(e)),'#dc2626'); }
      genBtn.disabled = false; genBtn.textContent = 'AI organize into entries';
    });
    var saveBtn = box.querySelector('#wizSave');
    if(saveBtn) saveBtn.addEventListener('click', async function(){
      var title = box.querySelector('#wizTitle').value.trim();
      var content = box.querySelector('#wizContent').value.trim();
      if(!content){ T('Content cannot be empty','#dc2626'); return; }
      try{
        await api('/knowledge', {method:'POST', body:{category:current, title:title||meta.name, content:content, tags:null, source:'manual', confidence:'medium'}});
        await api('/knowledge/onboarding/step', {method:'POST', body:{category:current, done:true}});
        T('Saved - next step','#16a34a');
        loadKbWizard(p);
      }catch(e){ T('Save failed：'+(e.detail||e.message||String(e)),'#dc2626'); }
    });
    var skipBtn = box.querySelector('#wizSkip');
    if(skipBtn) skipBtn.addEventListener('click', function(){ box.style.display = 'none'; });
  }catch(e){
    box.innerHTML = '<div class="card p3" style="color:#dc2626">Wizard load failed: '+E(e.detail||e.message||String(e))+'</div>';
  }
}

async function loadKbHistory(p, id){
  var box = p.querySelector('#kbHist'+id);
  if(!box) return;
  if(box.style.display !== 'none' && box.innerHTML){ box.style.display = 'none'; return; }
  box.style.display = '';
  box.innerHTML = 'Loading version history...';
  try{
    var r = await api('/knowledge/'+id+'/history');
    var hs = r.history || [];
    if(!hs.length){ box.innerHTML = '<div class="card p3" style="color:#64748b">No history yet (versions are created when you save edits)</div>'; return; }
    var h = '<div class="card p3"><p class="fwm fs12 mb2">Version history (current content is backed up before restoring)</p>';
    hs.forEach(function(v){
      h += '<div class="mb2" style="background:#f8fafc;border:1px solid #e2e8f0;border-radius:6px;padding:8px 10px">';
      h += '<div class="flex jcs aic g2"><b class="fs12">'+E(v.title||'(No title)')+'</b><span class="fs11 c6">'+E(v.changed_at||'')+'</span></div>';
      h += '<pre class="fs11 c6" style="white-space:pre-wrap;max-height:110px;overflow:auto;margin:4px 0 0">'+E((v.content||'').substring(0,400))+'</pre>';
      h += '<button class="btn btn-sm" style="background:#475569;margin-top:6px" data-hist-restore="'+v.id+'" data-hist-kid="'+id+'">Restore this version</button>';
      h += '</div>';
    });
    h += '</div>';
    box.innerHTML = h;
    box.querySelectorAll('[data-hist-restore]').forEach(function(b){
      b.addEventListener('click', async function(){
        if(!confirm('Restore this version? Current content is saved to history first and can be rolled back.')) return;
        try{
          await api('/knowledge/'+b.dataset.histKid+'/restore/'+b.dataset.histRestore, {method:'POST', body:{}});
          T('Restored','#16a34a');
          RKB(p);
        }catch(e){ T('Restore failed','#dc2626'); }
      });
    });
  }catch(e){
    box.innerHTML = '<div class="card p3" style="color:#dc2626">History load failed</div>';
  }
}

async function loadKbTemplates(p){
  var box = p.querySelector('#kbTemplate');
  if(!box) return;
  box.innerHTML = 'Loading...';
  try{
    var r = await api('/knowledge/templates');
    var ts = r.templates || [];
    var h = '<div class="card p3" style="background:#faf5ff;border:1px solid #e9d5ff">';
    h += '<p class="fwm fs13 mb1">Industry template</p>';
    h += '<p class="fs11 c6 mb2">Pick an industry and the system generates a Knowledge Base skeleton. Fill the ____ blanks with your real details. Existing content is not overwritten.</p>';
    h += '<div class="flex g2 fw">';
    ts.forEach(function(t){
      h += '<div class="card p2" style="flex:1;min-width:180px;border:1px solid #e9d5ff;border-radius:8px;cursor:pointer" data-tpl="'+E(t.key)+'">';
      h += '<b class="fs13">'+E(t.label)+'</b>';
      h += '<div class="fs11 c6 mt1">'+E(t.desc)+'</div>';
      h += '<button class="btn btn-sm mt2" style="background:#7c3aed;color:#fff">Generate skeleton</button>';
      h += '</div>';
    });
    h += '</div><div class="fs11 c6 mt2">Missing your industry? Start with General and refine later.</div>';
    h += '</div>';
    box.innerHTML = h;
    box.querySelectorAll('[data-tpl]').forEach(function(card){
      card.addEventListener('click', async function(){
        var key = card.dataset.tpl;
        var name = card.querySelector('b').textContent;
        if(!confirm('Use the '+name+' template to generate the Knowledge Base skeleton? Existing content will not be overwritten.')) return;
        var btn = card.querySelector('button'); btn.disabled = true; btn.textContent = 'Generating...';
        try{
          var d = await api('/knowledge/apply-template?industry='+encodeURIComponent(key), {method:'POST'});
          T('Generated '+d.added+'  entry skeleton ('+d.industry+'）','#16a34a',5000);
          RKB(p);
        }catch(e){ T('Generation failed: '+(e.detail||e.message||String(e)),'#dc2626'); btn.disabled = false; btn.textContent = 'Generate skeleton'; }
      });
    });
  }catch(e){
    box.innerHTML = '<div class="card p3" style="color:#dc2626">Template load failed: '+E(e.detail||e.message||String(e))+'</div>';
  }
}

async function loadKbUpload(p){
  var box = p.querySelector('#kbUpload');
  if(!box) return;
  var h = '<div class="card p3" style="background:#ecfeff;border:1px solid #a5f3fc">';
  h += '<p class="fwm fs13 mb1">Upload materials</p>';
  h += '<p class="fs11 c6 mb2">Upload product manuals, price lists or website copy (Word/PDF/Excel/TXT). AI extracts entries for your review before saving.。</p>';
  h += '<div class="flex g2 fw aic">';
  h += '<input type="file" id="kbFile" accept=".docx,.pdf,.xlsx,.txt,.md,.csv">';
  h += '<button class="btn btn-sm" style="background:#0891b2;color:#fff" id="kbFileBtn">Upload and extract with AI</button>';
  h += '</div>';
  h += '<div id="kbFileR" class="mt2"></div>';
  h += '</div>';
  box.innerHTML = h;

  var btn = box.querySelector('#kbFileBtn');
  var inp = box.querySelector('#kbFile');
  if(!btn || !inp) return;
  btn.addEventListener('click', async function(){
    var f = inp.files[0];
    if(!f){ T('Choose a file','#eab308'); return; }
    btn.disabled = true; btn.textContent = 'Parsing + AI extracting (about 30 seconds)...';
    var res = box.querySelector('#kbFileR');
    res.innerHTML = '<div class="fs12 c6">Parsing file and letting AI organize...</div>';
    try{
      var d = await uploadApi('/knowledge/import-file', f);
      var items = d.items || [];
      if(!items.length){ res.innerHTML = '<div class="fs12" style="color:#dc2626">No entries extracted</div>'; return; }
      var hh = '<div class="fs12 fwm mt2 mb1" style="color:#0f172a">AI extracted '+items.length+' entries - review and save:</div>';
      items.forEach(function(it, idx){
        hh += '<div class="card p2 mb2" style="border:1px solid #a5f3fc;background:#fff">';
        hh += '<div class="flex g2 fw aic">';
        hh += '<select data-ik-cat="'+idx+'" style="padding:4px 6px;font-size:11px">';
        ['product','profile','guidelines','forbidden','pricing','voice','case_study'].forEach(function(c){
          hh += '<option value="'+c+'"'+(c===it.category?' selected':'')+'>'+c+'</option>';
        });
        hh += '</select>';
        hh += '<input data-ik-title="'+idx+'" value="'+E(it.title)+'" style="flex:1;padding:5px 8px;font-size:12px">';
        hh += '</div>';
        hh += '<textarea data-ik-content="'+idx+'" rows="4" style="width:100%;margin-top:6px;font-size:12px">'+E(it.content)+'</textarea>';
        hh += '</div>';
      });
      hh += '<button class="btn btn-sm" style="background:#16a34a;color:#fff" id="kbFileSave">Save all to knowledge base</button>';
      res.innerHTML = hh;
      var sv = res.querySelector('#kbFileSave');
      if(sv) sv.addEventListener('click', async function(){
        sv.disabled = true; sv.textContent = 'Saving...';
        var ok = 0, fail = 0;
        for(var i=0;i<items.length;i++){
          var cat = res.querySelector('[data-ik-cat="'+i+'"]').value;
          var title = res.querySelector('[data-ik-title="'+i+'"]').value.trim();
          var content = res.querySelector('[data-ik-content="'+i+'"]').value.trim();
          if(!title || !content) continue;
          try{
            await api('/knowledge', {method:'POST', body:{category:cat, title:title, content:content}});
            ok++;
          }catch(e){ fail++; }
        }
        T('Saved '+ok+' entries'+(fail?'; failed '+fail+' entries':''), fail?'#f59e0b':'#16a34a', 5000);
        RKB(p);
      });
    }catch(e){
      res.innerHTML = '<div class="fs12" style="color:#dc2626">Extraction failed: '+E(e.detail||e.message||String(e))+'</div>';
    }finally{
      btn.disabled = false; btn.textContent = 'Upload and extract with AI';
    }
  });
}

async function loadKbCoach(p){
  var box = p.querySelector('#kbCoach');
  if(!box) return;
  box.innerHTML = 'Loading...';
  try{
    var r = await api('/knowledge/profile-coach');
    var qs = r.questions || [];
    var fw = r.framework || [];
    var h = '<div class="card p3" style="background:#f0fdfa;border:1px solid #99f6e4">';
    h += '<p class="fwm fs13 mb2">Profile coach</p>';
    h += '<p class="fs11 c6 mb2">'+E(r.intro||'')+'</p>';
    if(r.framework_note){
      h += '<p class="fs11 mb2" style="color:#b45309;background:#fffbeb;border:1px solid #fde68a;border-radius:6px;padding:8px 10px">'+E(r.framework_note)+'</p>';
    }
    if(r.roles && r.roles.length){
      h += '<div class="mb2"><span class="fs11 c6">Common buyer roles:</span>';
      r.roles.forEach(function(role){
        h += '<span class="badge" style="background:#ccfbf1;color:#0f766e;margin-right:4px">'+E(role)+'</span>';
      });
      h += '</div>';
    }
    h += '<div class="mb3">';
    fw.forEach(function(f){
      h += '<div style="background:#fff;border:1px solid #ccfbf1;border-radius:6px;padding:8px 10px;margin-bottom:6px">';
      h += '<b class="fs12">'+E(f.tier)+' Tier</b> <span class="fs11">'+E(f.who)+'</span>';
      if(f.example) h += '<div class="fs11" style="color:#0f766e">'+E(f.example)+'</div>';
      h += '</div>';
    });
    h += '</div>';
    qs.forEach(function(q){
      h += '<div class="mb2"><label class="fs11 c6">'+E(q.q)+'</label>';
      h += '<textarea id="pc_'+E(q.key)+'" rows="2" placeholder="'+E(q.hint||'')+'" style="margin-top:2px"></textarea></div>';
    });
    h += '<button class="btn btn-sm" style="background:#0f766e" id="pcGen">Generate profile draft with AI</button> <span id="pcMsg" class="fs11 c6"></span>';
    h += '</div>';
    box.innerHTML = h;
    var gen = box.querySelector('#pcGen');
    if(gen) gen.addEventListener('click', async function(){
      var msg = box.querySelector('#pcMsg');
      var answers = {};
      qs.forEach(function(q){ var el = box.querySelector('#pc_'+q.key); if(el) answers[q.key] = el.value.trim(); });
      msg.innerHTML = 'AI organizing...'; msg.style.color = '#64748b';
      try{
        var d = await api('/knowledge/profile-coach', {method:'POST', body:{answers:answers}});
        fillKbEditor(p, d.title || 'Customer profile & strategy', 'guidelines', d.content || '', 'ai_suggestion');
        var tagsEl = p.querySelector('#kbTags');
        if(tagsEl && Array.isArray(d.tags) && d.tags.length) tagsEl.value = d.tags.join(',');
        msg.innerHTML = 'Draft ready - click "Save new entry"'; msg.style.color = '#16a34a';
      }catch(e){
        msg.innerHTML = E(e.detail||e.message||String(e)); msg.style.color = '#dc2626';
      }
    });
  }catch(e){
    box.innerHTML = '<div class="card p3" style="color:#dc2626">Profile coach load failed: '+E(e.detail||e.message||String(e))+'</div>';
  }
}
