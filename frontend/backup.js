// ── Backup & Recovery Page ──

async function RBackup() {

  var s = '';

  var status = null;

  try {

    status = await api('/backup/status');

  } catch(e) { status = null; }



  s += '<h2 class="fs20 fwb mb4">Backup & Restore</h2>';


  if (!status) {

    s += '<div class="card p4 mb4" style="background:#fef5f5;border-left:4px solid #dc2626">';

    s += '<strong class="fs13 cr">Cannot reach the backend</strong>';

    s += '<p class="fs12 c6 mt2">Make sure the service is running (port from PORT in .env; default 8010)：<code style="background:#f8fafc;padding:2px 6px;border-radius:3px">python main.py</code></p>';
    s += '</div>';

    // Still show the recovery guide even when offline

    s += _recoveryGuide();

    document.getElementById('mainPane').innerHTML = s;

    return;

  }
    // ── 安全Status卡 ──
    s += '<div class="card p4 mb4" style="border-top:2px solid #059669">';
    s += '<h3 class="fs14 fwb mb3">🔐 Backup security status</h3>';
    s += '<div class="grid gcol2" style="gap:14px">';
    s += '<div><span class="fs12 c6">Encrypted backups</span><div class="fs14 fwm mt1" style="color:'+(status.encryption&&status.encryption.enabled?'#16a34a':'#f59e0b')+'">'+(status.encryption&&status.encryption.enabled?'Enabled (AES-256)':'Disabled')+'</div>';
    if(status.encryption && status.encryption.method) s += '<div class="fs11 c6 mt1">'+E(status.encryption.method)+'</div>';
    s += '</div>';
    s += '<div><span class="fs12 c6">Auto backup</span><div class="fs14 fwm mt1" style="color:#16a34a">✓ Every 4 hours + on startup</div>';
    s += '<div class="fs11 c6 mt1">Every backup is integrity-checked; bad backups are not counted</div></div>';
    s += '</div>';
    if(status.recent_backups && status.recent_backups.length){
      s += '<div class="fs12 c6 mt3 mb1">Latest backup check:</div>';
      status.recent_backups.forEach(function(r){
        var good = r.integrity === 'ok' || r.integrity === 'encrypted';
        var label = r.integrity === 'ok' ? '✓ OK' : (r.integrity === 'encrypted' ? '🔒 Encrypted' : '✗ '+E(r.integrity));
        s += '<div class="flex aic g2 fw" style="font-size:11px;margin-bottom:4px">';
        s += '<span class="badge" style="background:'+(good?'#dcfce7;color:#166534':'#fee2e2;color:#b91c1c')+'">'+label+'</span>';
        s += '<span style="color:#64748b">'+E(r.filename)+'</span>';
        s += '<span style="color:#94a3b8">'+(r.source==='cloud'?'Cloud':'Local')+' · '+E(r.created.replace('T',' ').substring(0,16))+'</span>';
        s += '</div>';
      });
    }
    s += '</div>';

    // Database info
    s += '<div class="card p4 mb4">';
    s += '<h3 class="fs14 fwb mb3">Database</h3>';

    s += '<div class="grid gcol2" style="gap:14px">';

    s += '<div><span class="fs12 c6">Size</span><div class="fs14 fwm mt1">' + status.database.size_mb + ' MB</div></div>';

    s += '<div><span class="fs12 c6">Status</span><div class="fs14 fwm mt1" style="color:#16a34a">' + (status.database.exists ? 'OK' : 'Error') + '</div></div>';

    s += '</div></div>';



    // Cloud backup status

    if (status.cloud_backups && status.cloud_backups.enabled) {
      s += '<div class="card p4 mb4" style="border-left:4px solid #16a34a">';
      s += '<h3 class="fs14 fwb mb3">☁️ Cloud auto-sync — enabled</h3>';
      s += '<p class="fs12 c6 mb3">Each backup syncs a copy to:<code style="background:#f8fafc;padding:2px 6px;border-radius:3px">' + E(status.cloud_backups.directory) + '</code></p>';
      s += '<p class="fs11 c6">The folder is configured on this computer (OneDrive / Dropbox / Google Drive / any synced folder). To change it, edit Cloud backup folder under System Settings > Sending rhythm & security, then restart.</p>';
      s += '<div class="grid gcol2" style="gap:14px">';

      s += '<div><span class="fs12 c6">Cloud backup count</span><div class="fs14 fwm mt1">' + status.cloud_backups.count + '</div></div>';

      if (status.cloud_backups.latest) {

        s += '<div><span class="fs12 c6">Latest cloud backup</span><div class="fs13 fwm mt1">' + status.cloud_backups.latest.created.replace('T',' ').substring(0,16) + '</div></div>';

      }

      s += '</div></div>';

    }



    // Local backups

    s += '<div class="card p4 mb4">';

    s += '<h3 class="fs14 fwb mb3">Local backups</h3>';

    s += '<div class="grid gcol2" style="gap:14px">';

    s += '<div><span class="fs12 c6">Local backup count</span><div class="fs14 fwm mt1">' + status.local_backups.count + '</div></div>';

    s += '<div><span class="fs12 c6">Total size</span><div class="fs14 fwm mt1">' + status.local_backups.total_size_mb + ' MB</div></div>';

    if (status.local_backups.latest) {

      s += '<div><span class="fs12 c6">Latest local backup</span><div class="fs13 fwm mt1">' + status.local_backups.latest.filename + '</div></div>';

      s += '<div><span class="fs12 c6">Time</span><div class="fs13 fwm mt1">' + status.local_backups.latest.created.replace('T',' ').substring(0,19) + '</div></div>';

    }

    if (status.retention) {

      s += '<div><span class="fs12 c6">Retention policy</span><div class="fs13 fwm mt1">Keep latest ' + status.retention.keep_latest_per_location + '; clean up backups older than ' + status.retention.keep_days + ' days</div></div>';

    }

    s += '</div></div>';



  // Action buttons

  s += '<div class="card p4 mb4">';

  s += '<h3 class="fs14 fwb mb3">Manual actions</h3>';

  s += '<div style="display:flex;gap:10px;flex-wrap:wrap;margin-bottom:6px">';

  s += '<button class="btn" style="background:#2563eb" onclick="doBackup()">Backup now (local + cloud)</button>';

  s += '<a class="btn btn-b" style="text-decoration:none" href="/api/backup/db" download>Download database file (.db)</a>';

  s += '<button class="btn" style="background:#16a34a" onclick="doExport()">Export full JSON</button>';

  s += '</div>';

  s += '<p class="fs12 c6" style="line-height:1.6;margin-top:8px">Cloud sync only runs when you set a cloud folder in System Settings (OneDrive / Dropbox / Google Drive / any synced folder). <b>If left blank it stays disabled</b>. Each computer keeps its own backups; nothing gets mixed. <b>Both local and cloud backups use AES-256 encryption</b>, so even if files leak, customer data cannot be read.</p>';
  s += '</div>';



  // Import section

  s += '<div class="card p4 mb4">';

  s += '<h3 class="fs14 fwb mb3">Restore from backup</h3>';

  s += '<p class="fs12 c6 mb3">Choose an exported JSON file to restore. Existing records with the same ID are updated; new ones are inserted.<strong>Existing data is never deleted。</strong></p>';

  s += '<div style="display:flex;gap:10px;align-items:center">';

  s += '<input type="file" id="importFile" accept=".json" style="max-width:300px">';

  s += '<button class="btn" style="background:#9333ea" onclick="doImport()">Import & restore</button>';

  s += '</div>';

  s += '<div id="importResult" class="mt3" style="display:none"></div>';

  s += '</div>';



  // One-click restore section

  s += '<div class="card p4 mb4" style="border-left:4px solid #dc2626">';

  s += '<h3 class="fs14 fwb mb3" style="color:#dc2626">One-click database restore</h3>';
  s += '<p class="fs12 c6 mb3">Automatically scan all backups (local + cloud, including encrypted) find the backup with the most customer records and restore it in one click.<strong>Backup files are never deleted.</strong>The current database is saved as .before_restore first.</p>';
  s += '<div style="display:flex;gap:10px;align-items:center">';

  s += '<button class="btn" style="background:#dc2626" id="restoreBtn" onclick="doRestoreBest()">Restore from best backup</button>';

  s += '<button class="btn btn-b" id="restoreCandidatesBtn" onclick="showRestoreCandidates()">View backup candidates</button>';

  s += '<span id="restoreStatus" style="font-size:12px;color:#64748b"></span>';

  s += '</div>';

  s += '<div id="restoreCandidates" class="mt3" style="display:none"></div>';
  s += '</div>';
  s += '</div>';

  // ── 备份记录（主账号看全部 / Member data export）──
  s += '<div class="card p4 mb4">';
  s += '<div class="flex aic jcs fw g2 mb3" style="background:#f0fdf4;border:1px solid #bbf7d0;border-radius:6px;padding:12px">';
  s += '<div><b class="fs13">My customer data</b><div class="fs11 c6 mt1">Export all customers assigned to me (interactions, sequences, deals, samples) anytime; easy to keep, move or hand over.</div></div>';
  s += '<button class="btn btn-sm" style="background:#16a34a" id="bkExportMine">Export my data</button>';
  s += '</div>';
  s += '<h3 class="fs14 fwb mb3">🗂️ Backup records</h3>';
  if(currentUser && currentUser.role !== 'member'){
    s += '<div class="flex aic g2 mb3" style="background:#f8fafc;padding:10px;border-radius:6px">';
    s += '<b class="fs12">Export member data:</b><select id="bkUserSel" style="max-width:220px"><option value="">Select member...</option>';
    Object.keys(usersMap).forEach(function(id){
      if(String(id) !== String(currentUser.id)) s += '<option value="'+id+'">'+E(usersMap[id])+'</option>';
    });
    s += '</select><button class="btn btn-sm" style="background:#0891b2" id="bkUserExport">Export member customers</button>';
    s += '<span class="fs11 c6">(includes interactions/sequences/deals/samples; for handover & compliance)</span>';
    s += '</div>';
  }
  s += '<div id="bkRecords"><div class="fs12 c6">Loading...</div></div>';
  s += '<div class="mt3" style="border-top:1px solid #e2e8f0;padding-top:10px">';
  s += '<b class="fs12">Restore member data:</b><input type="file" id="bkRestoreFile" accept=".json" style="font-size:11px;max-width:240px"> ';
  if(currentUser && currentUser.role !== 'member'){
    s += '<select id="bkRestoreSel" style="max-width:180px"><option value="">Restore to (default self)...</option>';
    Object.keys(usersMap).forEach(function(id){
      if(String(id) !== String(currentUser.id)) s += '<option value="'+id+'">'+E(usersMap[id])+'</option>';
    });
    s += '</select> ';
  }
  s += '<button class="btn btn-sm" style="background:#b45309" id="bkRestoreBtn">Upload & restore</button>';
  s += '<span class="fs11 c6">(merge by ID: existing customers updated, new ones added, assigned to the target member)</span>';
  s += '<div id="bkRestoreMsg" class="fs12 mt2" style="color:#dc2626"></div>';
  s += '</div>';
  s += '</div>';

  // Recovery guide
  s += _recoveryGuide();

  document.getElementById('mainPane').innerHTML = s;
  if(document.getElementById('bkUserExport')){
    document.getElementById('bkUserExport').addEventListener('click', _doUserExport);
  }
  if(document.getElementById('bkExportMine')){
    document.getElementById('bkExportMine').addEventListener('click', async function(){
      try{
        await downloadApi('/backup/user-export');
        T('Downloading your customer data...','#16a34a');
      }catch(e){ T(E(e.message||String(e)),'#dc2626'); }
    });
  }
  if(document.getElementById('bkRestoreBtn')){
    document.getElementById('bkRestoreBtn').addEventListener('click', _doUserRestore);
  }
  _loadBackupRecords();
}

