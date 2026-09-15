const state = { token: sessionStorage.getItem('nf_app_token') || null, user: null, farmId: null, page: null, chatMessages: [], chatFarmId: null, overviewTimer: null, selectedKnowledgeDoc: null };
const $ = (s) => document.querySelector(s);

function authHeaders(extra={}) {
  return { ...extra, ...(state.token ? { Authorization: `Bearer ${state.token}` } : {}) };
}
async function api(path, options={}) {
  const res = await fetch(path, { ...options, headers: authHeaders(options.headers || {}) });
  let data = null;
  try { data = await res.json(); } catch { data = {}; }
  if (res.status === 401 && state.token) {
    sessionStorage.removeItem('nf_app_token');
    state.token = null;
    if (!path.includes('/auth/login')) showLogin('Phiên đăng nhập đã hết hạn. Vui lòng đăng nhập lại.');
  }
  if (!res.ok) {
    const detail = data?.error?.message || data?.detail?.message || data?.detail;
    throw new Error(typeof detail === 'string' ? detail : `Lỗi ${res.status}`);
  }
  return data;
}
async function loadProtectedImage(element, path) {
  const img = typeof element === 'string' ? $(element) : element;
  const res = await fetch(path, { headers: authHeaders() });
  if (!res.ok) throw new Error(`Không tải được biểu đồ (${res.status})`);
  const url = URL.createObjectURL(await res.blob());
  if (img.dataset.objectUrl) URL.revokeObjectURL(img.dataset.objectUrl);
  img.dataset.objectUrl = url; img.src = url;
}
function esc(v='') { return String(v).replace(/[&<>'"]/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;',"'":'&#39;','"':'&quot;'}[c])); }
function safeUrl(v='') { try { const u=new URL(String(v)); return u.protocol==='https:'?u.href:'#'; } catch { return '#'; } }
function time(v) { if (!v) return '-'; return new Date(v).toLocaleString('vi-VN', { hour:'2-digit', minute:'2-digit', day:'2-digit', month:'2-digit' }); }
function statusText(v) { return ({open:'Mới',in_progress:'Đang xử lý',waiting_customer:'Chờ khách hàng',resolved:'Đã giải quyết',closed:'Đã đóng',reopened:'Mở lại'})[v] || v; }
function priorityText(v) { return ({urgent:'Khẩn cấp',high:'Cao',normal:'Bình thường',low:'Thấp'})[v] || v; }
function toast(text) { const el=$('#toast'); el.textContent=text; el.hidden=false; setTimeout(()=>el.hidden=true,2600); }
function loading() { $('#content').innerHTML='<div class="loading">Đang tải dữ liệu...</div>'; }
function showError(err) { $('#content').innerHTML=`<div class="panel"><h3>Không tải được dữ liệu</h3><p class="error">${esc(err.message)}</p></div>`; }
function clearOverviewTimer(){ if(state.overviewTimer){ clearInterval(state.overviewTimer); state.overviewTimer=null; } }
function showLogin(message='') {
  clearOverviewTimer();
  $('#appView').hidden=true; $('#loginView').hidden=false;
  $('#loginError').textContent=message;
  window.scrollTo(0,0);
}
function latestValue(rows,key){ const row=(rows||[]).find(x=>x[key]!==null&&x[key]!==undefined); return row?row[key]:null; }
function metricLabel(metric){ return ({soil_moisture:'Độ ẩm đất',air_humidity:'Độ ẩm không khí',temperature:'Nhiệt độ',ec:'EC',ph:'pH',flow_rate:'Lưu lượng'})[metric]||metric; }
function metricUnit(metric){ return ({soil_moisture:'%',air_humidity:'%',temperature:'°C',ec:'mS/cm',ph:'',flow_rate:'L/phút'})[metric]||''; }
function num(v,d=1){ return v===null||v===undefined?'—':Number(v).toFixed(d); }


function loadDemoAccounts() { /* Mật khẩu không bao giờ được tải xuống trình duyệt. */ }

$('#loginForm').addEventListener('submit', async e => {
  e.preventDefault(); $('#loginError').textContent='';
  const btn=$('#loginBtn'); const label=btn.querySelector('span');
  btn.disabled=true; label.textContent='Đang xác thực...';
  try {
    const data = await api('/api/identity/auth/login', { method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({username:$('#username').value.trim(),password:$('#password').value}) });
    state.token=data.access_token; state.user=data.user; state.farmId=data.user.default_farm_id;
    sessionStorage.setItem('nf_app_token',state.token);
    enterApp(); toast(`Xin chào ${state.user.display_name}`);
  } catch(err) { $('#loginError').textContent=err.message; }
  finally { btn.disabled=false; label.textContent='Đăng nhập'; }
});
$('#logoutBtn').addEventListener('click', () => { sessionStorage.removeItem('nf_app_token'); sessionStorage.removeItem('nf_selected_farm'); state.token=null; state.user=null; state.farmId=null; showLogin(''); });
$('#farmPicker').addEventListener('change', () => {
  state.farmId=$('#farmPicker').value||null;
  if(state.farmId) sessionStorage.setItem('nf_selected_farm',state.farmId);
  else sessionStorage.removeItem('nf_selected_farm');
  if(state.chatFarmId!==state.farmId){ state.chatMessages=[]; state.chatFarmId=null; }
  if(state.farmId) renderPage(state.page||'overview');
  else showFarmSelection();
});

function showFarmSelection(){
  clearOverviewTimer();
  $('#content').innerHTML='<div class="panel"><h3>Chọn vườn cần làm việc</h3><p>Tài khoản có quyền trên nhiều vườn. Hãy chọn đúng vườn ở thanh phía trên trước khi xem dữ liệu hoặc hỏi chatbot.</p></div>';
}

function enterApp() {
  $('#loginView').hidden=true; $('#appView').hidden=false;
  window.scrollTo(0,0);
  $('#userCard').innerHTML=`<b>${esc(state.user.display_name)}</b><small>${state.user.role==='farmer'?'Nông dân':'Kỹ thuật viên hỗ trợ'}</small>`;
  const needsSelection=state.user.role==='farmer'&&state.user.requires_farm_selection;
  $('#farmPicker').innerHTML=(needsSelection?'<option value="">-- Chọn vườn --</option>':'')+(state.user.farms||[]).map(f=>`<option value="${esc(f.farm_id)}">${esc(f.farm_name)}</option>`).join('');
  $('#farmPicker').value=state.farmId||'';
  $('#farmPickerWrap').hidden=state.user.role==='technician';
  const items = state.user.role==='farmer'
    ? [['overview','Tổng quan vườn'],['aiinsights','Gợi ý từ AI'],['chat','Chat hỗ trợ'],['tickets','Yêu cầu hỗ trợ'],['notifications','Cảnh báo'],['knowledge','Hướng dẫn']]
    : [['techdash','Trung tâm vận hành'],['queue','Ticket hỗ trợ'],['techknowledge','Kho tri thức'],['notify','Gửi cảnh báo']];
  $('#nav').innerHTML=items.map(([id,label])=>`<button class="nav-btn" data-page="${id}"><span>${label}</span></button>`).join('');
  document.querySelectorAll('.nav-btn').forEach(b=>b.addEventListener('click',()=>renderPage(b.dataset.page)));
  if(state.user.role==='farmer'&&!state.farmId) showFarmSelection(); else renderPage(items[0][0]);
}
function setPageMeta(title, eyebrow) {
  $('#pageTitle').textContent=title; $('#pageEyebrow').textContent=eyebrow;
  document.querySelectorAll('.nav-btn').forEach(b=>b.classList.toggle('active', b.dataset.page===state.page));
}
async function renderPage(page) {
  clearOverviewTimer();
  state.page=page; loading();
  if(state.user?.role==='farmer'&&!state.farmId){ showFarmSelection(); return; }
  try {
    if(page==='overview') await farmerOverview();
    if(page==='aiinsights') await farmerAiInsights();
    if(page==='modellab') await farmerModelLab();
    if(page==='knowledge') await farmerKnowledge();
    if(page==='chat') await farmerChat();
    if(page==='tickets') await ticketList(false);
    if(page==='notifications') await farmerNotifications();
    if(page==='queue') await ticketList(true);
    if(page==='techdash') await techDashboard();
    if(page==='techknowledge') await technicianKnowledge();
    if(page==='notify') await notificationForm();
  } catch(err) { showError(err); }
}

