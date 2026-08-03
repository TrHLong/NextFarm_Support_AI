const API = `${location.protocol}//${location.hostname}:8000`;
const state = { subjectId: null, kind: null, farmId: null };
const $ = (s) => document.querySelector(s);
const quicks = {
  lead: [['NextFarm là gì','NextFarm là gì?'],['Vườn vải 50m2','Tôi muốn xây dựng một vườn vải 50m2 thì cần thế nào?'],['Nhà màng rau','Tôi muốn làm nhà màng trồng rau 1000m2 thì NextFarm giúp gì?'],['Tưới tự động','Tưới tự động có lợi gì?'],['Muốn demo','Tôi muốn demo hệ thống']],
  customer: [['Độ ẩm khu A','Độ ẩm khu A giờ bao nhiêu?'],['Khu B thiếu nước?','Khu B có thiếu nước không?'],['Van 2','Van số 2 đang chạy không?'],['Lịch tưới','Hôm nay tưới mấy lần?'],['Bật van 2','Bật van 2 trong 10 phút'],['EC/pH','EC/pH hiện tại ổn không?']]
};
async function api(path, options={}) { const res = await fetch(`${API}${path}`, options); if (!res.ok) throw new Error(`${res.status} ${res.statusText}`); return res.json(); }
function msg(text, role='bot') { const d=document.createElement('div'); d.className=`msg ${role}`; d.textContent=text; $('#messages').appendChild(d); $('#messages').scrollTop=$('#messages').scrollHeight; }
function renderQuick() { $('#quick').innerHTML=''; (quicks[state.kind]||quicks.lead).forEach(([label,q])=>{ const b=document.createElement('button'); b.textContent=label; b.onclick=()=>send(q); $('#quick').appendChild(b); }); }
async function resolve(fullName, phone, region, note) {
  const data = await api('/intake/resolve', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({full_name:fullName, phone, region, note})});
  state.subjectId = data.subject_id; state.kind = data.identity_kind; state.farmId = data.farm_id;
  $('#intake').hidden = true; $('#chatApp').hidden = false;
  $('#mode').textContent = data.identity_kind === 'customer' ? 'Khách hàng đã xác minh' : 'Khách mới / tư vấn';
  $('#title').textContent = data.identity_kind === 'customer' ? data.display_name : 'Tư vấn NextFarm';
  $('#subtitle').textContent = data.message;
  $('#messages').innerHTML = '';
  msg(data.identity_kind === 'customer' ? 'Em đã nhận ra vườn của anh/chị. Có thể hỏi dữ liệu vườn, thiết bị, cảnh báo hoặc kiến thức NextFarm.' : 'Anh/chị cứ hỏi tự nhiên về NextFarm hoặc mô tả vườn muốn làm. Em sẽ tư vấn theo hướng phù hợp và chỉ chuyển tư vấn viên khi anh/chị muốn.');
  renderQuick();
}
async function send(text) { if (!text.trim()) return; msg(text, 'user'); $('#message').value=''; try { const data = await api('/chat', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({subject_id:state.subjectId, message:text})}); msg(data.answer || 'Không có câu trả lời.'); } catch(e) { msg(`Không gọi được API ${API}. Kiểm tra Docker Compose.`); } }
$('#intakeForm').addEventListener('submit', e => { e.preventDefault(); resolve($('#fullName').value, $('#phone').value, $('#region').value, $('#note').value); });
$('#leadDemo').addEventListener('click', () => resolve('Khách mới - vườn vải 50m2', '0987000050', 'Chưa rõ', 'Muốn xây vườn vải 50m2'));
$('#chatForm').addEventListener('submit', e => { e.preventDefault(); send($('#message').value); });
$('#reset').addEventListener('click', () => location.reload());