async function _loadBackupRecords(){
  var box = document.getElementById('bkRecords');
  if(!box) return;
  try{
    var r = await api('/backup/records');
    var rows = r.records || [];
    if(!rows.length){ box.innerHTML = '<div class="fs12 c6">No backup records (click "Backup now" and records are created automatically)</div>'; return; }
    var h = '<table style="width:100%;font-size:12px"><tr style="text-align:left;color:#64748b"><th style="padding:4px">Time</th><th style="padding:4px">Type</th><th style="padding:4px">Size</th><th style="padding:4px">Status</th></tr>';
    rows.forEach(function(x){
      var kindTxt = x.kind === 'db_full' ? 'Full database' : 'Member data export';
      var who = x.user_id ? (usersMap[x.user_id] || ('Member #'+x.user_id)) : 'System auto';
      var label = x.kind === 'user_export' ? kindTxt + '（' + who + '）' : kindTxt;
      h += '<tr><td style="padding:4px">'+E((x.created_at||'').replace('T',' ').substring(0,16))+'</td>';
      h += '<td style="padding:4px">'+label+'</td>';
      h += '<td style="padding:4px">'+(x.size_mb||0)+' MB</td>';
      h += '<td style="padding:4px;color:'+(x.integrity==='ok'?'#16a34a':'#dc2626')+'">'+(x.integrity==='ok'?'OK':'Error')+'</td></tr>';
    });
    h += '</table>';
    box.innerHTML = h;
  }catch(e){
    box.innerHTML = '<div class="fs12" style="color:#dc2626">Load failed: '+E(e.detail||e.message||String(e))+'</div>';
  }
}