function dataOriginInfo(rows){
  const origins=new Set((rows||[]).flatMap(x=>String(x.data_origin||'').split(',')).map(x=>x.trim()).filter(Boolean));
  const allowed=new Set(['simulated_device_calibrated_v9','nextfarm_api','nextfarm_mqtt','manual_import','partner_api']);
  if([...origins].some(x=>!allowed.has(x))) return {kind:'unknown',label:'Nguồn không hợp lệ',detail:'Có provenance ngoài data contract; hệ thống phải dừng sử dụng các mẫu này và báo kỹ thuật viên.'};
  if(origins.size===1&&origins.has('simulated_device_calibrated_v9')) return {kind:'simulated',label:'Mô phỏng thiết bị đã hiệu chỉnh',detail:'Telemetry demo của V10 được sinh liên tục từ mô hình trạng thái đã hiệu chỉnh bằng static reference công khai; không phải số đo phần cứng thật.'};
  if(origins.size&& !origins.has('simulated_device_calibrated_v9')) return {kind:'real',label:'Dữ liệu tích hợp có provenance',detail:`Nguồn: ${[...origins].join(', ')}. Giá trị vẫn phải qua freshness và quality gate trước khi kết luận.`};
  if(origins.size>1) return {kind:'mixed',label:'Dữ liệu hỗn hợp mô phỏng/tích hợp',detail:'Màn hình đang có nhiều provenance; không dùng kết quả gộp để tuyên bố số đo phần cứng thật.'};
  return {kind:'unknown',label:'Chưa có provenance',detail:'V10 không hiển thị mẫu không có provenance hợp lệ.'};
}

function realtimePipelineState(sim,telemetry,rows){
  const simOk=sim?.status==='ok' && sim?.mqtt_connected!==false;
  const ingestOk=telemetry?.status==='ok' && telemetry?.connected===true;
  const hasRows=(rows||[]).length>0;
  if(simOk&&ingestOk&&hasRows) return {ok:true,label:'Realtime đang hoạt động',title:'Dữ liệu đang chảy về hệ thống',hint:'Không cần tải lại trang — bảng và biểu đồ tự cập nhật mỗi 10 giây.'};
  if(!ingestOk) return {ok:false,label:'MQTT/Ingestion chưa sẵn sàng',title:'Đang kết nối luồng cảm biến',hint:telemetry?.last_error||'Hệ thống đang chờ Telemetry Ingestion kết nối MQTT. Dữ liệu sẽ xuất hiện tự động khi kết nối hoàn tất.'};
  if(!simOk) return {ok:false,label:'Simulator đang khởi động',title:'Đang khởi động nguồn dữ liệu',hint:sim?.last_error||`Trạng thái: ${sim?.startup_stage||'đang chuẩn bị'}. Hệ thống sẽ tự thử lại.`};
  if(!hasRows) return {ok:false,label:'Chưa nhận mẫu gần đây',title:'Đang chờ dữ liệu cảm biến',hint:'MQTT đã kết nối nhưng PostgreSQL chưa có mẫu gần đây cho vườn này. Hệ thống đang tự đồng bộ.'};
  return {ok:false,label:'Đang kiểm tra realtime',title:'Đang kiểm tra luồng dữ liệu',hint:'Vui lòng chờ vài giây.'};
}

async function farmerOverview() {
  setPageMeta('Tổng quan vườn','DỮ LIỆU TRỰC TIẾP THEO THỜI GIAN');
  const farm=encodeURIComponent(state.farmId);
  const [data,grid,series,simHealth,telemetryHealth]=await Promise.all([
    api(`/api/chatbot/farm/dashboard?farm_id=${farm}`),
    api(`/api/farm/studio/grid?farm_id=${farm}&minutes=60&limit=120`),
    api(`/api/farm/studio/series?farm_id=${farm}&metric=soil_moisture&hours=1&bucket_seconds=30`),
    api('/api/simulator/health').catch(err=>({status:'down',last_error:err.message})),
    api('/api/telemetry/health').catch(err=>({status:'down',connected:false,last_error:err.message}))
  ]);
  const online=data.devices.items.filter(x=>x.effective_online).length;
  const rows=grid.items||[];
  const pipe=realtimePipelineState(simHealth,telemetryHealth,rows);
  const origin=dataOriginInfo(rows);
  const sensor=(label,key,unit,d=1)=>`<div class="sensor-card live"><span>${label}</span><b data-live-key="${key}">${num(latestValue(rows,key),d)}${latestValue(rows,key)!==null?` ${unit}`:''}</b><small>Cập nhật từ cảm biến</small></div>`;
  $('#content').innerHTML=`
    <section class="farmer-hero ${pipe.ok?'':'pipeline-warning'}"><div><p class="eyebrow light">${esc(data.overview.farm_name||'VƯỜN CỦA BẠN')}</p><h3 id="farmerRealtimeTitle">${esc(pipe.title)}</h3><p id="farmerRealtimeHint">${esc(pipe.hint)}</p><p class="data-origin-note"><b id="dataOriginLabel">${esc(origin.label)}</b> · <span id="dataOriginDetail">${esc(origin.detail)}</span></p></div><div class="hero-live ${pipe.ok?'':'warning'}"><i></i><span id="farmerLiveText">${esc(pipe.label)}</span></div></section>
    <div class="metrics">
      <div class="metric"><small>Khu canh tác</small><strong>${data.overview.zones.length}</strong><span class="metric-sub">được cấp quyền truy cập</span></div>
      <div class="metric"><small>Thiết bị đang online</small><strong>${online}/${data.devices.total}</strong><span class="metric-sub">trạng thái thiết bị mới nhất</span></div>
      <div class="metric"><small>Cảnh báo đang mở</small><strong>${data.alerts.total}</strong><span class="metric-sub">cần theo dõi hoặc xử lý</span></div>
      <div class="metric metric-live"><small>Ca tưới hôm nay</small><strong>${data.irrigation.run_count}</strong><span class="metric-sub">ghi nhận trong hệ thống</span></div>
    </div>
    <div class="sensor-strip">
      ${sensor('Độ ẩm đất','soil_moisture','%',1)}
      ${sensor('Nhiệt độ','temperature','°C',1)}
      ${sensor('Độ ẩm không khí','air_humidity','%',1)}
      ${sensor('EC','ec','mS/cm',2)}
      ${sensor('pH','ph','',2)}
      ${sensor('Lưu lượng','flow_rate','L/phút',1)}
    </div>
    <div class="realtime-layout">
      <section class="panel"><div class="panel-head"><div><h3>Diễn biến theo thời gian</h3><p class="muted">Đường biểu diễn lấy từ PostgreSQL và giữ nhãn nguồn dữ liệu của từng mẫu.</p></div><div class="trend-toolbar"><select id="trendMetric"><option value="soil_moisture">Độ ẩm đất</option><option value="temperature">Nhiệt độ</option><option value="air_humidity">Độ ẩm không khí</option><option value="ec">EC</option><option value="ph">pH</option><option value="flow_rate">Lưu lượng</option></select><select id="trendHours"><option value="1">1 giờ</option><option value="6">6 giờ</option><option value="24">24 giờ</option></select></div></div><canvas id="farmerTrend" class="trend-chart" width="1100" height="320"></canvas><div class="chart-meta"><span id="trendLegend">Đang tải...</span><span id="lastSync" class="sync-text"></span></div></section>
      <section class="panel"><div class="panel-head"><div><h3>Cảnh báo cần chú ý</h3><p class="muted">Ưu tiên thông tin có thể ảnh hưởng tới vườn.</p></div><button class="secondary" id="goChat">Hỏi AI</button></div>${data.alerts.items.length?data.alerts.items.slice(0,5).map(a=>`<div class="alert-card ${esc(a.severity)}"><span class="badge ${esc(a.severity)}">${esc(a.severity)}</span><h4>${esc(a.title)}</h4><p>${esc(a.message)}</p><small>${time(a.detected_at)}</small></div>`).join(''):'<div class="empty">Không có cảnh báo mở. Vườn đang trong trạng thái ổn định.</div>'}</section>
    </div>
    <section class="panel"><div class="panel-head"><div><h3>Dòng dữ liệu gần nhất</h3><p class="muted">Mỗi dòng là một thời điểm cảm biến được ghi nhận; dữ liệu mới sẽ xuất hiện tự động.</p></div><span class="badge approved" id="rowFreshBadge">${rows.length} mẫu gần đây</span></div><div class="table-wrap"><table class="table"><thead><tr><th>Thời gian</th><th>Khu</th><th>Ẩm đất</th><th>Nhiệt độ</th><th>Ẩm KK</th><th>EC</th><th>pH</th><th>Lưu lượng</th><th>Nguồn</th></tr></thead><tbody id="farmerRealtimeBody">${farmerRowsHtml(rows)}</tbody></table></div></section>`;
  drawFarmerSeries(series.items||[],'soil_moisture');
  $('#goChat').addEventListener('click',()=>renderPage('chat'));
  $('#trendMetric').addEventListener('change',()=>loadFarmerTrend());
  $('#trendHours').addEventListener('change',()=>loadFarmerTrend());
  state.overviewTimer=setInterval(()=>refreshFarmerRealtime().catch(()=>{}),10000);
}

