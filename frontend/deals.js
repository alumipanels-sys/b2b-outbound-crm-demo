// Deals Pipeline Page
let dealFilter = '';

var DEAL_STAGE_CN = ['Initial contact', 'Requirements confirmed', 'Quotation sent', 'Negotiating', 'Won', 'Lost'];
var DEAL_STAGE_EN = ['First Contact', 'Requirements Confirmed', 'Proposal & Quote', 'Negotiating', 'Won', 'Lost'];
var DEAL_LEGACY_CN = {'需求确认':'Requirements Confirmed','方案报价':'Proposal & Quote','谈判中':'Negotiating','已成交':'Won'};
function stageToEn(cn){ if (DEAL_LEGACY_CN[cn]) return DEAL_LEGACY_CN[cn]; var i = DEAL_STAGE_CN.indexOf(cn); return i >= 0 ? DEAL_STAGE_EN[i] : (cn || '-'); }
function stageToCn(en){ var i = DEAL_STAGE_EN.indexOf(en); return i >= 0 ? DEAL_STAGE_CN[i] : (en || ''); }

async function RDeals(p) {
  var funnel = [];
  try { funnel = await api('/deals/funnel'); } catch (e) { funnel = []; }

  var stages = DEAL_STAGE_EN;
  var colors = ['#f97316', '#3b82f6', '#8b5cf6', '#ec4899', '#16a34a', '#6b7280'];
  var activeDeals = [];
  var totalAmount = 0;
  funnel.forEach(function (f) {
    if (f.stage !== 'Won' && f.stage !== 'Lost') activeDeals.push(f);
    totalAmount += f.total_amount;
  });
  var activeCount = activeDeals.reduce(function (a, f) { return a + f.count; }, 0);

  var h = '<div class="page-hd" style="align-items:center"><div><h2>Deals & Orders</h2><p class="page-sub">Create deals from customer details, move them through stages, and totals are summed automatically.</p></div>'
    + '<button class="btn btn-pri" id="addDealTopBtn">＋ New Deal</button></div>';
  h += '<div style="display:flex;gap:10px;margin-bottom:18px;flex-wrap:wrap">';
  h += '<div class="stat-card" style="--stat-color:#2563eb"><div class="stat-label">Active deals</div><div class="stat-value-wrapper"><span class="stat-value">' + activeCount + '</span></div></div>';
  h += '<div class="stat-card" style="--stat-color:#16a34a"><div class="stat-label">Total amount (EUR)</div><div class="stat-value-wrapper"><span class="stat-value" style="font-size:20px">' + fmtAmount(totalAmount) + '</span></div></div>';
  var won = funnel.find(function (f) { return f.stage === 'Won'; });
  h += '<div class="stat-card" style="--stat-color:#9333ea"><div class="stat-label">Won</div><div class="stat-value-wrapper"><span class="stat-value">' + (won ? won.count : 0) + '</span></div></div>';
  h += '</div>';

  // Funnel chart
  h += '<div class="card mb4" style="overflow:hidden"><div style="padding:12px 16px;background:#f7f9fc;border-bottom:1px solid #e4e9f2;display:flex;align-items:center;gap:8px">';
  h += '<span class="dot" style="width:8px;height:8px;border-radius:50%;background:#8b5cf6"></span>';
  h += '<span class="fs14 fwb" style="color:#0f172a">Sales funnel</span><span class="fs11 c6">Deal count and amount by stage</span></div>';
  h += '<div style="padding:16px 18px">';
  var maxCount = Math.max.apply(null, funnel.map(function (f) { return f.count; })) || 1;
  funnel.forEach(function (f, i) {
    var pct = Math.round(f.count / maxCount * 100);
    var bg = colors[i];
    h += '<div style="display:flex;align-items:center;gap:10px;margin-bottom:8px">';
    h += '<span style="width:80px;font-size:13px;font-weight:500">' + stageToEn(f.stage) + '</span>';
    h += '<div style="flex:1;height:24px;background:#f8fafc;border-radius:4px;overflow:hidden">';
    h += '<div style="height:100%;width:' + pct + '%;background:' + bg + ';border-radius:4px;display:flex;align-items:center;padding-left:10px;color:#fff;font-size:12px;font-weight:600">' + f.count + '</div></div>';
    h += '<span style="width:100px;text-align:right;font-size:12px;color:#64748b">' + fmtAmount(f.total_amount) + '</span>';
    h += '</div>';
  });
  h += '</div></div>';

  // Deal list
  h += '<div class="card p3 mb3 flex g2 aic fw"><span class="fs12 c6">Filter:</span>';
  h += '<button class="btn btn-sm" style="background:' + (dealFilter ? '#e5e7eb' : '#2563eb') + ';color:' + (dealFilter ? '#374151' : '#fff') + '" id="dfAll">All</button>';
  stages.forEach(function (s) {
    h += '<button class="btn btn-sm" style="background:' + (dealFilter === s ? '#2563eb' : '#e5e7eb') + ';color:' + (dealFilter === s ? '#fff' : '#374151') + '" data-df="' + s + '">' + s + '</button>';
  });
  h += '<span style="flex:1"></span>';
  h += '<button class="btn" style="background:#16a34a" id="addDealBtn">+ New Deal</button>';
  h += '</div>';

  var deals = [];
  try {
    deals = dealFilter ? await api('/deals?stage=' + encodeURIComponent(stageToCn(dealFilter))) : await api('/deals');
  } catch (e) { deals = []; }

  if (!deals.length) {
    h += '<div class="card tc" style="padding:40px;color:#64748b"><div style="font-size:40px;margin-bottom:8px">📊</div><div style="font-size:14px">No deals yet</div><div style="font-size:12px;margin-top:4px">Create a deal from the customer detail page, or use the button above.</div></div>';
  } else {
    h += '<div class="card oa"><table><thead><tr><th>Deal name</th><th>Customer</th><th>Amount</th><th>Stage</th><th>Expected date</th><th style="width:60px">Actions</th></tr></thead><tbody>';
    deals.forEach(function (d) {
      var sc = colors[DEAL_STAGE_CN.indexOf(d.stage)] || '#6b7280';
      h += '<tr>';
      h += '<td class="fwm" style="cursor:pointer" data-open-dp="' + d.prospect_id + '">' + E(d.name) + '</td>';
      h += '<td class="fwm c6" style="cursor:pointer" data-open-dp="' + d.prospect_id + '">Customer #' + d.prospect_id + '</td>';
      h += '<td style="font-weight:600;color:#16a34a">' + fmtAmount(d.amount || 0) + '</td>';
      h += '<td><span class="badge" style="background:' + sc + ';color:#fff">' + E(stageToEn(d.stage)) + '</span></td>';
      h += '<td style="color:#aaa">' + E(d.expected_date || '-') + '</td>';
      h += '<td style="white-space:nowrap"><button class="btn btn-sm" style="background:#3b82f6" data-edit-deal="' + d.id + '">Edit</button> <button class="btn btn-sm" style="background:#dc2626" data-del-deal="' + d.id + '">Delete</button></td>';
      h += '</tr>';
    });
    h += '</tbody></table></div>';
  }

  p.innerHTML = h;

  bindSafe(p, '#dfAll', 'click', function () { dealFilter = ''; RDeals(p); });
  p.querySelectorAll('[data-df]').forEach(function (b) {
    b.addEventListener('click', function () { dealFilter = b.dataset.df; RDeals(p); });
  });

  bindSafe(p, '#addDealBtn', 'click', function () { showDealForm(p, null); });
  bindSafe(p, '#addDealTopBtn', 'click', function () { showDealForm(p, null); });

  p.querySelectorAll('[data-open-dp]').forEach(function (el) {
    el.addEventListener('click', function () { openDrawer(parseInt(el.dataset.openDp)); });
  });

  p.querySelectorAll('[data-edit-deal]').forEach(function (el) {
    el.addEventListener('click', function () { showDealForm(p, parseInt(el.dataset.editDeal)); });
  });

  p.querySelectorAll('[data-del-deal]').forEach(function (el) {
    el.addEventListener('click', function () {
      if (!confirm('Delete this deal?')) return;
      api('/deals/' + parseInt(el.dataset.delDeal), { method: 'DELETE' }).then(function () { T('Deleted'); RDeals(p); }).catch(function () { T('Delete failed', '#dc2626'); });
    });
  });
}