async function _doUserExport(){
  var sel = document.getElementById('bkUserSel');
  if(!sel || !sel.value){ T('Select a member first','#dc2626'); return; }
  try{
    await downloadApi('/backup/user-export?user_id='+sel.value);
    T("Downloading this member's data...",'#0891b2');
  }catch(e){ T(E(e.message||String(e)),'#dc2626'); }
}

async function _doUserRestore(){
  var fileEl = document.getElementById('bkRestoreFile');
  var msg = document.getElementById('bkRestoreMsg');
  if(!fileEl || !fileEl.files || !fileEl.files[0]){ if(msg){msg.innerHTML='Select an exported JSON file first';} return; }
  var extra = {};
  var sel = document.getElementById('bkRestoreSel');
  if(sel && sel.value) extra.target_user_id = sel.value;
  if(msg){ msg.innerHTML = 'Restoring...'; msg.style.color = '#64748b'; }
  try{
    var r = await uploadApi('/backup/user-restore', fileEl.files[0], extra);
    if(msg){ msg.innerHTML = '✓ Restore done: added '+r.prospects.inserted+' customers, updated '+r.prospects.updated+''; msg.style.color = '#16a34a'; }
    _loadBackupRecords();
  }catch(e){
    if(msg){ msg.innerHTML = E(e.detail||e.message||String(e)); msg.style.color = '#dc2626'; }
  }
}


