// Review report: which customer types reply most, which channel is worth investing in

async function RReview(p){
  p.innerHTML = '<div class="empty-state card">Loading...</div>';
  var data;
  try{
    data = await api('/performance/review?days=30');
  }catch(e){
    p.innerHTML = '<div class="card tc p4" style="color:#dc2626">'+E(e.detail||e.message||String(e))+'</div>';
    return;
  }
  var h = '<h2 class="fs20 fwb mb3">Outreach Review</h2>';
  h += '<p class="fs12 c6 mb3">Last 30 days: which customer types reply most, and which source channels deserve investment. After reviewing, adjust the screening criteria in Knowledge Base &gt; ICP &amp; Strategy.</p>';
  h += _table('By source channel', data.by_channel || []);
  h += _table('By industry', data.by_industry || []);
  p.innerHTML = h;
}

function _table(title, rows){
  var isChannel = title.toLowerCase().indexOf('channel') > -1;
  var h = '<div class="card p3 mb3">';
  h += '<p class="fwm fs13 mb2">'+title+'</p>';
  if(!rows.length){
    h += '<div class="fs12 c6 tc" style="padding:16px">No data yet (develop some customers first)</div>';
  }else{
    h += '<table style="width:100%;font-size:12px"><tr style="text-align:left;color:#64748b">';
    h += '<th style="padding:6px">'+(isChannel?'Channel':'Industry')+'</th><th style="padding:6px">Sent</th>';
    h += '<th style="padding:6px">Replies</th><th style="padding:6px">Reply rate</th><th style="padding:6px">Won</th><th style="padding:6px">Win rate</th></tr>';
    rows.forEach(function(r){
      var rateColor = r.reply_rate >= 15 ? '#16a34a' : (r.reply_rate >= 5 ? '#f59e0b' : '#64748b');
      h += '<tr style="border-top:1px solid #f1f5f9">';
      h += '<td style="padding:6px"><b>'+E(r.key)+'</b></td>';
      h += '<td style="padding:6px">'+r.sent+'</td>';
      h += '<td style="padding:6px">'+r.replies+'</td>';
      h += '<td style="padding:6px;color:'+rateColor+'">'+r.reply_rate+'%</td>';
      h += '<td style="padding:6px">'+r.won+'</td>';
      h += '<td style="padding:6px">'+r.won_rate+'%</td></tr>';
    });
    h += '</table>';
  }
  h += '</div>';
  return h;
}
