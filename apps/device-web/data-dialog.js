/* Read-only garden data. Shares authentication and device scope with chat. */
(() => {
  const groups=['sensor_readings','device_status','irrigation_schedules','irrigation_runs','irrigation_runs','control_commands','alerts'];
  const names=['Số đo cảm biến','Trạng thái thiết bị','Lịch tưới','Lịch sử tưới','Châm phân','Nhật ký lệnh','Cảnh báo'];
  const metrics=['temperature','soil_moisture','air_humidity','ec','ph','flow_rate'];
  let active=0, timer, generation=0, page=0, rows=[];
  const box=document.createElement('div'); box.className='modal-backdrop garden-data-modal'; box.hidden=true;
  box.innerHTML='<section class="dialog-card profile-dialog" role="dialog" aria-modal="true" aria-labelledby="dataTitle"><div class="dialog-head"><div><p class="eyebrow">DỮ LIỆU VƯỜN</p><h2 id="dataTitle"></h2><p id="dataScope"></p></div><button class="dialog-close" aria-label="Đóng">×</button></div><div class="data-toolbar"><label>Khoảng thời gian <select id="dataPeriod"><option value="hours:24">24 giờ qua</option><option value="today">Hôm nay</option><option value="yesterday">Hôm qua</option><option value="hours:1">1 giờ qua</option><option value="hours:6">6 giờ qua</option><option value="days:3">3 ngày qua</option><option value="days:7">7 ngày qua</option></select></label><label id="metricLabel">Chỉ số <select id="dataMetric"></select></label><button id="dataRefresh" type="button">Làm mới</button></div><p id="dataFresh" role="status"></p><div id="dataBody"></div></section>';
  document.body.append(box);
  const q=s=>box.querySelector(s), esc=escapeHtml;
  const number=v=>v==null||v===''||!Number.isFinite(Number(v))?'—':new Intl.NumberFormat('vi-VN',{maximumFractionDigits:2}).format(Number(v));
  const stamp=v=>v&&!Number.isNaN(Date.parse(v))?new Date(v).toLocaleString('vi-VN',{timeZone:'Asia/Ho_Chi_Minh'}):v||'—';
  const labels={completed:'Hoàn thành',success:'Thành công',failed:'Thất bại',interrupted:'Gián đoạn',acknowledged:'Đã xác nhận lệnh',not_acknowledged:'Chưa xác nhận',open:'Chưa xử lý',resolved:'Đã xử lý',closed:'Đã đóng',warning:'Cảnh báo',critical:'Nghiêm trọng',info:'Thông tin',start_irrigation:'Bắt đầu tưới',stop_irrigation:'Dừng tưới',open_valve:'Mở van',close_valve:'Đóng van',local_schedule:'Lịch tự động',sensor_stale:'Dữ liệu cảm biến chậm',no_flow:'Không có dòng nước'};
  const label=v=>labels[v]||v||'—';
  function close(){box.hidden=true;clearTimeout(timer);generation++;document.body.classList.remove('dialog-open');}
  q('.dialog-close').onclick=close;box.onclick=e=>{if(e.target===box)close();};document.addEventListener('keydown',e=>{if(e.key==='Escape')close();});
  const cards=items=>'<div class="profile-summary">'+items.map(([k,v])=>`<div><span>${esc(k)}</span><strong>${esc(v)}</strong></div>`).join('')+'</div>';
  function cell(value) {
    const text=String(value??'—').replace(/^zone_([a-z0-9]+)$/i,(_,z)=>'Khu '+z.toUpperCase());
    const date=text.match(/^(\d{1,2}:\d{2}(?::\d{2})?)[,\s]+(\d{1,2}\/\d{1,2}\/\d{4})$/);
    if(date)return `<span class="data-time">${esc(date[1])}</span><span class="data-date">${esc(date[2])}</span>`;
    const tone=['Hoàn thành','Thành công','Đã xác nhận lệnh','Đã xử lý','Đang bật'].includes(text)?'success':['Thất bại','Nghiêm trọng'].includes(text)?'danger':['Chưa xử lý','Cảnh báo','Gián đoạn'].includes(text)?'warning':null;
    return tone?`<span class="data-badge ${tone}">${esc(text)}</span>`:esc(text);
  }
  function table(headers,values){return '<div class="profile-table-wrap" tabindex="0" aria-label="Bảng dữ liệu; cuộn ngang để xem thêm cột"><table><thead><tr>'+headers.map(h=>`<th scope="col">${esc(h)}</th>`).join('')+'</tr></thead><tbody>'+values.map(row=>'<tr>'+row.map((v,i)=>`<td data-label="${esc(headers[i])}">${cell(v)}</td>`).join('')+'</tr>').join('')+'</tbody></table></div>';}
  function render(){
    if(!rows.length){q('#dataBody').innerHTML='<p class="empty-profile">Chưa có bản ghi trong phạm vi này. Bạn có thể đổi khoảng thời gian.</p>';return;}
    const subset=rows.slice(page*20,page*20+20);let html='';
    if(active===0){
      html=cards(metrics.map(m=>{const r=[...rows].reverse().find(r=>r[m]!=null);return [sensorSpecs[m].label,r?`${number(r[m])} ${sensorSpecs[m].unit} · ${stamp(r.observed_at)}`:'Chưa có dữ liệu'];}));
      const m=q('#dataMetric').value, points=rows.filter(r=>r[m]!=null&&Number.isFinite(Number(r[m]))&&Number.isFinite(Date.parse(r.observed_at))&&!['bad','suspect','missing'].includes(r.quality));
      if(points.length){const vals=points.map(r=>Number(r[m]));const lo=Math.min(...vals)-.1,hi=Math.max(...vals)+.1;const t0=Date.parse(points[0].observed_at),span=Math.max(1,Date.parse(points.at(-1).observed_at)-t0);const x=r=>50+(Date.parse(r.observed_at)-t0)/span*650,y=r=>190-(Number(r[m])-lo)/(hi-lo)*160;
        html+=`<h3>${esc(sensorSpecs[m].label)} (${esc(sensorSpecs[m].unit)})</h3><svg viewBox="0 0 760 230" role="img" aria-label="Các điểm đo theo thời gian" style="width:100%;background:#f6faf7"><text x="4" y="30">${esc(number(hi))}</text><text x="4" y="190">${esc(number(lo))}</text>`+points.map((r,i)=>`${i&&Date.parse(r.observed_at)-Date.parse(points[i-1].observed_at)<=900000?`<line x1="${x(points[i-1])}" y1="${y(points[i-1])}" x2="${x(r)}" y2="${y(r)}" stroke="#178157"/>`:''}<circle cx="${x(r)}" cy="${y(r)}" r="3" fill="#178157"><title>${esc(stamp(r.observed_at))}: ${esc(number(r[m]))} ${esc(sensorSpecs[m].unit)}</title></circle>`).join('')+`<text x="50" y="220">${esc(stamp(points[0].observed_at))}</text><text x="700" y="220" text-anchor="end">${esc(stamp(points.at(-1).observed_at))}</text></svg><p>${points.length} điểm đo hợp lệ. Khoảng thiếu dữ liệu được ngắt đường.</p>`;
      }else html+='<p>Chưa có điểm đo hợp lệ cho chỉ số đã chọn.</p>';
      html+=table(['Thời gian',...metrics.map(m=>sensorSpecs[m].label)],subset.map(r=>[stamp(r.observed_at),...metrics.map(m=>number(r[m]))]));
    }else if(active===1){const r=rows.at(-1),on=v=>v==null?'Chưa rõ':v?'Đang chạy / mở':'Tắt / đóng';html=cards([['Kết nối',r.online==null?'Chưa rõ':r.online?'Online':'Offline'],['Cập nhật',stamp(r.observed_at)],['Bơm nước',on(r.pump_running??r.pump_on)],['Bơm phân',on(r.fertilizer_running??r.fertilizer_pump_on)],['Lưu lượng',number(r.flow_rate??r.flow_rate_lpm)+' L/phút'],['Kênh phân',r.active_fertilizer_channel??'Chưa có thông tin'],...(r.outputs||[]).map(o=>[`Cổng ${o.port} · ${o.zone_id||o.role||''}`,on(o.running)])]);
    }else if(active===2){html=table(['Khu','Lịch','Bắt đầu','Thời lượng (phút)','Phân dự kiến (mL)','Trạng thái'],subset.map(r=>[r.zone_id,r.name,r.start_time??r.every_hours,number(r.duration_minutes),number(r.fertilizer_ml),r.enabled==null?'Chưa rõ':r.enabled?'Đang bật':'Tạm dừng']));
    }else if(active===3||active===4){html=active===4?'<p class="data-note">Lượng phân được ghi nhận trong các ca tưới.</p>':'';html+=active===4?table(['Bắt đầu','Kết thúc','Khu','Lượng phân (mL)','Kênh phân','Kết quả'],subset.map(r=>[stamp(r.started_at),stamp(r.ended_at),r.zone_id,number(r.fertilizer_ml),r.fertilizer_channel,label(r.result)])):table(['Bắt đầu','Kết thúc','Khu','Thời lượng (phút)','Nước (L)','Phân (mL)','Kênh phân','Kết quả','Lý do'],subset.map(r=>[stamp(r.started_at),stamp(r.ended_at),r.zone_id,number(r.duration_minutes),number(r.water_liters),number(r.fertilizer_ml),r.fertilizer_channel,label(r.result),r.failure_reason]));
    }else if(active===5){html=table(['Thời gian','Người gửi','Khu','Lệnh','Kết quả'],subset.map(r=>[stamp(r.requested_at||r.observed_at),label(r.requested_by),r.zone_id||'Chưa gắn khu',label(r.command),label(r.status)]));
    }else{html=table(['Thời gian','Khu','Nội dung','Mức độ','Trạng thái'],subset.map(r=>[stamp(r.observed_at),r.zone_id||'Toàn thiết bị',r.text||r.message||label(r.code),label(r.severity),label(r.status)]));}
    if(active!==1)html+=`<div class="data-toolbar"><button id="dataPrev" ${page===0?'disabled':''}>← Trước</button><span>Trang ${page+1} / ${Math.ceil(rows.length/20)} · ${rows.length} bản ghi</span><button id="dataNext" ${(page+1)*20>=rows.length?'disabled':''}>Sau →</button></div>`;
    q('#dataBody').innerHTML=html;if(q('#dataPrev')){q('#dataPrev').onclick=()=>{page--;render();};q('#dataNext').onclick=()=>{page++;render();};}
  }
  async function load(){
    clearTimeout(timer);const id=++generation,device=state.device?.device_id,zone=state.zone;
    if(!device||box.hidden)return;
    const params=new URLSearchParams({group:groups[active],period:active===1?'latest':q('#dataPeriod').value});if(zone&&[0,2,3,4,6].includes(active))params.set('zone_id',zone);
    try{const result=await api(`/api/farm/devices/${encodeURIComponent(device)}/data?${params}`);if(id!==generation||box.hidden)return;
      rows=(result.items||[]).filter(r=>!zone||active===1||r.zone_id===zone||([5,6].includes(active)&&!r.zone_id)).sort((a,b)=>Date.parse(a.observed_at||a.started_at)-Date.parse(b.observed_at||b.started_at));
      const latest=rows.at(-1)?.observed_at,age=Date.now()-Date.parse(latest);q('#dataFresh').textContent=active<2?(Number.isFinite(age)?(age>(active===1?30000:1800000)?'● Dữ liệu chậm':'● Đang cập nhật')+' · '+stamp(latest):'Chưa có mốc dữ liệu mới'):'Đã tải lúc '+stamp(new Date().toISOString());render();
    }catch(error){if(id!==generation)return;console.error(error);q('#dataFresh').textContent='Không tải được dữ liệu. Bấm Làm mới để thử lại.';q('#dataBody').textContent='';}
    if(!box.hidden&&id===generation)timer=setTimeout(load,active===1?5000:15000);
  }
  window.openGardenData=index=>{active=index;page=0;rows=[];q('#dataTitle').textContent=names[index];q('#dataScope').textContent=`${state.farm?.name||''} · ${zoneLabel()}`;q('#metricLabel').hidden=index!==0;q('#dataPeriod').parentElement.hidden=index===1;q('#dataMetric').innerHTML=metrics.map(m=>`<option value="${m}">${sensorSpecs[m].label}</option>`).join('');q('#dataBody').textContent='Đang tải dữ liệu…';box.hidden=false;document.body.classList.add('dialog-open');q('.dialog-close').focus();load();};
  q('#dataPeriod').onchange=()=>{page=0;load();};q('#dataMetric').onchange=render;q('#dataRefresh').onclick=load;
})();
