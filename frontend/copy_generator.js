// Copy Generator tab
// User selects 1-3 success cases → AI writes copy based on cases + current customer profile

var _cgSelectedCases = [];
var _cgResult = null;
var _cgChannel = 'email';
var _cgLoading = false;

async function DTCopyGen(b) {
  if (!dp || !dp.id) { b.innerHTML = '<p style="color:#dc2626">Open a customer first</p>'; return; }

  var matches = Array.isArray(drCaseMatches) ? drCaseMatches : [];

  var h = '';
  h += '<div class="flex jcs aic mb3">';
  h += '<div><span class="fs14 fwb">Copy Generator</span><span class="fs11 c6" style="margin-left:8px">Select cases → AI writes copy based on real plays</span></div>';
  h += '<div class="flex aic g2">';
  h += renderModelSelector('model_copygen', '');
  h += '<select id="cgChannel" style="width:120px;font-size:12px">';
  h += '<option value="email"' + (_cgChannel === 'email' ? ' selected' : '') + '>Email</option>';
  h += '<option value="linkedin"' + (_cgChannel === 'linkedin' ? ' selected' : '') + '>LinkedIn</option>';
  h += '<option value="whatsapp"' + (_cgChannel === 'whatsapp' ? ' selected' : '') + '>WhatsApp</option>';
  h += '</select>';
  h += '<button class="btn btn-pri" id="cgGenerateBtn"' + (_cgSelectedCases.length === 0 ? ' disabled style="opacity:0.5"' : '') + '>Generate copy</button>';
  h += '</div></div>';

  h += '<div style="display:grid;grid-template-columns:1fr 1.2fr;gap:14px">';

  // LEFT: Case selector
  h += '<div>';
  h += '<div class="card p3 mb2" style="background:#f8fafc"><span class="fs12 fwb">Candidate cases</span><span class="fs11 c6" style="margin-left:6px">(' + matches.length + ')</span></div>';
  if (!matches.length) {
    h += '<div class="card p4 tc c6">No matching cases for this customer.<br>Add win cases in the Case dashboard first.</div>';
  } else {
    matches.forEach(function (c) {
      var checked = _cgSelectedCases.indexOf(c.id) >= 0;
      var scoreColor = c.match_score >= 70 ? '#16a34a' : c.match_score >= 40 ? '#ca8a04' : '#6b7280';
      var detailId = 'cgDetail_' + c.id;

      h += '<div class="card p3 mb2" style="border-left:3px solid ' + (checked ? '#6366f1' : '#e2e8f0') + ';cursor:pointer;transition:border-color .15s" data-cg-case="' + c.id + '">';
      h += '<div class="flex aic g2 mb1">';
      h += '<input type="checkbox" data-cg-cbox="' + c.id + '"' + (checked ? ' checked' : '') + ' style="width:16px;height:16px;cursor:pointer;flex-shrink:0">';
      h += '<strong class="fs13" style="flex:1">' + E(c.title || 'Untitled') + '</strong>';
      h += '<span class="badge" style="background:' + scoreColor + ';color:#fff;font-size:10px">' + E(c.match_score) + '%</span>';
      h += '</div>';
      h += '<div class="flex fw g2 mb1" style="margin-left:24px">';
      if (c.profile) h += '<span class="badge" style="background:#e0e7ff;color:#3730a3;font-size:10px">Profile ' + E(c.profile) + '</span>';
      (c.channels || []).forEach(function (ch) { h += '<span class="badge" style="background:#f1f5f9;color:#475569;font-size:10px">' + E(ch) + '</span>'; });
      (c.outcomes || []).forEach(function (out) { h += '<span class="badge" style="background:#dcfce7;color:#166534;font-size:10px">' + E(out) + '</span>'; });
      h += '</div>';
      if (c.match_reasons && c.match_reasons.length) {
        h += '<div class="fs11 c6" style="margin-left:24px">' + E(c.match_reasons.join(' · ')) + '</div>';
      }
      var play = c.playbook || [];
      if (play.length) {
        h += '<div class="fs11 mt1" style="margin-left:24px;color:#475569;line-height:1.5">' + E(play[0].substring(0, 120)) + '</div>';
      }
      h += '<div class="fs11 mt1" style="margin-left:24px;color:#6366f1;cursor:pointer" data-cg-expand="' + c.id + '">Expand details ▼</div>';
      h += '<div id="' + detailId + '" style="display:none;margin-left:24px;margin-top:8px;padding:10px;background:#f8fafc;border-radius:4px;max-height:300px;overflow-y:auto;font-size:11px;line-height:1.6;white-space:pre-wrap;color:#334155">' + E((c.preview || '').substring(0, 800)) + '</div>';
      h += '</div>';
    });
  }
  h += '</div>';

  // RIGHT: Generated draft
  h += '<div>';
  h += '<div class="card p3 mb2" style="background:#f8fafc"><span class="fs12 fwb">Generated copy</span></div>';
  if (_cgLoading) {
    h += '<div class="card p4 tc" style="color:#6366f1;padding:32px">Generating copy...</div>';
  } else if (_cgResult) {
    h += renderCopyResult(_cgResult);
  } else {
    h += '<div class="card p4 tc c6" style="padding:32px">Select cases on the left and click "Generate copy"<br><br><span class="fs11">AI writes a draft for this customer based on your selected win cases</span></div>';
  }
  h += '</div>';

  h += '</div>';

  b.innerHTML = h;

  var chSel = b.querySelector('#cgChannel');
  if (chSel) chSel.addEventListener('change', function () { _cgChannel = this.value; });

  b.querySelectorAll('[data-cg-cbox]').forEach(function (cb) {
    cb.addEventListener('click', function (e) { e.stopPropagation(); });
    cb.addEventListener('change', function () {
      var cid = parseInt(this.dataset.cgCbox);
      if (this.checked) {
        if (_cgSelectedCases.indexOf(cid) < 0) _cgSelectedCases.push(cid);
      } else {
        _cgSelectedCases = _cgSelectedCases.filter(function (x) { return x !== cid; });
      }
      DTCopyGen(b);
    });
  });

  b.querySelectorAll('[data-cg-expand]').forEach(function (el) {
    el.addEventListener('click', function (e) {
      e.stopPropagation();
      var cid = this.dataset.cgExpand;
      var detail = document.getElementById('cgDetail_' + cid);
      if (detail) {
        if (detail.style.display === 'none') {
          detail.style.display = 'block';
          this.textContent = 'Collapse ▲';
        } else {
          detail.style.display = 'none';
          this.textContent = 'Expand details ▼';
        }
      }
    });
  });

  b.querySelectorAll('[data-cg-case]').forEach(function (card) {
    card.addEventListener('click', function (e) {
      if (e.target.closest('[data-cg-expand]') || e.target.closest('[data-cg-cbox]')) return;
      var cid = parseInt(this.dataset.cgCase);
      var cb = this.querySelector('[data-cg-cbox="' + cid + '"]');
      if (cb) { cb.checked = !cb.checked; cb.dispatchEvent(new Event('change')); }
    });
  });

  var genBtn = b.querySelector('#cgGenerateBtn');
  if (genBtn && _cgSelectedCases.length > 0) {
    genBtn.addEventListener('click', async function () {
      if (_cgLoading) return;
      _cgLoading = true;
      _cgResult = null;
      DTCopyGen(b);
      try {
        var ctrl = new AbortController();
        var timer = setTimeout(function(){ ctrl.abort(); }, 60000);
        var resp = await authFetch('/api/case-intel/generate-copy', {
          method: 'POST',
          headers: {'Content-Type':'application/json'},
          body: JSON.stringify({
            prospect_id: dp.id,
            case_ids: _cgSelectedCases.slice(0, 3),
            channel: _cgChannel,
            tone_note: null,
            model: getPanelModel('model_copygen')
          }),
          signal: ctrl.signal
        });
        clearTimeout(timer);
        if (!resp.ok) {
          var errText = await resp.text();
          try { var errJson = JSON.parse(errText); throw new Error(errJson.detail || errText); } catch(e) { if (e.message !== errText) throw e; throw new Error(errText); }
        }
        _cgResult = await resp.json();
        _cgLoading = false;
        DTCopyGen(b);
      } catch (e) {
        _cgLoading = false;
        _cgResult = { error: (e.detail || e.message || String(e)) };
        DTCopyGen(b);
      }
    });
  }

  var saveSeqBtn = b.querySelector('#cgSaveSeq');
  if (saveSeqBtn && _cgResult && _cgResult.draft) {
    saveSeqBtn.addEventListener('click', async function () {
      var d = _cgResult.draft;
      try {
        await api('/sequences/' + dp.id, {
          method: 'POST',
          body: {
            step_number: 1,
            channel: _cgChannel,
            subject: d.subject || '(no subject)',
            content: d.body || '',
            scheduled_date: new Date().toISOString().slice(0, 10)
          }
        });
        T('Saved to development plan', '#16a34a');
      } catch (e) {
        T('Save failed: ' + (e.detail || e.message || ''), '#dc2626');
      }
    });
  }

  var saveDraftBtn = b.querySelector('#cgSaveDraft');
  if (saveDraftBtn && _cgResult && _cgResult.draft) {
    saveDraftBtn.addEventListener('click', async function () {
      var d = _cgResult.draft;
      try {
        var toEmail = dp.email || dp.dm_email || '';
        if (!toEmail) {
          T('This customer has no email address — cannot save as draft', '#dc2626');
          return;
        }
        await api('/email/queue', {
          method: 'POST',
          body: {
            prospect_id: dp.id,
            to_email: toEmail,
            subject: d.subject || '(no subject)',
            body: d.body || '',
            status: 'draft',
            sender_key: (typeof getSenderKey === 'function' ? getSenderKey('email_sender') : 'primary')
          }
        });
        T('Saved to email drafts', '#16a34a');
        if (typeof loadEmail === 'function') loadEmail();
      } catch (e) {
        T('Save draft failed: ' + (e.detail || e.message || ''), '#dc2626');
      }
    });
  }
}