function showDealForm(p, editId) {
  var deal = null;

  var h = '<div id="dealFormMask" class="mask" style="z-index:60"></div>';
  h += '<div id="dealFormDrawer" class="drawer" style="z-index:61;max-width:500px"><div class="drawer-header"><div class="drawer-header-top"><h3>' + (editId ? 'Edit Deal' : 'New Deal') + '</h3><button id="dealFormClose">&times;</button></div></div>';
  h += '<div class="drawer-body">';

  if (editId) {
    h += '<input type="hidden" id="dfEditId" value="' + editId + '">';
  }

  h += '<div class="mb3"><label class="fs11 c6">Deal name</label><input id="dfName" placeholder="e.g. Annual order from XYZ Distributors"></div>';
  h += '<div class="mb3"><label class="fs11 c6">Customer</label><select id="dfProspect"><option value="">Select customer</option></select></div>';
  h += '<div class="mb3"><label class="fs11 c6">Amount (EUR)</label><input type="number" id="dfAmount" value="0" step="0.01"></div>';
  h += '<div class="mb3"><label class="fs11 c6">Stage</label><select id="dfStage">';
  DEAL_STAGE_EN.forEach(function (s) {
    h += '<option value="' + s + '">' + s + '</option>';
  });
  h += '</select></div>';
  h += '<div class="mb3"><label class="fs11 c6">Expected close date</label><input type="date" id="dfDate"></div>';
  h += '<div class="mb3"><label class="fs11 c6">Note</label><textarea id="dfNote" rows="3"></textarea></div>';
  h += '<div class="flex g2"><button class="btn" style="background:#2563eb" id="dfSave">Save</button><button class="btn" style="background:#e5e7eb;color:#334155" id="dfCancel">Cancel</button></div>';
  h += '</div></div>';

  document.body.insertAdjacentHTML('beforeend', h);

  api('/prospects?limit=200').then(function (r) {
    var sel = document.getElementById('dfProspect');
    if (!sel) return;
    r.items.forEach(function (pr) {
      sel.innerHTML += '<option value="' + pr.id + '">' + (pr.company || '?') + (pr.contact ? ' - ' + pr.contact : '') + '</option>';
    });
    if (editId) {
      api('/deals/' + editId).then(function (d) {
        var nm = document.getElementById('dfName'); if (nm) nm.value = d.name || '';
        var dp = document.getElementById('dfProspect'); if (dp) dp.value = d.prospect_id || '';
        var am = document.getElementById('dfAmount'); if (am) am.value = d.amount || 0;
        var st = document.getElementById('dfStage'); if (st) st.value = stageToEn(d.stage) || 'First Contact';
        var dt = document.getElementById('dfDate'); if (dt) dt.value = d.expected_date || '';
        var nt = document.getElementById('dfNote'); if (nt) nt.value = d.note || '';
      }).catch(function () { T('Failed to load deal', '#dc2626'); });
    }
  });

  function close() {
    var m = document.getElementById('dealFormMask'); if (m) m.remove();
    var d = document.getElementById('dealFormDrawer'); if (d) d.remove();
  }

  document.getElementById('dealFormMask').onclick = close;
  document.getElementById('dealFormClose').onclick = close;
  document.getElementById('dfCancel').addEventListener('click', close);

  document.getElementById('dfSave').addEventListener('click', function () {
    var body = {
      name: document.getElementById('dfName').value.trim(),
      prospect_id: parseInt(document.getElementById('dfProspect').value) || 0,
      amount: parseFloat(document.getElementById('dfAmount').value) || 0,
      stage: stageToCn(document.getElementById('dfStage').value),
      expected_date: document.getElementById('dfDate').value,
      note: document.getElementById('dfNote').value.trim()
    };
    if (!body.name) { T('Enter a deal name', '#dc2626'); return; }
    if (!body.prospect_id) { T('Select a customer', '#dc2626'); return; }

    var url = editId ? '/deals/' + editId : '/deals';
    var method = editId ? 'PUT' : 'POST';
    api(url, { method: method, body: body }).then(function () {
      T(editId ? 'Updated' : 'Created');
      close();
      RDeals(p);
    }).catch(function (e) { T('Save failed: ' + (e.detail || e.message || ''), '#dc2626'); });
  });
}

function fmtAmount(n) {
  if (!n) return '€0';
  n = Number(n);
  if (n >= 1000000) return '€' + (n / 1000000).toFixed(1) + 'M';
  if (n >= 1000) return '€' + (n / 1000).toFixed(0) + 'K';
  return '€' + n.toFixed(0);
}