function farmerRowsHtml(rows){
  return (rows||[]).slice(0,18).map(x=>{const o=dataOriginInfo([x]);return `<tr><td>${time(x.observed_at)}</td><td><b>Khu ${esc(x.zone_code||'—')}</b></td><td>${num(x.soil_moisture,1)}</td><td>${num(x.temperature,1)}</td><td>${num(x.air_humidity,1)}</td><td>${num(x.ec,2)}</td><td>${num(x.ph,2)}</td><td>${num(x.flow_rate,1)}</td><td><span class="badge ${o.kind==='observed'?'approved':'info'}">${esc(o.label)}</span></td></tr>`}).join('')||'<tr><td colspan="9" class="empty">Đang chờ dữ liệu cảm biến. Kiểm tra Data Simulator/MQTT nếu trạng thái này kéo dài.</td></tr>';
}

function drawFarmerSeries(items,metric){
  const c=$('#farmerTrend'); if(!c)return; const ctx=c.getContext('2d'),w=c.width,h=c.height,pL=58,pR=22,pT=24,pB=42;
  ctx.clearRect(0,0,w,h); ctx.font='12px Segoe UI';
  if(!items.length){ctx.fillStyle='#6a7d74';ctx.fillText('Chưa có dữ liệu trong khoảng thời gian này.',pL,55);$('#trendLegend').textContent='Chưa có dữ liệu';return;}
  const vals=items.map(x=>Number(x.avg_value)).filter(Number.isFinite),mn=Math.min(...vals),mx=Math.max(...vals),pad=Math.max((mx-mn)*.12,.1),lo=mn-pad,hi=mx+pad,range=Math.max(.001,hi-lo);
  ctx.strokeStyle='#e3ebe6';ctx.lineWidth=1;ctx.fillStyle='#718279';
  for(let i=0;i<5;i++){const y=pT+(h-pT-pB)*i/4;ctx.beginPath();ctx.moveTo(pL,y);ctx.lineTo(w-pR,y);ctx.stroke();const v=hi-range*i/4;ctx.fillText(v.toFixed(metric==='ec'||metric==='ph'?2:1),8,y+4)}
  const points=items.map((x,i)=>({x:pL+(w-pL-pR)*i/Math.max(1,items.length-1),y:pT+(h-pT-pB)*(hi-Number(x.avg_value))/range}));
  const grad=ctx.createLinearGradient(0,pT,0,h-pB);grad.addColorStop(0,'rgba(13,138,82,.20)');grad.addColorStop(1,'rgba(13,138,82,0)');ctx.beginPath();points.forEach((pt,i)=>i?ctx.lineTo(pt.x,pt.y):ctx.moveTo(pt.x,pt.y));ctx.lineTo(points.at(-1).x,h-pB);ctx.lineTo(points[0].x,h-pB);ctx.closePath();ctx.fillStyle=grad;ctx.fill();
  ctx.beginPath();points.forEach((pt,i)=>i?ctx.lineTo(pt.x,pt.y):ctx.moveTo(pt.x,pt.y));ctx.strokeStyle='#0d8a52';ctx.lineWidth=3;ctx.stroke();
  ctx.fillStyle='#64766d';ctx.fillText(new Date(items[0].bucket).toLocaleTimeString('vi-VN',{hour:'2-digit',minute:'2-digit'}),pL,h-15);const t2=new Date(items.at(-1).bucket).toLocaleTimeString('vi-VN',{hour:'2-digit',minute:'2-digit'});ctx.fillText(t2,w-pR-50,h-15);
  $('#trendLegend').textContent=`${metricLabel(metric)} • Min ${mn.toFixed(2)} • Max ${mx.toFixed(2)} ${metricUnit(metric)}`;
  $('#lastSync').textContent=`Cập nhật ${new Date().toLocaleTimeString('vi-VN')}`;
}

async function loadFarmerTrend(){
  if(state.page!=='overview')return; const metric=$('#trendMetric')?.value||'soil_moisture',hours=$('#trendHours')?.value||'1'; const bucket=hours==='1'?30:hours==='6'?180:600;
  const d=await api(`/api/farm/studio/series?farm_id=${encodeURIComponent(state.farmId)}&metric=${encodeURIComponent(metric)}&hours=${hours}&bucket_seconds=${bucket}`); drawFarmerSeries(d.items||[],metric);
}

async function refreshFarmerRealtime(){
  if(state.page!=='overview')return;
  const [d,sim,telemetry]=await Promise.all([
    api(`/api/farm/studio/grid?farm_id=${encodeURIComponent(state.farmId)}&minutes=60&limit=120`),
    api('/api/simulator/health').catch(err=>({status:'down',last_error:err.message})),
    api('/api/telemetry/health').catch(err=>({status:'down',connected:false,last_error:err.message}))
  ]);
  const rows=d.items||[],pipe=realtimePipelineState(sim,telemetry,rows),origin=dataOriginInfo(rows);
  const configs={soil_moisture:['%',1],temperature:['°C',1],air_humidity:['%',1],ec:['mS/cm',2],ph:['',2],flow_rate:['L/phút',1]};
  Object.entries(configs).forEach(([key,[unit,digits]])=>{const el=document.querySelector(`[data-live-key="${key}"]`);if(el){const v=latestValue(rows,key);el.textContent=v===null?'—':`${num(v,digits)}${unit?' '+unit:''}`}});
  if($('#farmerRealtimeBody'))$('#farmerRealtimeBody').innerHTML=farmerRowsHtml(rows);
  if($('#rowFreshBadge'))$('#rowFreshBadge').textContent=`${rows.length} mẫu gần đây`;
  if($('#farmerLiveText'))$('#farmerLiveText').textContent=pipe.ok?`Đồng bộ ${new Date().toLocaleTimeString('vi-VN')}`:pipe.label;
  if($('#farmerRealtimeTitle'))$('#farmerRealtimeTitle').textContent=pipe.title;
  if($('#farmerRealtimeHint'))$('#farmerRealtimeHint').textContent=pipe.hint;
  if($('#dataOriginLabel'))$('#dataOriginLabel').textContent=origin.label;
  if($('#dataOriginDetail'))$('#dataOriginDetail').textContent=origin.detail;
  await loadFarmerTrend();
}

