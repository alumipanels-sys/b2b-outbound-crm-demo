async function ROps(p){
  p.innerHTML = '<div class="card p4 tc c6">Loading AI automation...</div>';
  var intel;
  try {
    intel = await api('/ops/intelligence/status');
  } catch(e) {
    p.innerHTML = '<div class="card p4 tc cr">Failed to load AI automation: '+E(e.detail||e.message||String(e))+'</div>';
    return;
  }

  var io = intel.overview || {};
  var h = '<div class="page-hd" style="align-items:center">';
  h += '<div><h2>Auto Research</h2><p class="page-sub">The system researches customer intelligence automatically. Below shows progress; you can also trigger a manual run.</p></div>';
  h += '<button class="btn btn-sm btn-b" id="opsRefresh">Refresh data</button>';
  h += '</div>';

  // Core coverage stats
  h += '<div style="display:flex;gap:10px;margin-bottom:18px;flex-wrap:wrap">';
  h += opsMetric('Website coverage', (io.website_coverage_rate||0)+'%', (io.with_website||0)+' / '+(io.active_prospects||0)+' customers have a website', '#2563eb');
  h += opsMetric('Key points researched', (io.key_point_rate||0)+'%', (io.with_key_points||0)+' customers analyzed', '#16a34a');
  h += opsMetric('Icebreakers available', (io.icebreaker_rate||0)+'%', (io.with_icebreakers||0)+' customers with angles', '#7c3aed');
  h += '</div>';

  // Auto research (manual catch-up)
  h += '<div class="card" style="margin-bottom:18px;overflow:hidden">';
  h += '<div style="padding:12px 16px;background:#f7f9fc;border-bottom:1px solid #e4e9f2;display:flex;align-items:center;gap:8px">';
  h += '<span class="dot" style="width:8px;height:8px;border-radius:50%;background:#2563eb"></span>';
  h += '<span class="fs14 fwb" style="color:#0f172a">Auto-research customers</span>';
  h += '<span class="fs11 c6">'+(io.due_refresh||0)+' due · '+(io.never_scraped||0)+' never researched</span>';
  h += '<span style="flex:1"></span>';
  h += '<button class="btn btn-sm" style="background:#16a34a" id="runIntelDue">Research 3 now</button>';
  h += '</div>';
  h += '<div style="padding:14px 16px">';
  h += '<div class="fs11 c6 mb2">Manual runs process 3 at a time, about 1-2 minutes; the rest auto-run overnight.</div>';
  h += opsDueTable(intel.due || []);
  h += '</div></div>';

  // One-line summary
  h += '<div class="card p3"><p class="fs12 c6" style="line-height:1.7">Customer research, reply analysis and profile health checks all run automatically — no action needed.</p></div>';

  p.innerHTML = h;

  bindSafe(p, '#opsRefresh', 'click', function(){ ROps(p); });
  bindSafe(p, '#runIntelDue', 'click', async function(){
    var btn = p.querySelector('#runIntelDue');
    btn.disabled = true;
    btn.textContent = 'Running intelligence...';
    try {
      var r = await api('/ops/intelligence/refresh-due?limit=3', {method:'POST', timeout:600000});
      var ok = (r.results||[]).filter(function(x){return x.status==='ok'}).length;
      var fail = (r.results||[]).filter(function(x){return x.status!=='ok'}).length;
      T('Intelligence done: '+ok+' ok, '+fail+' failed', fail ? '#f97316' : '#16a34a', 6000);
      ROps(p);
    } catch(e) {
      if(e && (e.name==='AbortError'||/aborted/i.test(String(e.message||'')))){
        T('Processing is taking longer; the page stopped waiting — the backend may still be working. Click "Refresh data" later.', '#f97316', 7000);
      } else {
        T('Intelligence automation failed: '+(e.detail||e.message||''), '#dc2626', 6000);
      }
      btn.disabled = false;
      btn.textContent = 'Research 3 now';
    }
  });

  p.querySelectorAll('[data-refresh-intel]').forEach(function(b){
    b.addEventListener('click', async function(){
      b.disabled = true;
      b.textContent = 'Processing';
      try {
        var r = await api('/ops/intelligence/refresh/'+b.dataset.refreshIntel, {method:'POST', timeout:180000});
        if(r.status === 'ok'){
          T((r.company||'Customer')+' intelligence refreshed: '+(r.steps||[]).join(' / '), '#16a34a', 6000);
        }else{
          T((r.company||'Customer')+' no intelligence captured: '+(r.reason||r.website_error||'no valid data'), '#f97316', 8000);
        }
        ROps(p);
      } catch(e) {
        if(e && (e.name==='AbortError'||/aborted/i.test(String(e.message||'')))){
          T('Processing is taking longer; click "Refresh data" later.', '#f97316', 6000);
        } else {
          T('Single-customer intelligence refresh failed', '#dc2626');
        }
        b.disabled = false;
        b.textContent = 'Research';
      }
    });
  });

  p.querySelectorAll('[data-close-reply]').forEach(function(b){
    b.addEventListener('click', async function(){
      b.disabled = true;
      b.textContent = 'Analyzing';
      try {
        var r = await api('/ops/replies/close/'+b.dataset.closeReply, {method:'POST'});
        T('Reply analyzed: '+(r.intent||'done'), '#16a34a', 4000);
        ROps(p);
      } catch(e) {
        T('Reply analysis failed', '#dc2626');
        b.disabled = false;
        b.textContent = 'Analyze';
      }
    });
  });
}

function opsMetric(label, value, sub, color){
  return '<div class="stat-card" style="--stat-color:'+color+'"><div class="stat-label">'+E(label)+'</div><div class="stat-value-wrapper"><span class="stat-value">'+E(value)+'</span></div><div class="fs11" style="color:#64748b;margin-top:2px">'+E(sub||'')+'</div></div>';
}

function opsDueTable(rows){
  if(!rows.length) return '<div class="tc c6" style="padding:24px">✓ No customers waiting — all researched</div>';
  var h = '<table><thead><tr><th>Customer</th><th>Profile</th><th>Existing intel</th><th>Action</th></tr></thead><tbody>';
  rows.slice(0,20).forEach(function(r){
    var sig = [];
    if(r.website_key_points) sig.push('Website');
    if(r.icebreak_angles) sig.push('Icebreaker');
    if(r.hiring_signals) sig.push('Hiring');
    if(r.osint_report) sig.push('Background');
    h += '<tr><td><span class="fwm">'+E(r.company)+'</span><div class="fs11 c6">'+E(r.country||'')+'</div></td><td>'+E(r.profile_type||'-')+'</td><td>'+(sig.length?sig.join(' / '):'<span class="cr">None</span>')+'</td><td><button class="btn btn-sm" style="background:#2563eb" data-refresh-intel="'+r.prospect_id+'">Research</button></td></tr>';
  });
  return h + '</tbody></table>';
}

function opsReplyTable(rows){
  if(!rows.length) return '<div class="tc c6 p4">All customer replies have been analyzed.</div>';
  var h = '<table><thead><tr><th>From</th><th>Subject</th><th>Preview</th><th>Action</th></tr></thead><tbody>';
  rows.slice(0,20).forEach(function(r){
    h += '<tr><td>'+E(r.from||('#'+r.prospect_id))+'</td><td>'+E(r.subject||'-')+'</td><td class="fs11 c6">'+E((r.preview||'').substring(0,80))+'</td><td><button class="btn btn-sm" style="background:#f97316" data-close-reply="'+r.id+'">Analyze</button></td></tr>';
  });
  return h + '</tbody></table>';
}
