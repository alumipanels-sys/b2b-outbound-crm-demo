// Hiring Scout page
// Top: stored hiring-signal prospects; bottom: broad-search tool
var _hiringData = [];
var _hiringPage = 1;
var _hiringTotal = 0;

async function RHiring(p) {
  var h = '';
  h += '<h2 class="fs20 fwb mb4">🎯 Hiring Scout</h2>';

  // Section 1: existing hiring-sourced prospects
  h += '<div class="card-accent mb4">';
  h += '<div class="p3" style="border-bottom:1px solid #e2e8f0;display:flex;align-items:center;justify-content:space-between">';
  h += '<span class="fw6 fs14" style="color:#0f172a">Hiring-signal prospects</span>';
  h += '<span class="fs11 c6" id="hiringCount"></span>';
  h += '</div>';
  h += '<div id="hiringListBody" style="padding:8px 12px">';
  h += '<div class="fs12 c6" style="padding:10px;text-align:center">Loading...</div>';
  h += '</div>';
  h += '</div>';

  // Section 2: search tool
  h += '<p class="fs12 c6 mb3" style="line-height:1.6">Search recent job posts of target companies on LinkedIn, auto-extract company names, let AI judge whether they are potential customers, and import them with one click. <strong>Imported companies are tagged as "Hiring signal".</strong></p>';

  h += '<div class="card p4 mb4">';
  h += '<h3 class="fs14 fwb mb3">Search scope</h3>';
  h += '<div style="display:flex;gap:6px;flex-wrap:wrap;margin-bottom:12px" id="countryTags">';
  var allCountries = [
    {code:'DE',label:'Germany',desc:'high-end manufacturing'},
    {code:'AE',label:'Middle East',desc:'trade + re-export'},
    {code:'IN',label:'India',desc:'manufacturing + IT'},
    {code:'TR',label:'Turkey',desc:'manufacturing + trade'},
    {code:'IT',label:'Italy',desc:'manufacturing + design'},
    {code:'NL',label:'Netherlands',desc:'manufacturing + logistics'},
  ];
  allCountries.forEach(function(c, i){
    h += '<label style="cursor:pointer;display:flex;align-items:center;gap:4px;padding:4px 10px;border:1px solid #d1d5db;border-radius:6px;font-size:12px;background:#fff">';
    h += '<input type="checkbox" value="'+c.code+'" class="cc" '+(i<3?'checked':'')+'>';
    h += c.label+' <span style="color:#64748b;font-size:10px">'+c.desc+'</span>';
    h += '</label>';
  });
  h += '</div>';
  h += '<button class="btn" style="background:#9333ea" id="scoutBtn" onclick="doHiringScout()">Start search</button>';
  h += '<span id="scoutStatus" style="font-size:12px;color:#64748b;margin-left:10px"></span>';
  h += '</div>';

  // Batch results
  h += '<div class="card p4" id="scoutResults" style="display:none">';
  h += '<h3 class="fs14 fwb mb3">Search results</h3>';
  h += '<div id="scoutResultBody"></div>';
  h += '</div>';

  p.innerHTML = h;

  loadHiringList();
}

async function loadHiringList() {
  try {
    var r = await api('/prospects?source='+encodeURIComponent('Hiring signal')+'&limit=50&sort=created_at&order=desc');
    _hiringData = r.items || [];
    _hiringTotal = r.total || 0;
  } catch(e) {
    _hiringData = [];
    _hiringTotal = 0;
  }
  renderHiringList();
}

function renderHiringList() {
  var body = document.getElementById('hiringListBody');
  var countEl = document.getElementById('hiringCount');
  if (!body) return;

  if (countEl) countEl.textContent = _hiringTotal + ' total';

  if (!_hiringData.length) {
    body.innerHTML = '<div class="empty-state" style="padding:20px">No hiring-signal customers yet — run a search to import some.</div>';
    return;
  }

  var h = '';
  _hiringData.forEach(function(x){
    var pt = x.profile_type || '';
    var vl = x.value_level || '';
    var score = x.ai_score != null ? Math.round(x.ai_score) : null;
    var isVIP = pt === 'A' && vl === 'HIGH';
    var badgeColor = pt === 'A' ? '#7c3aed' : pt === 'B' ? '#2563eb' : pt === 'C' ? '#059669' : '#64748b';
    var stageLabel = ({new:'New',touched:'Touched',connected:'Connected',replied:'Replied',interested:'Interested',sample_pending:'Sample pending',sample_sent:'Sample sent',testing:'Testing',feedback:'Feedback',trial_order:'Trial order',won:'Won',lost:'Lost',cooling:'Cooling'})[x.sales_stage||'new'] || (x.sales_stage||'-');

    h += '<div class="prospect-row" style="border-left:3px solid '+badgeColor+'" data-open="'+x.id+'">';
    h += '<div style="flex:3;min-width:0">';
    h += '<div style="font-weight:600;font-size:13px;color:#0f172a;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">';
    if (isVIP) h += '⭐ ';
    h += E(x.company||'');
    h += ' <span style="font-size:11px;color:#64748b;font-weight:400">' + E(x.country||'') + '</span>';
    h += '</div>';
    h += '<div style="font-size:11px;color:#94a3b8;margin-top:2px;display:flex;align-items:center;gap:6px">';
    if (x.contact) h += '<span>' + E(x.contact) + '</span><span style="color:#d1d5db">·</span>';
    if (x.industry) h += '<span>' + E(x.industry) + '</span><span style="color:#d1d5db">·</span>';
    h += '<span style="background:'+badgeColor+';color:#fff;font-size:9px;padding:1px 5px;border-radius:3px;font-weight:600">'+E(pt||'?')+'</span>';
    if (vl === 'HIGH') h += '<span style="background:#fef3c7;color:#92400e;font-size:9px;padding:1px 5px;border-radius:3px;font-weight:600">HIGH</span>';
    if (score != null) h += '<span style="color:#d1d5db">·</span><span>Score '+score+'</span>';
    h += '<span style="color:#d1d5db">·</span><span style="background:#f0fdf4;color:#15803d;font-size:9px;padding:1px 5px;border-radius:3px">'+stageLabel+'</span>';
    h += '</div>';
    h += '</div>';
    h += '<div style="flex-shrink:0">';
    h += '<button class="btn btn-sm btn-b" onclick="event.stopPropagation();openDrawer('+x.id+')" style="font-size:10px;padding:2px 8px">Details</button>';
    h += '</div>';
    h += '</div>';
  });

  body.innerHTML = h;

  body.querySelectorAll('.prospect-row').forEach(function(row){
    row.addEventListener('click', function(e){
      if (e.target.tagName === 'BUTTON') return;
      var id = parseInt(row.dataset.open);
      if (typeof openDrawer === 'function') openDrawer(id);
    });
  });
}