async function farmerAiInsights() {
  setPageMeta('Gợi ý từ AI','PHÂN TÍCH DỰA TRÊN DỮ LIỆU VƯỜN');
  const data=await api(`/api/chatbot/farm/ai-dashboard?farm_id=${encodeURIComponent(state.farmId)}`);
  const summary=data.summary, top=summary.top_recommendation||{};
  const modelCount=data.models?.total||0;
  $('#content').innerHTML=`
    <div class="metrics">
      <div class="metric"><small>Mô hình đã huấn luyện</small><strong>${modelCount}</strong></div>
      <div class="metric"><small>Khu được phân tích</small><strong>${summary.zone_results?.length||0}</strong></div>
      <div class="metric"><small>Cần người kiểm tra</small><strong>${summary.human_required_count||0}</strong></div>
      <div class="metric"><small>Dữ liệu cập nhật</small><strong>15 giây</strong></div>
    </div>
    <div class="grid-2 ai-grid">
      <section class="panel"><div class="panel-head"><div><h3>Biểu đồ và dự báo 24 giờ</h3><p class="muted">Dữ liệu vườn có provenance + ngưỡng mục tiêu + dự báo ngắn hạn + điểm bất thường.</p></div><button id="askChart" class="secondary">Yêu cầu biểu đồ khác</button></div>
        <img class="ai-chart standalone" src="data:${esc(data.chart.mime_type||'image/png')};base64,${data.chart.base64}" alt="${esc(data.chart.title||'Biểu đồ AI')}">
        <a class="secondary download-chart" download="${esc(data.chart.filename||'nextfarm-chart.png')}" href="data:${esc(data.chart.mime_type||'image/png')};base64,${data.chart.base64}">Tải biểu đồ PNG</a>
      </section>
      <section class="panel"><h3>Đánh giá thông minh</h3><div class="ai-insight ${esc(top.severity||'info')}"><b>${esc(top.title||'AI đang theo dõi')}</b><p>${esc(top.summary||'Chưa có bất thường nghiêm trọng.')}</p>${Array.isArray(top.actions)?`<ul>${top.actions.map(a=>`<li>${esc(a)}</li>`).join('')}</ul>`:''}</div>
        <h3>Phạm vi AI tự xử lý</h3><ul>${(summary.ai_scope?.can_handle||[]).map(x=>`<li>${esc(x)}</li>`).join('')}</ul>
        <h3>Chỉ chuyển kỹ thuật viên khi</h3><ul>${(summary.ai_scope?.requires_human||[]).map(x=>`<li>${esc(x)}</li>`).join('')}</ul>
      </section>
    </div>
    <section class="panel"><h3>Phân tích từng khu</h3><div class="insight-cards">${(summary.zone_results||[]).map(r=>{const rec=r.recommendation||{}, mdl=r.model||{};return `<div class="insight-card"><span class="badge ${esc(rec.severity||'info')}">Khu ${esc(r.zone_code||'-')}</span><h4>${esc(rec.title||'Đang học')}</h4><p>${esc(rec.summary||'')}</p><small>${mdl.ready?`Học từ ${mdl.sample_count} mẫu · Tin cậy ${Math.round((mdl.confidence||0)*100)}% · Dự báo ${mdl.forecast_value} ${esc(r.unit||'')}`:'Đang thu thập dữ liệu'}</small></div>`}).join('')}</div></section>`;
  $('#askChart').addEventListener('click',()=>{renderPage('chat'); setTimeout(()=>{$('#chatInput').value='Vẽ biểu đồ độ ẩm khu A 24 giờ';$('#chatInput').focus();},50);});
}

async function farmerChat() {
  setPageMeta('Chat AI hỗ trợ vườn','FUNCTION CALLING / TOOL USE');
  let storageNote='Lịch sử được lưu trong PostgreSQL và tự khôi phục sau khi mở lại máy.';
  if(state.chatFarmId!==state.farmId){
    const history=await api(`/api/chatbot/conversations/current/messages?farm_id=${encodeURIComponent(state.farmId)}&limit=300`);
    state.chatMessages=(history.items||[]).map(m=>({role:m.role,text:m.text,createdAt:m.created_at,persistence:{saved:true,store:'postgresql'}}));
    state.chatFarmId=state.farmId;
    storageNote=history.storage?.warning||storageNote;
  }
  const initial = state.chatMessages.length ? '' : `<div class="bubble bot">Xin chào ${esc(state.user.display_name)}. Tôi chỉ trả lời bằng dữ liệu vườn có ghi rõ nguồn hoặc tài liệu đã kiểm duyệt. Khi dữ liệu thiếu/trễ, tôi sẽ nói rõ và không đoán.</div>`;
  $('#content').innerHTML=`<div class="chat-layout">
    <section class="chat-panel"><div id="messages" class="messages">${initial}</div><form id="chatForm" class="chat-send"><input id="chatInput" placeholder="Ví dụ: Độ ẩm khu A giờ bao nhiêu?" required/><button class="primary">Gửi</button></form></section>
    <aside class="panel"><div class="ai-insight info"><b>Lưu chat bền vững</b><p>${esc(storageNote)}</p></div><h3>Câu hỏi demo</h3><div class="quick-list" id="quickList"></div><hr><p class="muted">Chatbot không điều khiển van/bơm trong phạm vi PoC này.</p></aside>
  </div>`;
  const msgs=$('#messages');
  state.chatMessages.forEach(m=>msgs.insertAdjacentHTML('beforeend',bubbleHtml(m)));
  const qs=['Phân tích tình hình vườn','Vẽ biểu đồ độ ẩm khu A 24 giờ','Dự báo độ ẩm khu A 30 phút tới','Độ ẩm khu A giờ bao nhiêu?','Thiết bị có online không?','Có cảnh báo gì không?','Tôi muốn gặp kỹ thuật viên'];
  $('#quickList').innerHTML=qs.map(q=>`<button type="button" data-q="${esc(q)}">${esc(q)}</button>`).join('');
  document.querySelectorAll('#quickList button').forEach(b=>b.addEventListener('click',()=>sendChat(b.dataset.q)));
  $('#chatForm').addEventListener('submit',e=>{e.preventDefault();sendChat($('#chatInput').value);});
}
function bubbleHtml(m) {
  const visual=m.visualization?.base64?`<div class="ai-visual"><h4>${esc(m.visualization.title||'Biểu đồ AI')}</h4><img class="ai-chart" src="data:${esc(m.visualization.mime_type||'image/png')};base64,${m.visualization.base64}" alt="${esc(m.visualization.title||'Biểu đồ phân tích dữ liệu vườn')}"><a class="secondary download-chart" download="${esc(m.visualization.filename||'nextfarm-chart.png')}" href="data:${esc(m.visualization.mime_type||'image/png')};base64,${m.visualization.base64}">Tải biểu đồ PNG</a></div>`:'';
  const insight=m.insights?`<div class="ai-insight ${esc(m.insights.severity||'info')}"><b>${esc(m.insights.title||'Đánh giá AI')}</b><p>${esc(m.insights.summary||'')}</p>${Array.isArray(m.insights.actions)?`<ul>${m.insights.actions.map(a=>`<li>${esc(a)}</li>`).join('')}</ul>`:''}<small>Quyết định: ${m.insights.decision==='human_required'?'Cần kỹ thuật viên':m.insights.decision==='ai_can_handle'?'AI tiếp tục xử lý':'Theo dõi thêm'}</small></div>`:'';
  const sourceHtml=m.source?`<small>Nguồn: ${m.source.source_url?`<a href="${esc(m.source.source_url)}" target="_blank" rel="noopener noreferrer">${esc(m.source.title||m.source.source_name||'Nguồn đã kiểm duyệt')}</a>`:esc(m.source.title||m.source.source_name||'Nội bộ')}</small>`:'';
  const verifyHtml=m.verification?`<small class="verify ${m.verification.allowed?'ok':'blocked'}">${m.verification.allowed?'Đã qua Truth Guard':'Truth Guard đã chặn nội dung thiếu căn cứ'}</small>`:'';
  const persistenceHtml=m.persistence?`<small class="verify ${m.persistence.saved?'ok':'blocked'}">${m.persistence.saved?'Đã lưu PostgreSQL':'Cảnh báo: câu trả lời chưa lưu được'}</small>`:'';
  return `<div class="bubble ${m.role}">${esc(m.text)}${sourceHtml}${verifyHtml}${persistenceHtml}${visual}${insight}${m.ticket?`<div class="ticket-action"><button class="primary create-ticket" data-payload='${esc(JSON.stringify(m.ticket.payload))}'>${esc(m.ticket.label)}</button></div>`:''}</div>`;
}
async function sendChat(text) {
  if(!text.trim()) return;
  const clientMessageId=(crypto.randomUUID?crypto.randomUUID():`web-${Date.now()}-${Math.random().toString(16).slice(2)}`);
  const pending={role:'user',text,persistence:null};state.chatMessages.push(pending);
  $('#messages').insertAdjacentHTML('beforeend',bubbleHtml(pending)); $('#chatInput').value='';
  $('#messages').insertAdjacentHTML('beforeend','<div id="thinking" class="bubble bot">Đang kiểm tra dữ liệu...</div>');
  try {
    const data=await api('/api/chatbot/chat',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({message:text,farm_id:state.farmId,client_message_id:clientMessageId})});
    pending.persistence={saved:true,store:'postgresql'};
    $('#thinking').remove(); const m={role:'bot',text:data.answer,source:data.source,ticket:data.ticket_suggestion,visualization:data.visualization,insights:data.insights,verification:data.verification,persistence:data.persistence}; state.chatMessages.push(m); $('#messages').insertAdjacentHTML('beforeend',bubbleHtml(m)); bindTicketButtons();
  } catch(err) { $('#thinking').textContent=err.message; }
  $('#messages').scrollTop=$('#messages').scrollHeight;
}
function bindTicketButtons() {
  document.querySelectorAll('.create-ticket').forEach(btn=>{ if(btn.dataset.bound)return; btn.dataset.bound='1'; btn.addEventListener('click',async()=>{
    try{const payload=JSON.parse(btn.dataset.payload); const t=await api('/api/chatbot/tickets/confirm',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload)}); btn.outerHTML=`<b>Đã tạo ${esc(t.ticket_id)}</b>`;toast('Đã gửi ticket cho kỹ thuật viên.');}catch(e){toast(e.message);}
  }); });
}