function _recoveryGuide() {

  var s = '';

  s += '<div class="card p4">';

  s += '<h3 class="fs14 fwb mb3">Move to a new computer / recovery guide</h3>';

  s += '<ol class="fs12 c6" style="padding-left:20px;line-height:1.8;margin-top:8px">';

  s += '<li>Set the same cloud folder on the new computer (OneDrive / Dropbox / Google Drive / any synced folder) and let the backups sync over automatically</li>';

 s += '<li>Pull the project code</li>';
  s += '<li>Configure the .env file (API keys, SMTP, etc.)</li>';

  s += '<li>Copy the latest .db file from the cloud to the project root and rename it to <code>prospect.db</code></li>';

  s += '<li>Start the service — all customers, interactions and knowledge base are restored</li>';

  s += '</ol>';

  s += '</div>';

  return s;

}



async function doBackup() {

  T('Backing up (local + cloud)...', 'info', 1500);

  try {

    var r = await api('/backup/run', {method:'POST'});

    var msg = 'Backup success: ' + r.filename;

    if (r.local && r.local.size_mb) msg += ' | Local ' + r.local.size_mb + 'MB';

    if (r.cloud && r.cloud.status === 'ok') msg += ' | ☁️ Cloud synced';

    else if (r.cloud && r.cloud.error) msg += ' | Cloud failed';

    T(msg, 'success', 3000);

    setTimeout(function(){ RBackup(); }, 600);

  } catch(e) {

    T('Backup failed: ' + e.message, 'error');

  }

}



async function doExport() {

  T('Exporting...', 'info', 2000);

  try {

    var r = await authFetch('/api/backup/export', { method: 'POST' });
    if (!r.ok) { T('Export failed: HTTP ' + r.status, 'error'); return; }

    var blob = await r.blob();

    var url = URL.createObjectURL(blob);

    var a = document.createElement('a');

    a.href = url; a.download = 'tuodan_export.json';
    document.body.appendChild(a); a.click(); document.body.removeChild(a);

    URL.revokeObjectURL(url);

    T('JSON export download started', 'success');

  } catch(e) { T('Export failed: ' + e.message, 'error'); }

}