async function doHiringScout() {
  var btn = document.getElementById('scoutBtn');
  var status = document.getElementById('scoutStatus');
  btn.disabled = true;
  btn.textContent = 'Searching...';

  var countries = [];
  document.querySelectorAll('.cc:checked').forEach(function(cb){ countries.push(cb.value); });
  if (!countries.length) { T('Select at least one country', '#dc2626'); btn.disabled = false; btn.textContent = 'Start search'; return; }

  status.textContent = 'Searching hiring posts in ' + countries.join(', ') + '...';
  T('Hiring scout started — targets: ' + countries.join(', '), '#9333ea', 3000);

  try {
    var r = await api('/ai/hiring-scout', { method: 'POST', body: { countries: countries } });
    if (!r.success) { T(r.error || 'Search returned no results', '#f59e0b'); status.textContent = ''; btn.disabled = false; btn.textContent = 'Search again'; return; }

    var div = document.getElementById('scoutResults');
    var body = document.getElementById('scoutResultBody');

    var h = '';
    h += '<div class="mb3" style="display:flex;gap:10px;flex-wrap:wrap">';
    h += '<div class="badge" style="background:#9333ea;color:#fff;font-size:13px;padding:4px 12px">Searched: '+r.total_searched+'</div>';
    h += '<div class="badge" style="background:#16a34a;color:#fff;font-size:13px;padding:4px 12px">Imported: '+r.total_imported+'</div>';
    h += '</div>';

    if (r.by_country && r.by_country.length > 0) {
      h += '<table style="width:100%"><thead><tr><th>Country</th><th>Imported</th><th>Skipped</th><th>Errors</th></tr></thead><tbody>';
      var countryNames = {DE:'Germany',AE:'Middle East',IN:'India',TR:'Turkey',IT:'Italy',NL:'Netherlands'};
      r.by_country.forEach(function(x){
        h += '<tr><td>'+E(countryNames[x.country]||x.country)+'</td>';
        h += '<td style="color:#16a34a;font-weight:600">'+x.imported+'</td>';
        h += '<td style="color:#64748b">'+x.skipped+'</td>';
        h += '<td style="color:#dc2626">'+x.errors+'</td></tr>';
      });
      h += '</tbody></table>';
    }

    if (r.total_imported > 0) {
      h += '<div class="mt3 p3" style="background:#f0fdf6;border-radius:6px;border:1px solid #bbf7d0">';
      h += '<span class="fs13 fwm" style="color:#166534">Auto-imported '+r.total_imported+' new customers, tagged "Hiring signal".</span>';
      h += '</div>';
      loadHiringList();
    } else {
      h += '<div class="mt3 p3" style="background:#fffced;border-radius:6px;border:1px solid #fde68a">';
      h += '<span class="fs13 fwm" style="color:#92400e">No new potential customers found (may already exist or failed AI screening). Try another country?</span>';
      h += '</div>';
    }

    body.innerHTML = h;
    div.style.display = 'block';
    status.textContent = 'Done — imported ' + r.total_imported + ' customers';
    T('Search done: ' + r.total_searched + ' results, imported ' + r.total_imported + ' customers', r.total_imported>0?'#16a34a':'#f59e0b');
    if (typeof updateHiringBadge === 'function') updateHiringBadge();
  } catch(e) {
    T('Search failed: ' + (e.detail || e.message || String(e)), '#dc2626');
    status.textContent = 'Search failed';
  }
  btn.disabled = false;
  btn.textContent = 'Search again';
}