async function ticketList(isTech) {
  setPageMeta(isTech?'Ticket hỗ trợ':'Yêu cầu hỗ trợ',isTech?'ƯU TIÊN RÕ • TRẠNG THÁI RÕ • THAO TÁC NHANH':'THEO DÕI TIẾN ĐỘ HỖ TRỢ');
  const data=await api('/api/tickets/tickets');
  const items=data.items||[];
  if(isTech){
    const counts={open:items.filter(x=>['open','reopened'].includes(x.status)).length,in_progress:items.filter(x=>x.status==='in_progress').length,urgent:items.filter(x=>x.priority==='urgent'&&!['resolved','closed'].includes(x.status)).length,resolved:items.filter(x=>['resolved','closed'].includes(x.status)).length};
    $('#content').innerHTML=`<div class="metrics"><div class="metric"><small>Đang chờ</small><strong>${counts.open}</strong></div><div class="metric"><small>Đang xử lý</small><strong>${counts.in_progress}</strong></div><div class="metric"><small>Khẩn cấp</small><strong>${counts.urgent}</strong></div><div class="metric"><small>Đã hoàn tất</small><strong>${counts.resolved}</strong></div></div>
    <section class="panel"><div class="panel-head"><div><h3>Hàng đợi xử lý</h3><p class="muted">${esc(data.queue_rule||'Ưu tiên cao trước, FIFO trong cùng mức.')}</p></div><span class="badge approved">${items.length} ticket</span></div><div class="table-wrap"><table class="table"><thead><tr><th>Mã</th><th>Người gửi / vườn</th><th>Vấn đề</th><th>Ưu tiên</th><th>Trạng thái</th><th>Tạo lúc</th></tr></thead><tbody>${items.map(t=>`<tr class="row-link" data-id="${esc(t.ticket_id)}"><td><b>${esc(t.ticket_id)}</b></td><td><b>${esc(t.requester_name)}</b><br><small>${esc(t.farm_name)}</small></td><td>${esc(t.title)}</td><td><span class="badge ${esc(t.priority)}">${priorityText(t.priority)}</span></td><td class="status-${esc(t.status)}"><b>${statusText(t.status)}</b></td><td>${time(t.created_at)}</td></tr>`).join('')||'<tr><td colspan="6" class="empty">Không có ticket.</td></tr>'}</tbody></table></div></section>`;
  } else {
    $('#content').innerHTML=`<section class="panel"><div class="panel-head"><div><h3>Các yêu cầu bạn đã gửi</h3><p class="muted">Bạn có thể mở từng yêu cầu để xem phản hồi của kỹ thuật viên.</p></div><button id="goChatTicket" class="primary">Tạo yêu cầu qua Chat AI</button></div><div class="table-wrap"><table class="table"><thead><tr><th>Mã</th><th>Nội dung</th><th>Mức độ</th><th>Trạng thái</th><th>Thời gian</th></tr></thead><tbody>${items.map(t=>`<tr class="row-link" data-id="${esc(t.ticket_id)}"><td><b>${esc(t.ticket_id)}</b></td><td>${esc(t.title)}</td><td><span class="badge ${esc(t.priority)}">${priorityText(t.priority)}</span></td><td class="status-${esc(t.status)}"><b>${statusText(t.status)}</b></td><td>${time(t.created_at)}</td></tr>`).join('')||'<tr><td colspan="5" class="empty">Bạn chưa có yêu cầu hỗ trợ.</td></tr>'}</tbody></table></div></section>`;
  }
  document.querySelectorAll('.row-link').forEach(r=>r.addEventListener('click',()=>ticketDetail(r.dataset.id,isTech)));
  if($('#goChatTicket')) $('#goChatTicket').addEventListener('click',()=>renderPage('chat'));
}

async function ticketDetail(id,isTech) {
  loading(); const data=await api(`/api/tickets/tickets/${encodeURIComponent(id)}`); const t=data.ticket;
  setPageMeta(t.ticket_id, isTech?'CHI TIẾT XỬ LÝ TICKET':'TRAO ĐỔI HỖ TRỢ');
  $('#content').innerHTML=`<div class="ticket-detail">
    <section class="panel"><div class="panel-head"><div><span class="badge ${esc(t.priority)}">${priorityText(t.priority)}</span><h3>${esc(t.title)}</h3><p>${esc(t.requester_name)} · ${esc(t.farm_name)} ${t.zone_code?'· Khu '+esc(t.zone_code):''}</p></div><button id="backTickets" class="ghost">Quay lại</button></div>
      <div id="thread" class="thread">${data.messages.map(m=>`<div class="thread-msg ${esc(m.message_type)}"><b>${esc(m.display_name)}</b><small> · ${time(m.created_at)}</small><p>${esc(m.content)}</p></div>`).join('')}</div>
      <form id="messageForm"><label>Phản hồi<textarea id="messageText" rows="3" required></textarea></label>${isTech?'<label class="check-item"><input id="warningType" type="checkbox"> Gửi dưới dạng cảnh báo</label>':''}<button class="primary">Gửi phản hồi</button></form>
    </section>
    <aside class="panel"><h3>Thông tin xử lý</h3><p><b>Trạng thái:</b> ${statusText(t.status)}</p><p><b>Loại lỗi:</b> ${esc(t.category)}</p><p><b>Kỹ thuật viên:</b> ${esc(t.assigned_name||'Chưa tiếp nhận')}</p>
      ${isTech&&t.status==='open'?'<button id="acceptBtn" class="primary">Tiếp nhận ticket</button>':''}
      <h3>Checklist</h3><div id="checklist">${data.checklist.map(i=>`<label class="check-item"><input type="checkbox" data-item="${esc(i.checklist_item_id)}" ${i.completed?'checked':''} ${!isTech?'disabled':''}><span>${esc(i.instruction)}</span></label>`).join('')||'<p class="muted">Chưa có checklist.</p>'}</div>
      ${isTech&& !['resolved','closed'].includes(t.status)?`<h3>Hoàn tất xử lý</h3><form id="resolveForm"><label>Nguyên nhân gốc<textarea id="rootCause" rows="2" required></textarea></label><label>Cách xử lý<textarea id="resolution" rows="3" required></textarea></label><label class="check-item"><input id="reusable" type="checkbox"> Đưa vào kho tri thức</label><button class="primary">Đánh dấu đã giải quyết</button></form>`:''}
      ${data.resolution?`<div class="alert-card"><h4>Kết quả xử lý</h4><p><b>Nguyên nhân:</b> ${esc(data.resolution.root_cause)}</p><p><b>Giải pháp:</b> ${esc(data.resolution.resolution)}</p></div>`:''}
      ${isTech?`<h3>Ca tương tự</h3>${data.similar_cases.map(c=>`<div class="alert-card"><b>${esc(c.title)}</b><p>${esc(c.resolution)}</p></div>`).join('')||'<p class="muted">Chưa có ca tương tự.</p>'}`:''}
    </aside></div>`;
  $('#backTickets').addEventListener('click',()=>ticketList(isTech));
  $('#messageForm').addEventListener('submit',async e=>{e.preventDefault();await api(`/api/tickets/tickets/${id}/messages`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({content:$('#messageText').value,message_type:$('#warningType')?.checked?'warning':'message'})});toast('Đã gửi phản hồi.');ticketDetail(id,isTech);});
  if($('#acceptBtn')) $('#acceptBtn').addEventListener('click',async()=>{await api(`/api/tickets/tickets/${id}/accept`,{method:'POST'});toast('Đã tiếp nhận ticket.');ticketDetail(id,isTech);});
  document.querySelectorAll('#checklist input[data-item]').forEach(c=>c.addEventListener('change',async()=>{await api(`/api/tickets/tickets/${id}/checklist/${c.dataset.item}`,{method:'PATCH',headers:{'Content-Type':'application/json'},body:JSON.stringify({completed:c.checked})});toast('Đã cập nhật checklist.');}));
  if($('#resolveForm')) $('#resolveForm').addEventListener('submit',async e=>{e.preventDefault();await api(`/api/tickets/tickets/${id}/resolve`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({root_cause:$('#rootCause').value,resolution:$('#resolution').value,reusable_for_knowledge:$('#reusable').checked})});toast('Đã giải quyết ticket.');ticketDetail(id,isTech);});
}