function renderCopyResult(result) {
  if (result.error) {
    return '<div class="card p4" style="color:#dc2626">Generation failed: ' + E(result.error) + '</div>';
  }

  var d = result.draft || {};
  var subject = d.subject || '';
  var body = d.body || '';
  var sources = Array.isArray(d.sources) ? d.sources : [];
  var reasoning = result.reasoning || '';

  var h = '<div class="card p3">';

  var chMap = { email: 'Email', linkedin: 'LinkedIn', whatsapp: 'WhatsApp' };
  h += '<div class="flex jcs aic mb2">';
  h += '<span class="badge" style="background:#6366f1;color:#fff">' + (chMap[result.channel] || result.channel) + '</span>';
  if (result.selected_cases && result.selected_cases.length) {
    result.selected_cases.forEach(function (c) {
      h += '<span class="badge ml2" style="background:#e0e7ff;color:#3730a3;font-size:10px">Based on: ' + E((c.title || '').substring(0, 30)) + '</span>';
    });
  }
  h += '</div>';

  if (subject) {
    h += '<div class="mb2"><label class="fs11 c6" style="display:block;margin-bottom:2px">Subject</label>';
    h += '<div class="p2" style="background:#f8fafc;border-radius:4px;font-size:13px;font-weight:600">' + E(subject) + '</div></div>';
  }

  h += '<div class="mb2"><label class="fs11 c6" style="display:block;margin-bottom:2px">Body</label>';
  h += '<div class="p2" style="background:#f8fafc;border-radius:4px;font-size:13px;line-height:1.7;white-space:pre-wrap;min-height:120px">' + E(body) + '</div></div>';

  if (sources.length) {
    h += '<div class="mb3"><label class="fs11 c6" style="display:block;margin-bottom:4px">Referenced sources</label>';
    sources.forEach(function (s) {
      h += '<div class="p2 mb1" style="background:#fffced;border-radius:4px;font-size:11px;border-left:3px solid #f59e0b">';
      h += '<b>' + E(s.case_title || '') + '</b>: <span style="color:#475569">' + E(s.reference_line || '') + '</span>';
      h += '</div>';
    });
  }

  if (reasoning) {
    h += '<div class="mb3"><label class="fs11 c6" style="display:block;margin-bottom:2px">AI writing logic</label>';
    h += '<div class="p2 fs11" style="background:#f0fdf4;border-radius:4px;color:#166534;line-height:1.6">' + E(reasoning) + '</div></div>';
  }

  h += '<div class="flex g2">';
  h += '<button class="btn btn-sm btn-pri" id="cgSaveSeq">Save to plan</button>';
  h += '<button class="btn btn-sm" style="background:#34d399" id="cgSaveDraft">Save to email drafts</button>';
  h += '</div>';

  h += '</div>';
  return h;
}