async function doImport() {

  var file = document.getElementById('importFile').files[0];

  if (!file) { T('Select a file first', 'error'); return; }

  T('Importing...', 'info', 2000);

  try {

    var form = new FormData();

    form.append('file', file);

    var resp = await authFetch('/api/backup/import', { method: 'POST', body: form });
    var r = await resp.json();

    if (r.error) { T('Import failed: ' + r.error, 'error'); return; }



    var div = document.getElementById('importResult');

    var h = '<div class="card p3" style="background:#f0fdf6;border-color:#bbf7d0"><strong class="fs13">Import complete</strong><ul class="fs12 mt2" style="padding-left:16px">';

    for (var k in r.imported) {

      var v = r.imported[k];

      h += '<li>' + k + ': updated ' + v.updated + ' added, ' + v.inserted + '</li>';

    }

    h += '</ul></div>';

    div.innerHTML = h;

    div.style.display = 'block';

    if (r.errors && r.errors.length) {

      div.innerHTML += '<div class="mt2 fs12 cr">Errors: ' + r.errors.join(', ') + '</div>';

    }

    T('Import succeeded', 'success');

    setTimeout(function(){ RBackup(); }, 1000);

  } catch(e) {

    T('Import failed: ' + e.message, 'error');

  }

}



async function doRestoreBest() {

  var btn = document.getElementById('restoreBtn');

  var status = document.getElementById('restoreStatus');

  btn.disabled = true;

  btn.textContent = 'Scanning backups...';

  status.textContent = 'Scanning all backup files...';

  T('Scanning backups...', '#eab308', 3000);

  try {

    var r = await api('/backup/restore-best', { method: 'POST' });

    if (!r.success) {

      T(r.error || 'Restore not executed', '#f59e0b', 4000);

      status.textContent = r.error || 'Nothing to restore';

      btn.disabled = false;

      btn.textContent = 'Restore from best backup';

      return;

    }

    status.textContent = 'Restored ' + r.restored_count + ' records (was ' + r.previous_count + ' → ' + r.restored_count + ')';

    T('Restore success! Restored ' + r.restored_from + ' records from ' + r.restored_count + ' records', 'success', 5000);

    btn.disabled = false;

    btn.textContent = 'Restore from best backup';

    setTimeout(function(){ RBackup(); }, 1500);

  } catch(e) {

    T('Restore failed: ' + (e.detail || e.message || String(e)), 'error');

    status.textContent = 'Restore failed';

    btn.disabled = false;

    btn.textContent = 'Retry';

  }

}



async function showRestoreCandidates() {

  var box = document.getElementById('restoreCandidates');

  if (!box) return;

  box.style.display = 'block';

  box.innerHTML = '<div class="fs12 c6">Scanning backups...</div>';

  try {

    var r = await api('/backup/candidates');

    var list = r.candidates || [];

    if (!list.length) {

      box.innerHTML = '<div class="fs12 cr">No usable backups found</div>';

      return;

    }

    var h = '<table><thead><tr><th>File</th><th>Source</th><th>Time</th><th>Customers</th><th>Interactions</th><th>Status</th><th>Size</th></tr></thead><tbody>';

    list.slice(0, 10).forEach(function(x) {

      h += '<tr>';

      h += '<td class="fs12">' + E(x.filename || '') + '</td>';

      h += '<td class="fs12">' + E(x.source || '') + '</td>';

      h += '<td class="fs12">' + E((x.created || '').replace('T',' ').substring(0,19)) + '</td>';

      h += '<td class="fs12">' + ((x.counts && x.counts.prospects) || 0) + '</td>';

      h += '<td class="fs12">' + ((x.counts && x.counts.interactions) || 0) + '</td>';

      h += '<td class="fs12" style="color:' + (x.integrity === 'ok' ? '#16a34a' : '#dc2626') + '">' + E(x.integrity || '') + '</td>';

      h += '<td class="fs12">' + (x.size_mb || 0) + ' MB</td>';

      h += '</tr>';

    });

    h += '</tbody></table>';

    box.innerHTML = h;

  } catch(e) {

    box.innerHTML = '<div class="fs12 cr">Scan failed: ' + E(e.detail || e.message || String(e)) + '</div>';

  }

}