async function farmerKnowledge() {
  setPageMeta('Hướng dẫn & tài liệu','NỘI DUNG ĐÃ ĐƯỢC KIỂM DUYỆT');
  const [health,sources,articles]=await Promise.all([
    api('/api/knowledge/health'),api('/api/knowledge/sources'),api('/api/knowledge/articles')
  ]);
  $('#content').innerHTML=`
    <div class="metrics">
      <div class="metric"><small>Tài liệu đã duyệt</small><strong>${health.approved_documents}</strong></div>
      <div class="metric"><small>Hồ sơ cây trồng</small><strong>${health.reviewed_crop_profiles}</strong></div>
      <div class="metric"><small>Nguồn tin cậy</small><strong>${sources.total}</strong></div>
      <div class="metric"><small>Cách trả lời</small><strong class="metric-text">Có dẫn nguồn</strong></div>
    </div>
    <div class="grid-2">
      <section class="panel"><div class="panel-head"><div><h3>Nguồn đang sử dụng</h3><p class="muted">Chỉ tài liệu đã duyệt mới được chatbot dùng trả lời.</p></div></div>
        ${sources.items.map(src=>`<div class="source-card"><span class="badge info">Tier ${src.trust_tier}</span><b>${esc(src.source_name)}</b><p>${esc(src.usage_note||'')}</p><a href="${esc(src.source_url)}" target="_blank" rel="noopener noreferrer">Mở nguồn</a></div>`).join('')}
      </section>
      <section class="panel"><h3>Tài liệu đã kiểm duyệt</h3>
        ${articles.items.map(doc=>`<div class="source-card"><b>${esc(doc.title)}</b><p>${esc(doc.category)}</p><a href="${esc(doc.source_url)}" target="_blank" rel="noopener noreferrer">${esc(doc.source_name)}</a></div>`).join('')}
      </section>
    </div>
    <section class="panel"><h3>Hỏi AI bằng tài liệu đã kiểm duyệt</h3><p>Vào Chat AI và hỏi: <b>“Vườn tôi đang trồng cà chua, mùa tới nên trồng cây gì phù hợp?”</b></p><p class="muted">Bot sẽ đọc dữ liệu vườn, xếp hạng mức phù hợp, dẫn nguồn và từ chối khẳng định năng suất/lợi nhuận khi thiếu dữ liệu thị trường.</p><button id="goKnowledgeChat" class="primary">Mở Chat AI</button></section>`;
  $('#goKnowledgeChat').addEventListener('click',()=>renderPage('chat'));
}

async function farmerNotifications() {
  setPageMeta('Cảnh báo từ kỹ thuật viên','THÔNG BÁO CHỦ ĐỘNG');
  const data=await api('/api/tickets/notifications');
  $('#content').innerHTML=`<section class="panel"><h3>Danh sách cảnh báo</h3>${data.items.map(n=>`<div class="alert-card ${esc(n.severity)}"><span class="badge ${esc(n.severity)}">${esc(n.severity)}</span><h4>${esc(n.title)}</h4><p>${esc(n.message)}</p><small>${esc(n.created_by_name||'Kỹ thuật viên')} · ${time(n.created_at)}</small></div>`).join('')||'<div class="empty">Chưa có cảnh báo.</div>'}</section>`;
}

async function techDashboard() {
  setPageMeta('Trung tâm vận hành','SUPPORTOPS • TICKET • KNOWLEDGE');
  const [d,k]=await Promise.all([api('/api/tickets/dashboard'),api('/api/knowledge/studio/stats')]),m=d.metrics,g=k.production_gate||{};
  const maxCat=Math.max(1,...(d.categories||[]).map(x=>Number(x.total||0)));
  $('#content').innerHTML=`
    <section class="ops-hero"><div><p class="eyebrow light">BÀN LÀM VIỆC KỸ THUẬT VIÊN</p><h3>Ưu tiên việc cần xử lý, không để người dùng phải tìm.</h3><p>Ticket khẩn cấp, tình trạng kho tri thức và thao tác cảnh báo nằm trong cùng một luồng.</p></div><div class="ops-actions"><button data-go="queue">Mở hàng đợi</button><button data-go="techknowledge">Quản lý tri thức</button><button data-go="notify">Gửi cảnh báo</button><a href="http://localhost:8081" target="_blank">Data Studio</a></div></section>
    <div class="metrics"><div class="metric"><small>Ticket đang chờ</small><strong>${m.open_count}</strong><span class="metric-sub">theo ưu tiên + FIFO</span></div><div class="metric"><small>Đang xử lý</small><strong>${m.in_progress_count}</strong><span class="metric-sub">đã có kỹ thuật viên tiếp nhận</span></div><div class="metric"><small>Khẩn cấp</small><strong>${m.urgent_count}</strong><span class="metric-sub">cần phản hồi trước</span></div><div class="metric"><small>Tài liệu đã duyệt</small><strong>${k.approved}</strong><span class="metric-sub">${k.drafts} bản nháp chờ kiểm tra</span></div></div>
    <div class="grid-2"><section class="panel"><div class="panel-head"><div><h3>Việc cần xử lý trước</h3><p class="muted">Hàng đợi ưu tiên cao trước, FIFO trong cùng mức.</p></div><button class="secondary" data-go="queue">Xem tất cả</button></div><div class="queue-cards">${(d.queue||[]).slice(0,7).map((t,i)=>`<div class="queue-card" data-ticket="${esc(t.ticket_id)}"><span class="queue-rank">${i+1}</span><div class="queue-main"><b>${esc(t.title)}</b><small>${esc(t.requester_name)} • ${esc(t.farm_name)} • ${time(t.created_at)}</small></div><span class="badge ${esc(t.priority)}">${priorityText(t.priority)}</span></div>`).join('')||'<div class="empty">Không có ticket đang chờ.</div>'}</div></section>
    <section class="panel"><div class="panel-head"><div><h3>Sức khỏe kho tri thức</h3><p class="muted">Chỉ tài liệu đã duyệt được chatbot sử dụng.</p></div><button class="secondary" data-go="techknowledge">Mở quản lý</button></div><div class="knowledge-gate ${g.ready?'ready':''}"><b>${g.ready?'Đủ điều kiện production gate':'Kho tri thức chưa đạt production gate'}</b><p>${esc((g.gaps||[]).join(' • ')||'Đã đủ ngưỡng tối thiểu')}</p></div><div class="status-list"><div class="status-item"><strong>Nguồn</strong><span>${k.sources}</span></div><div class="status-item"><strong>Tài liệu</strong><span>${k.total}</span></div><div class="status-item"><strong>Bản nháp chờ duyệt</strong><span>${k.drafts}</span></div><div class="status-item"><strong>Chunks</strong><span>${k.chunks}</span></div></div></section></div>
    <div class="grid-2" style="margin-top:16px"><section class="panel"><h3>Nhóm vấn đề đang gặp</h3>${(d.categories||[]).map(c=>`<div class="progress-row"><span>${esc(c.category)}</span><div class="progress-track"><i style="width:${Math.round(Number(c.total||0)/maxCat*100)}%"></i></div><b>${c.total}</b></div>`).join('')||'<div class="empty">Chưa có dữ liệu ticket.</div>'}</section><section class="panel"><h3>Hiệu suất hỗ trợ</h3><div class="status-list"><div class="status-item"><strong>Phản hồi đầu tiên trung bình</strong><span>${m.avg_first_response_minutes??'—'} phút</span></div><div class="status-item"><strong>Thời gian giải quyết trung bình</strong><span>${m.avg_resolution_minutes??'—'} phút</span></div><div class="status-item"><strong>Tổng ticket lịch sử</strong><span>${m.total}</span></div></div></section></div>`;
  document.querySelectorAll('[data-go]').forEach(x=>x.addEventListener('click',()=>renderPage(x.dataset.go)));
  document.querySelectorAll('[data-ticket]').forEach(x=>x.addEventListener('click',()=>ticketDetail(x.dataset.ticket,true)));
}

async function technicianKnowledge() {
  setPageMeta('Quản lý kho tri thức','DUYỆT NGUỒN • KIỂM SOÁT NỘI DUNG • RAG');
  const [stats,docs]=await Promise.all([api('/api/knowledge/studio/stats'),api('/api/knowledge/studio/documents?approved=all')]),g=stats.production_gate||{};
  $('#content').innerHTML=`<div class="metrics"><div class="metric"><small>Nguồn tin cậy</small><strong>${stats.sources}</strong></div><div class="metric"><small>Tài liệu</small><strong>${stats.total}</strong></div><div class="metric"><small>Đã duyệt</small><strong>${stats.approved}</strong></div><div class="metric"><small>Bản nháp</small><strong>${stats.drafts}</strong></div></div>
  <div class="knowledge-tools"><section class="knowledge-gate ${g.ready?'ready':''}"><b>${g.ready?'Production gate: ĐẠT':'Production gate: CHƯA ĐẠT'}</b><p>${esc((g.gaps||[]).join(' • ')||'Kho đã đạt ngưỡng tối thiểu.')}</p></section><section class="panel"><b>Knowledge Studio chuyên sâu</b><p class="muted">Có thể mở giao diện độc lập khi cần kiểm tra dài.</p><a class="secondary" href="http://localhost:8082" target="_blank" style="display:inline-flex;text-decoration:none">Mở :8082</a></section></div>
  <section class="panel" style="margin-top:16px"><div class="panel-head"><div><h3>Nhập nguồn web mới</h3><p class="muted">Tài liệu mới luôn ở trạng thái bản nháp trước khi được duyệt.</p></div></div><form id="techIngestForm" class="form-row"><label>URL HTTPS<input id="techIngestUrl" placeholder="https://..." required></label><label>Tên nguồn<input id="techSourceName" placeholder="Tên nguồn (không bắt buộc)"></label><label>Nhóm tài liệu<select id="techCategory"><option>NEXTFARM_PRODUCT</option><option>SENSOR_KNOWLEDGE</option><option>CROP_GUIDE</option><option>WEB_RESEARCH</option></select></label><div style="display:flex;align-items:end"><button class="primary" style="width:100%;margin-bottom:12px">Tải thành bản nháp</button></div></form><p id="techIngestResult" class="muted"></p></section>
  <div class="knowledge-grid" style="margin-top:16px"><aside class="panel"><div class="panel-head"><div><h3>Tài liệu</h3><p class="muted">Chọn một tài liệu để đọc và duyệt.</p></div><select id="techDocFilter" style="width:auto;margin:0"><option value="all">Tất cả</option><option value="false">Bản nháp</option><option value="true">Đã duyệt</option></select></div><div id="techDocList" class="doc-list">${techDocListHtml(docs.items||[])}</div></aside><section id="techDocDetail" class="panel doc-detail"><div class="empty">Chọn một tài liệu bên trái để xem nội dung và nguồn.</div></section></div>`;
  bindTechDocs();
  $('#techDocFilter').addEventListener('change',async()=>{const d=await api('/api/knowledge/studio/documents?approved='+encodeURIComponent($('#techDocFilter').value));$('#techDocList').innerHTML=techDocListHtml(d.items||[]);bindTechDocs();});
  $('#techIngestForm').addEventListener('submit',async e=>{e.preventDefault();const out=$('#techIngestResult');out.textContent='Đang tải và tách tài liệu...';try{const x=await api('/api/knowledge/studio/ingest-url',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({url:$('#techIngestUrl').value,source_name:$('#techSourceName').value||null,category:$('#techCategory').value})});out.textContent=`Đã tạo bản nháp ${x.document_id}. Hãy đọc nội dung trước khi duyệt.`;toast('Đã nhập tài liệu thành bản nháp.');await technicianKnowledge();await openTechKnowledgeDoc(x.document_id);}catch(err){out.textContent=err.message;}});
}

function techDocListHtml(items){return items.map(x=>`<div class="doc-item" data-doc="${esc(x.document_id)}"><b>${esc(x.title)}</b><small>${esc(x.source_name)} • Tier ${Number(x.trust_tier)} • ${Number(x.chunk_count)} mục</small><span class="badge ${x.approved?'approved':'draft'}" style="margin-top:7px">${x.approved?'Đã duyệt':'Bản nháp'}</span></div>`).join('')||'<div class="empty">Không có tài liệu trong bộ lọc này.</div>';}
function bindTechDocs(){document.querySelectorAll('[data-doc]').forEach(x=>x.addEventListener('click',()=>openTechKnowledgeDoc(x.dataset.doc)));}
async function openTechKnowledgeDoc(id){
  const d=await api('/api/knowledge/studio/documents/'+encodeURIComponent(id));state.selectedKnowledgeDoc=d;document.querySelectorAll('[data-doc]').forEach(x=>x.classList.toggle('active',x.dataset.doc===id));const u=safeUrl(d.source_url);
  $('#techDocDetail').innerHTML=`<div class="panel-head"><div><span class="badge ${d.approved?'approved':'draft'}">${d.approved?'Đã duyệt':'Bản nháp'}</span><h3 style="margin-top:9px">${esc(d.title)}</h3><p class="muted">${esc(d.source_name)} • Trust tier ${Number(d.trust_tier)} • cập nhật ${time(d.updated_at)}</p></div>${d.approved?'':`<button id="techApproveDoc" class="primary">Duyệt tài liệu</button>`}</div><p><a href="${esc(u)}" target="_blank" rel="noopener noreferrer">${esc(d.source_url)}</a></p>${(d.chunks||[]).map((c,i)=>`<article class="chunk-card"><small class="muted">Mục ${i+1} • ${esc(c.section_path||'Nội dung')}</small><h4>${esc(c.heading||d.title)}</h4><p>${esc(c.content_vi)}</p></article>`).join('')}`;
  if($('#techApproveDoc'))$('#techApproveDoc').addEventListener('click',async()=>{await api('/api/knowledge/admin/documents/'+encodeURIComponent(id)+'/approve',{method:'POST'});toast('Đã duyệt tài liệu.');await technicianKnowledge();await openTechKnowledgeDoc(id);});
}

async function notificationForm() {
  setPageMeta('Gửi cảnh báo cho nông dân','KỸ THUẬT VIÊN CHỦ ĐỘNG THÔNG BÁO');
  const farmers=await api('/api/identity/support/farmers');
  $('#content').innerHTML=`<section class="panel" style="max-width:760px"><h3>Tạo cảnh báo</h3><form id="notifyForm"><label>Người nhận<select id="recipient">${farmers.items.map(f=>`<option value="${esc(f.user_id)}" data-farm="${esc(f.farm_id)}">${esc(f.display_name)} · ${esc(f.farm_name)}</option>`).join('')}</select></label><label>Mức độ<select id="severity"><option value="info">Thông tin</option><option value="warning" selected>Cảnh báo</option><option value="critical">Khẩn cấp</option></select></label><label>Tiêu đề<input id="notifyTitle" required></label><label>Nội dung<textarea id="notifyMessage" rows="5" required></textarea></label><button class="primary">Gửi cảnh báo</button></form></section>`;
  $('#notifyForm').addEventListener('submit',async e=>{e.preventDefault();const opt=$('#recipient').selectedOptions[0];await api('/api/tickets/notifications',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({recipient_id:$('#recipient').value,farm_id:opt.dataset.farm,severity:$('#severity').value,title:$('#notifyTitle').value,message:$('#notifyMessage').value})});toast('Đã gửi cảnh báo cho nông dân.');$('#notifyForm').reset();});
}


async function farmerModelLab() {
  setPageMeta('Phòng thí nghiệm Train/Test AI','ĐÁNH GIÁ THẬT TRÊN TẬP TEST THEO THỜI GIAN');
  const status = await api(`/api/analytics/ml/status?farm_id=${encodeURIComponent(state.farmId)}`);
  const farm = status.farms?.[state.farmId];
  if (!farm) {
    $('#content').innerHTML=`<section class="panel"><h3>Hệ thống đang train/test</h3><p>AI đang hợp nhất dữ liệu nhiều vườn, chia train/validation/test theo thời gian và huấn luyện đúng 10 mô hình dùng chung.</p><p class="muted">Trạng thái: ${status.running?'Đang chạy':'Chưa có kết quả'}${status.last_error?` · ${esc(status.last_error)}`:''}</p><button id="refreshMl" class="primary">Tải lại trạng thái</button></section>`;
    $('#refreshMl').addEventListener('click',()=>farmerModelLab());
    return;
  }
  const report = await api(`/api/analytics/ml/reports/${encodeURIComponent(state.farmId)}`);
  let live=null; try{ live=await api(`/api/analytics/ml/predict/${encodeURIComponent(state.farmId)}?zone=A`); }catch(_e){}
  const score = m => m.task==='classification' ? m.metrics.f1_macro : m.metrics.r2;
  const decisionLabel = !live ? '' : live.decision==='human_required' ? 'Cần người kiểm tra' : live.decision==='ai_can_handle' ? 'AI approved có thể xử lý' : 'Chỉ quan sát';
  const decisionClass = !live ? 'info' : live.decision==='human_required' ? 'urgent' : live.decision==='ai_can_handle' ? 'info' : 'warning';
  $('#content').innerHTML=`
    <div class="metrics">
      <div class="metric"><small>Model dùng chung</small><strong>${report.model_count}</strong></div>
      <div class="metric"><small>Approved</small><strong>${status.approved_model_count||0}</strong></div>
      <div class="metric"><small>Experimental</small><strong>${status.experimental_model_count||0}</strong></div>
      <div class="metric"><small>Mẫu train</small><strong>${report.train_count}</strong></div>
      <div class="metric"><small>Mẫu validation/test</small><strong>${report.validation_count} / ${report.test_count}</strong></div>
      <div class="metric"><small>Production gate</small><strong>${status.production_ready?'ĐẠT':'CHƯA ĐẠT'}</strong></div>
    </div>
    <section class="panel"><div class="ai-insight ${status.production_ready?'':'warning'}"><b>${status.production_ready?'Model suite đủ điều kiện production gate hiện tại':'Model suite chưa đạt production gate'}</b><p>${status.production_ready?'Dataset đến từ DB và 10/10 model đã approved.':'Cần dataset DB và đủ 10/10 model approved; model experimental chỉ dùng để quan sát.'}</p></div></section>
    <div class="grid-2 ai-grid">
      <section class="panel">
        <div class="panel-head"><div><h3>Kết quả 10 họ mô hình dùng chung</h3><p class="muted">Một artifact phục vụ nhiều nông dân; model không vượt quality gate được ghi rõ là experimental.</p></div></div>
        <img id="suiteSummaryChart" class="ai-chart standalone" alt="Biểu đồ kết quả train test 10 mô hình">
      </section>
      <section class="panel">
        <h3>Nguyên tắc đánh giá</h3>
        <div class="ai-insight"><b>Không trộn tương lai vào quá khứ</b><p>Tập train/validation/test lần lượt là 70%/15%/15% theo thời gian, không trộn dữ liệu tương lai vào quá khứ.</p></div>
        <div class="ai-insight"><b>Biểu đồ sinh từ dự đoán thật</b><p>Mỗi họ mô hình chỉ có một model.joblib dùng chung, kèm report, biểu đồ test, đánh giá từng vườn và Leave-One-Farm-Out.</p></div>
        <div class="ai-insight warning"><b>Dataset được tạo từ PostgreSQL</b><p>V10 khóa phiên bản dataset runtime từ sensor_readings, device_status, irrigation_runs và telemetry_ingest_events; static reference được khóa riêng trước khi train bootstrap. Nhãn phân loại hiện là weak labels theo rule và vẫn cần dữ liệu sự cố đã xác nhận để đạt production.</p></div>
      </section>
    </div>
    ${live?`<section class="panel model-table-panel"><div class="panel-head"><div><h3>Suy luận thật trên dữ liệu IoT mới nhất – Khu ${esc(live.zone_code)}</h3><p class="muted">Model dùng chung đang đọc profile + snapshot IoT của vườn hiện tại. Chỉ model approved được phép quyết định cảnh báo.</p></div><span class="badge ${decisionClass}">${decisionLabel}</span></div><div class="insight-cards">${live.predictions.map(p=>`<div class="insight-card"><small>${esc(p.display_name)} · <span class="badge ${p.deployment_status==='approved'?'info':'warning'}">${p.deployment_status==='approved'?'Approved':'Experimental'}</span></small><h4>${esc(p.label)}</h4>${p.probability!=null?`<p>Độ tin cậy: ${(p.probability*100).toFixed(1)}%</p>`:''}</div>`).join('')}</div></section>`:''}
    <section class="panel model-table-panel"><h3>Chi tiết từng mô hình</h3>
      <div class="table-wrap"><table class="table"><thead><tr><th>Mô hình</th><th>Trạng thái</th><th>Loại</th><th>Điểm test chính</th><th>Số mẫu</th><th>Biểu đồ</th></tr></thead><tbody>
      ${report.models.map(m=>`<tr><td><b>${esc(m.display_name)}</b><br><small>${esc(m.description)}</small></td><td><span class="badge ${m.deployment_status==='approved'?'info':'warning'}">${m.deployment_status==='approved'?'Approved':'Experimental'}</span></td><td>${m.task==='classification'?'Phân loại':'Dự báo'}</td><td><b>${Number(score(m)).toFixed(3)}</b><br><small>${m.task==='classification'?`Accuracy ${Number(m.metrics.accuracy).toFixed(3)}`:`MAE ${Number(m.metrics.mae).toFixed(3)} · RMSE ${Number(m.metrics.rmse).toFixed(3)}`}</small></td><td>${m.train_count} / ${m.test_count}</td><td><button class="secondary view-model-chart" data-model="${esc(m.model_name)}">Xem test</button></td></tr>`).join('')}
      </tbody></table></div>
    </section>
    <section id="modelChartPanel" class="panel" hidden></section>`;
  await loadProtectedImage('#suiteSummaryChart', `/api/analytics/ml/charts/${encodeURIComponent(state.farmId)}/summary?ts=${Date.now()}`);
  document.querySelectorAll('.view-model-chart').forEach(btn=>btn.addEventListener('click',async()=>{
    const model=btn.dataset.model;
    const panel=$('#modelChartPanel'); panel.hidden=false;
    panel.innerHTML=`<div class="panel-head"><h3>Biểu đồ đánh giá: ${esc(model)}</h3></div><div class="grid-2"><div><img id="modelEvaluationChart" class="ai-chart" alt="Biểu đồ đánh giá tập test"></div><div><img id="modelImportanceChart" class="ai-chart" alt="Biểu đồ đặc trưng quan trọng"></div></div>`;
    await Promise.all([
      loadProtectedImage('#modelEvaluationChart', `/api/analytics/ml/charts/${encodeURIComponent(state.farmId)}/${encodeURIComponent(model)}/evaluation?ts=${Date.now()}`),
      loadProtectedImage('#modelImportanceChart', `/api/analytics/ml/charts/${encodeURIComponent(state.farmId)}/${encodeURIComponent(model)}/importance?ts=${Date.now()}`)
    ]);
    panel.scrollIntoView({behavior:'smooth'});
  }));
}

async function restoreSession(){
  if(!state.token){ showLogin(''); return; }
  try{
    state.user=await api('/api/identity/auth/me');
    const savedFarm=sessionStorage.getItem('nf_selected_farm');
    const allowed=(state.user.farms||[]).some(f=>f.farm_id===savedFarm&&f.can_read);
    state.farmId=allowed?savedFarm:state.user.default_farm_id;
    enterApp();
  }
  catch(_err){ sessionStorage.removeItem('nf_app_token'); state.token=null; showLogin('Phiên đăng nhập cũ không còn hợp lệ. Vui lòng đăng nhập lại.'); }
}
loadDemoAccounts();
restoreSession();
