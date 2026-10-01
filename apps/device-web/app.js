const $ = selector => document.querySelector(selector);
const $$ = selector => [...document.querySelectorAll(selector)];
const emptyChatTemplate = $('#messages').innerHTML;

const state = {
  token: sessionStorage.getItem('nf_device_token'),
  user: null,
  devices: [],
  farms: [],
  farm: null,
  device: null,
  zone: null,
  errorTimer: null,
};

const sensorSpecs = {
  temperature: {
    label: 'Nhiệt độ', unit: '°C', color: '#16865a',
    terms: ['nhiet do', 'bao nhieu do', 'nong hay mat', 'nong khong', 'co nong', 'nong qua'],
    low: 'Nhiệt độ thấp có thể làm quá trình sinh trưởng chậm lại.',
    good: 'Mức này thuận lợi để cây duy trì các hoạt động sinh lý bình thường.',
    high: 'Nhiệt độ cao có thể làm cây thoát hơi nước mạnh và tăng nguy cơ stress nhiệt.',
  },
  soil_moisture: {
    label: 'Độ ẩm đất', unit: '%', color: '#3983b7',
    terms: ['do am dat', 'am dat', 'dat am', 'dat kho', 'vung re kho', 'can tuoi chua'],
    low: 'Đất đang khô hơn mức cài đặt, cây có thể khó hút nước nếu tình trạng kéo dài.',
    good: 'Độ ẩm đang ở khoảng phù hợp đã cài đặt, giúp vùng rễ duy trì nước ổn định.',
    high: 'Đất ẩm hơn mức cài đặt; nếu kéo dài có thể làm rễ thiếu thoáng khí.',
  },
  air_humidity: {
    label: 'Độ ẩm không khí', unit: '%', color: '#5b7fb8',
    terms: ['do am khong khi', 'am khong khi', 'khong khi am', 'khong khi kho'],
    low: 'Không khí khô có thể làm cây thoát hơi nước nhanh hơn.',
    good: 'Mức này đang nằm trong khoảng được cấu hình cho vườn.',
    high: 'Không khí ẩm kéo dài có thể tạo điều kiện cho một số bệnh nấm phát triển.',
  },
  ec: {
    label: 'EC', unit: 'mS/cm', color: '#9d7734',
    terms: ['chi so ec', 'nong do ec', 'ec'],
    low: 'EC thấp hơn cấu hình có thể phản ánh nồng độ dinh dưỡng còn thấp.',
    good: 'EC đang trong khoảng dinh dưỡng đã cấu hình cho vườn.',
    high: 'EC cao hơn cấu hình có thể làm cây khó hút nước do nồng độ muối cao.',
  },
  ph: {
    label: 'pH', unit: '', color: '#8669a8',
    terms: ['chi so ph', 'do ph', 'ph'],
    low: 'pH thấp hơn cấu hình có thể ảnh hưởng khả năng hấp thu một số dinh dưỡng.',
    good: 'pH đang trong khoảng đã cấu hình, thuận lợi hơn cho việc hấp thu dinh dưỡng.',
    high: 'pH cao hơn cấu hình có thể làm một số dinh dưỡng khó được cây hấp thu.',
  },
  light: {
    label: 'Ánh sáng', unit: 'lux', color: '#c58b24',
    terms: ['anh sang', 'buc xa', 'par'],
    low: 'Ánh sáng thấp kéo dài có thể hạn chế quang hợp của cây.',
    good: 'Mức ánh sáng đang nằm trong khoảng cấu hình tham chiếu của vườn.',
    high: 'Ánh sáng cao đi cùng nhiệt độ cao có thể làm tăng nhu cầu nước và nguy cơ stress.',
  },
  flow_rate: {
    label: 'Lưu lượng nước', unit: 'L/phút', color: '#2b8fa6',
    terms: ['luu luong', 'nuoc chay manh', 'nuoc chay yeu'],
    low: 'Lưu lượng đang thấp hơn khoảng cấu hình.',
    good: 'Lưu lượng đang trong khoảng vận hành đã cấu hình.',
    high: 'Lưu lượng đang cao hơn khoảng cấu hình.',
  },
};

const profileLabels = {
  greenhouse: 'Nhà kính', open_field: 'Ngoài trời', net_house: 'Nhà lưới',
};

const dataGroups = [
  ['Số đo cảm biến', 'Độ ẩm đất, nhiệt độ, EC, pH và lưu lượng nước tức thời theo từng khu', 'Khoảng 10 phút'],
  ['Trạng thái thiết bị', 'Kết nối, bơm, van và từng cổng ra', 'Khoảng 5 giây'],
  ['Lịch tưới', 'Khu, van, giờ bắt đầu và thời lượng đã cấu hình', 'Theo cấu hình'],
  ['Lịch sử tưới', 'Bắt đầu, kết thúc, thời lượng, tổng lượng nước và tổng lượng phân', 'Theo sự kiện'],
  ['Nhật ký lệnh', 'Người gửi lệnh, thời điểm và kết quả', 'Theo sự kiện'],
  ['Cảnh báo', 'Mất kết nối hoặc chỉ số vượt ngưỡng', 'Theo sự kiện'],
];

const escapeHtml = value => String(value ?? '').replace(/[&<>"']/g, char => ({
  '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;',
}[char]));

function normalize(value) {
  return String(value ?? '').toLowerCase().replace(/đ/g, 'd')
    .normalize('NFD').replace(/[\u0300-\u036f]/g, '').replace(/\s+/g, ' ').trim();
}

function showError(value) {
  const element = $('#error');
  const message = value?.message || String(value || 'Đã có lỗi xảy ra.');
  clearTimeout(state.errorTimer);
  element.textContent = message;
  element.hidden = false;
  state.errorTimer = setTimeout(() => { element.hidden = true; }, 6000);
}

async function api(path, options = {}) {
  const response = await fetch(path, {
    ...options,
    headers: {
      ...(options.headers || {}),
      ...(state.token ? { Authorization: `Bearer ${state.token}` } : {}),
    },
  });
  let body;
  try { body = await response.json(); } catch { body = {}; }
  if (!response.ok) {
    const detail = typeof body.detail === 'string' ? body.detail : body.detail?.message;
    throw new Error(detail || `Không thể kết nối hệ thống (lỗi ${response.status}).`);
  }
  return body;
}

function profileOf(device) { return device?.profile && typeof device.profile === 'object' ? device.profile : {}; }

function configuredZones(device = state.device) {
  const zones = profileOf(device).zones;
  return Array.isArray(zones) ? zones.filter(zone => zone?.zone_id) : [];
}

function zoneLabel(zoneId = state.zone) {
  const configured = configuredZones().find(zone => zone.zone_id === zoneId);
  if (configured?.name) return configured.name;
  return zoneId ? zoneId.replace(/^zone_/, 'Khu ').toUpperCase() : 'Toàn vườn';
}

function questionWithContext(template) {
  return String(template || '').replaceAll('{zone}', zoneLabel());
}

function openDialog(selector) {
  const dialog = $(selector);
  if (!dialog) return;
  dialog.hidden = false;
  document.body.classList.add('dialog-open');
  requestAnimationFrame(() => dialog.querySelector('button')?.focus());
}

function closeDialogs() {
  $$('.modal-backdrop').forEach(dialog => { dialog.hidden = true; });
  document.body.classList.remove('dialog-open');
}

function renderZoneOptions() {
  const options = $('#zoneOptions');
  options.replaceChildren();
  const zones = configuredZones();
  if (!zones.length) {
    options.innerHTML = '<p class="empty-profile">Hồ sơ vườn chưa khai báo khu canh tác.</p>';
    return;
  }
  for (const zone of zones) {
    const button = document.createElement('button');
    button.type = 'button';
    button.className = `zone-option${zone.zone_id === state.zone ? ' active' : ''}`;
    const details = [zone.area_m2 ? `${zone.area_m2} m²` : 'Chưa khai báo diện tích', zone.valve_port != null ? `Van ${zone.valve_port}` : 'Chưa gắn van'];
    button.innerHTML = `<span class="zone-option-mark">${zone.zone_id === state.zone ? '✓' : '○'}</span><span><strong>${escapeHtml(zone.name || zoneLabel(zone.zone_id))}</strong><small>${escapeHtml(details.join(' · '))}</small></span><span>›</span>`;
    button.addEventListener('click', () => setZone(zone.zone_id, true));
    options.append(button);
  }
}

function updateZoneContext() {
  const label = zoneLabel();
  $('#zoneName').textContent = label;
  $('#chatZoneName').textContent = label;
  $('#chatCropName').textContent = state.farm?.crop || 'Cây trồng';
  $('#message').placeholder = `Hỏi bất cứ điều gì về ${label}…`;
  renderZoneOptions();
}

function setZone(zoneId, announce = false) {
  const previous = state.zone;
  state.zone = zoneId || null;
  updateZoneContext();
  closeDialogs();
  if (announce && previous !== state.zone) appendMessage(`Đã chuyển phạm vi hỏi đáp sang ${zoneLabel()}. Từ giờ câu hỏi không ghi rõ khu sẽ dùng dữ liệu của ${zoneLabel()}.`);
  $('#message').focus();
}

function displayValue(value, suffix = '') {
  return value == null || value === '' ? 'Chưa khai báo' : `${value}${suffix}`;
}

function renderFarmProfile() {
  const profile = profileOf(state.device);
  const zones = configuredZones();
  const sensors = Array.isArray(profile.installed_sensors) ? profile.installed_sensors : [];
  const thresholds = profile.thresholds && typeof profile.thresholds === 'object' ? profile.thresholds : {};
  const sensorNames = sensors.map(metric => sensorSpecs[metric]?.label || metric);
  const thresholdRows = Object.entries(thresholds).map(([metric, bounds]) => {
    const spec = sensorSpecs[metric] || { label: metric, unit: '' };
    const range = Array.isArray(bounds) && bounds.length === 2 ? `${bounds[0]}–${bounds[1]} ${spec.unit}`.trim() : 'Chưa khai báo';
    return `<div><span>${escapeHtml(spec.label)}</span><strong>${escapeHtml(range)}</strong></div>`;
  }).join('') || '<p class="empty-profile">Chưa có ngưỡng cảm biến được khai báo.</p>';
  const zoneRows = zones.map(zone => `<div class="profile-zone"><span><strong>${escapeHtml(zone.name || zoneLabel(zone.zone_id))}</strong><small>${escapeHtml(displayValue(zone.area_m2, ' m²'))}</small></span><span>${escapeHtml(zone.valve_port != null ? `Van ${zone.valve_port}` : 'Chưa gắn van')}</span></div>`).join('') || '<p class="empty-profile">Chưa khai báo khu canh tác.</p>';
  const groupRows = dataGroups.map(([name, detail, cadence]) => `<tr><th>${escapeHtml(name)}</th><td>${escapeHtml(detail)}</td><td>${escapeHtml(cadence)}</td></tr>`).join('');
  $('#farmProfileContent').innerHTML = `
    <div class="profile-summary">
      <div><span>Vườn</span><strong>${escapeHtml(state.farm?.name || farmDisplayName(state.device))}</strong></div>
      <div><span>Cây trồng</span><strong>${escapeHtml(profile.crop || 'Chưa khai báo')}</strong></div>
      <div><span>Số khu</span><strong>${zones.length || 'Chưa khai báo'}</strong></div>
      <div><span>Hình thức</span><strong>${escapeHtml(profileLabels[profile.profile_type] || profile.profile_type || 'Chưa khai báo')}</strong></div>
      <div><span>Diện tích vườn</span><strong>${escapeHtml(displayValue(profile.area_m2, ' m²'))}</strong></div>
      <div><span>Thiết bị</span><strong>${escapeHtml(profile.model || 'Chưa khai báo')}</strong></div>
    </div>
    <div class="profile-columns">
      <section><h3>Các khu canh tác</h3><div class="profile-zones">${zoneRows}</div></section>
      <section><h3>Cảm biến đã khai báo</h3><p class="sensor-list">${sensorNames.length ? sensorNames.map(name => `<span>${escapeHtml(name)}</span>`).join('') : 'Chưa khai báo cảm biến.'}</p><h3>Khoảng ngưỡng tham chiếu</h3><div class="threshold-list">${thresholdRows}</div><p class="profile-caution">Các ngưỡng là cấu hình tham chiếu. Số đo có sai số và cần được đánh giá theo nhiều mốc liên tiếp, giống cây và giai đoạn sinh trưởng.</p></section>
    </div>
    <section class="profile-data-groups"><h3>Dữ liệu trợ lý có thể đọc</h3><div class="profile-table-wrap"><table><thead><tr><th>Nhóm</th><th>Nội dung</th><th>Cập nhật</th></tr></thead><tbody>${groupRows}</tbody></table></div></section>`;
}

function farmDisplayName(device) {
  const profile = profileOf(device);
  if (profile.farm_name) return profile.farm_name;
  if (profile.crop) return `Vườn ${profile.crop}`;
  const cleaned = String(device?.device_name || '').replace(/^tủ\s+/i, '').replace(/\s+(long|lan|minh)$/i, '').trim();
  return cleaned ? `Vườn ${cleaned}` : 'Vườn của tôi';
}

function groupFarms(devices) {
  const grouped = new Map();
  for (const device of devices) {
    const key = device.farm_id || device.device_id;
    if (!grouped.has(key)) grouped.set(key, { id: key, devices: [], primary: device });
    grouped.get(key).devices.push(device);
  }
  return [...grouped.values()].map(farm => ({
    ...farm,
    name: farmDisplayName(farm.primary),
    crop: profileOf(farm.primary).crop || 'Cây trồng chưa khai báo',
  }));
}

function renderFarmChoices() {
  const grid = $('#farmGrid');
  grid.replaceChildren();
  for (const farm of state.farms) {
    const button = document.createElement('button');
    button.type = 'button';
    button.className = 'farm-choice';
    button.innerHTML = `<span class="farm-choice-icon">⌁</span><span><strong>${escapeHtml(farm.name)}</strong><small>${escapeHtml(farm.crop)}</small></span><span>→</span>`;
    button.addEventListener('click', () => selectFarm(farm));
    grid.append(button);
  }
}

function resetMessages() {
  $('#messages').innerHTML = emptyChatTemplate;
  const displayName = state.user?.display_name || 'bạn';
  const firstName = displayName.trim().split(/\s+/).slice(-1)[0] || 'bạn';
  const name = $('#farmerName');
  if (name) name.textContent = firstName.toUpperCase();
}

function hideEmptyChat() {
  const empty = $('#emptyChat');
  if (empty) empty.hidden = true;
}

function scrollMessages() {
  const messages = $('#messages');
  requestAnimationFrame(() => { messages.scrollTop = messages.scrollHeight; });
}

function humanizeAnswer(value) {
  return String(value ?? '')
    .replace(/^(?:Tủ đang chọn|Vườn đang xem):\s*[^\n]+\.\s*/i, '')
    .replace(/tủ đang chọn/gi, 'vườn đang xem')
    .replace(/tủ đã chọn/gi, 'vườn đang xem')
    .replace(/tủ này/gi, 'vườn này')
    .replace(/cho tủ/gi, 'cho vườn')
    .replace(/Tủ chưa có/gi, 'Vườn chưa có')
    .replace(/Tủ còn gửi trạng thái/gi, 'Hệ thống của vườn vẫn đang kết nối')
    .replace(/trạng thái tủ/gi, 'trạng thái hệ thống')
    .replace(/Ngưỡng chưa được chuyên gia xác nhận theo cây, đất và giai đoạn sinh trưởng; chưa kết luận mức này phù hợp cho cây hay đề xuất tưới\./gi, 'Đây là đánh giá theo ngưỡng cấu hình tham chiếu; chưa thay thế tư vấn chuyên gia theo giống cây và giai đoạn sinh trưởng.')
    .replace(/Xem bảng 10 model để biết lý do;?\s*/gi, '')
    .replace(/Các model dự báo riêng chỉ dùng khi vượt kiểm định trong phạm vi đã công bố\./gi, 'Các chức năng dự báo chỉ được sử dụng khi đã đủ độ tin cậy.')
    .replace(/\n\nNguồn: dữ liệu mô phỏng, chưa phải số đo ngoài thực địa\.?/gi, '')
    .trim();
}

function structuredAnswerHtml(value) {
  const clean = humanizeAnswer(value);
  const lines = clean.split(/\n+/).map(x => x.trim()).filter(Boolean);
  if (lines.length > 1) return lines.map((line, index) => `<div class="answer-line${index === 0 ? ' answer-lead' : ''}">${escapeHtml(line)}</div>`).join('');
  // Keep long evidence responses scannable without inventing or changing data.
  const parts = clean.split(/(?<=[.!?])\s+(?=[A-ZÀ-Ỵ])/u).map(x => x.trim()).filter(Boolean);
  if (parts.length >= 3) return parts.map((part, index) => `<div class="answer-line${index === 0 ? ' answer-lead' : ''}">${escapeHtml(part)}</div>`).join('');
  return `<div class="answer-line answer-lead">${escapeHtml(clean)}</div>`;
}

function appendMessage(text, { user = false, chatId = null, loading = false } = {}) {
  hideEmptyChat();
  const row = document.createElement('div');
  row.className = `message-row ${user ? 'user' : 'assistant'}${loading ? ' typing' : ''}`;
  if (!user) {
    const avatar = document.createElement('span');
    avatar.className = 'mini-avatar';
    avatar.textContent = 'N';
    row.append(avatar);
  }

  const column = document.createElement('div');
  column.className = 'message-column';
  const bubble = document.createElement('div');
  bubble.className = 'bubble';
  if (loading) {
    bubble.innerHTML = '<span class="typing-dots" aria-label="Trợ lý đang tìm số liệu"><i></i><i></i><i></i></span>';
  } else {
    const clean = user ? String(text) : humanizeAnswer(text);
    const sourceIndex = clean.lastIndexOf('\n\nNguồn:');
    const answer = document.createElement('div');
    answer.className = user ? 'plain-message' : 'structured-answer';
    answer.innerHTML = user ? escapeHtml(sourceIndex >= 0 ? clean.slice(0, sourceIndex) : clean) : structuredAnswerHtml(sourceIndex >= 0 ? clean.slice(0, sourceIndex) : clean);
    bubble.append(answer);
    if (!user && sourceIndex >= 0) {
      const source = document.createElement('p');
      source.className = 'source-line';
      source.textContent = clean.slice(sourceIndex + 2);
      bubble.append(source);
    }
  }
  column.append(bubble);

  if (!user && chatId) {
    const feedback = document.createElement('div');
    feedback.className = 'feedback-row';
    for (const [label, useful] of [['Hữu ích', true], ['Chưa đúng ý', false]]) {
      const button = document.createElement('button');
      button.type = 'button';
      button.textContent = label;
      button.addEventListener('click', async () => {
        try {
          await api('/api/chatbot/feedback', {
            method: 'POST', headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ chat_id: chatId, useful }),
          });
          feedback.className = 'feedback-thanks';
          feedback.textContent = 'Cảm ơn bạn, NextFarm đã ghi nhận.';
        } catch (error) { showError(error); }
      });
      feedback.append(button);
    }
    column.append(feedback);
  }

  row.append(column);
  $('#messages').append(row);
  scrollMessages();
  return { row, column };
}

function detectedMetrics(question) {
  const text = normalize(question);
  const found = [];
  for (const [metric, spec] of Object.entries(sensorSpecs)) {
    const searchable = metric === 'soil_moisture'
      ? text.replace(/\b(do am khong khi|am khong khi|khong khi am|khong khi kho)\b/g, '')
      : text;
    if (spec.terms.some(term => new RegExp(`(^|\\s)${term.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')}(?=\\s|$|[?,.])`).test(searchable))) found.push(metric);
  }
  return found;
}

function sensorQuestionMode(question) {
  const text = normalize(question);
  const forecast = /\b(du bao|sap toi|gio toi|tieng toi|phut toi|ngay mai|se bien dong|se tang|se giam|nguy co)\b/.test(text)
    || /\b(sau|trong)\s+\d+\s*(phut|gio|tieng|h)\b/.test(text);
  if (forecast) return 'forecast';
  const history = /\b(qua|gan day|truoc day|lich su|xu huong|bien dong|tang hay giam|cao nhat|thap nhat|trung binh|so sanh)\b/.test(text)
    || /\b\d+\s*(phut|gio|tieng|h|ngay)\s+(qua|gan day|truoc)\b/.test(text)
    || /\b(hom nay|hom qua|tuan nay|tuan truoc|thang nay|thang truoc)\b/.test(text);
  return history ? 'history' : 'current';
}

function historyWindowHours(question) {
  const text = normalize(question);
  const hours = text.match(/\b(\d+)\s*(?:gio|tieng|h)\s+(?:qua|gan day|truoc)\b/);
  if (hours) return Math.max(1, Math.min(2160, Number(hours[1])));
  const days = text.match(/\b(\d+)\s*ngay\s+(?:qua|gan day|truoc)\b/);
  if (days) return Math.max(1, Math.min(2160, Number(days[1]) * 24));
  if (/\b(tuan nay|tuan truoc)\b/.test(text)) return 168;
  if (/\b(thang nay|thang truoc)\b/.test(text)) return 720;
  if (/\b(hom nay|hom qua)\b/.test(text)) return 24;
  return 2;
}

function questionZone(question) {
  const match = normalize(question).match(/\bkhu\s+([a-z0-9]+)\b/);
  return match && !['nao', 'vuc', 'vuon'].includes(match[1]) ? `zone_${match[1]}` : null;
}

function validReading(row, metric) {
  const value = Number(row?.[metric]);
  const stamp = Date.parse(row?.observed_at);
  return Number.isFinite(value) && Number.isFinite(stamp) && !['bad', 'suspect'].includes(row?.quality);
}

async function loadInsight(metric, question, windowHours) {
  const response = await api(`/api/farm/devices/${encodeURIComponent(state.device.device_id)}/data?group=sensor_readings&period=hours:${windowHours}`);
  const zone = questionZone(question) || state.zone;
  let rows = (response.items || []).filter(row => validReading(row, metric));
  if (zone) rows = rows.filter(row => row.zone_id === zone);
  if (!zone) {
    const zones = [...new Set(rows.map(row => row.zone_id).filter(Boolean))];
    if (zones.length > 1) rows = rows.filter(row => row.zone_id === zones[0]);
  }
  rows.sort((a, b) => Date.parse(a.observed_at) - Date.parse(b.observed_at));
  if (!rows.length) throw new Error(`Chưa có chuỗi ${sensorSpecs[metric].label.toLowerCase()} hợp lệ để vẽ biểu đồ.`);

  const latestStamp = Date.parse(rows.at(-1).observed_at);
  const now = Date.now();
  const isStale = now - latestStamp > 30 * 60 * 1000;
  const windowEnd = isStale ? latestStamp : now;
  const windowStart = windowEnd - windowHours * 60 * 60 * 1000;
  const points = rows.filter(row => Date.parse(row.observed_at) >= windowStart && Date.parse(row.observed_at) <= windowEnd + 30000);
  if (!points.length) throw new Error(`Chưa có số đo ${sensorSpecs[metric].label.toLowerCase()} trong ${windowHours} giờ được hỏi.`);

  const values = points.map(row => Number(row[metric]));
  const profile = profileOf(state.device);
  const bounds = Array.isArray(profile.thresholds?.[metric]) && profile.thresholds[metric].length === 2
    ? profile.thresholds[metric].map(Number) : null;
  return {
    metric, points, values, bounds, isStale, windowHours,
    current: values.at(-1), min: Math.min(...values), max: Math.max(...values),
    average: values.reduce((sum, value) => sum + value, 0) / values.length,
    change: values.at(-1) - values[0],
    crop: profile.crop || 'cây trồng',
    approved: profile.agronomy_approved === true,
    source: response.source || state.device.data_origin || '',
    zoneName: points.at(-1).zone_id ? points.at(-1).zone_id.replace(/^zone_/, 'Khu ').toUpperCase() : '',
  };
}

function fixed(value, metric) {
  const digits = ['temperature', 'soil_moisture', 'air_humidity'].includes(metric) ? 1 : 2;
  return Number(value).toFixed(digits);
}

function insightAssessment(insight) {
  const { current, bounds, metric } = insight;
  if (!bounds || bounds.some(value => !Number.isFinite(value))) return { key: 'unknown', label: 'Chưa có ngưỡng', message: `Biểu đồ cho thấy diễn biến thực đo. Vườn chưa cấu hình ngưỡng ${sensorSpecs[metric].label.toLowerCase()} nên trợ lý chưa xếp mức cao hay thấp.` };
  if (current < bounds[0]) return { key: 'low', label: 'Thấp hơn ngưỡng', message: sensorSpecs[metric].low };
  if (current > bounds[1]) return { key: 'high', label: 'Cao hơn ngưỡng', message: sensorSpecs[metric].high };
  return { key: 'good', label: 'Trong ngưỡng phù hợp', message: sensorSpecs[metric].good };
}

function chartMarkup(insight) {
  const { points, values, bounds, metric } = insight;
  const width = 760, height = 220, left = 48, right = 18, top = 20, bottom = 35;
  const candidates = [...values, ...(bounds || [])].filter(Number.isFinite);
  let low = Math.min(...candidates), high = Math.max(...candidates);
  const baseSpan = Math.max(high - low, metric === 'ph' ? .5 : metric === 'ec' ? .3 : 2);
  low -= baseSpan * .18; high += baseSpan * .18;
  const x = index => left + (points.length === 1 ? (width - left - right) / 2 : index * (width - left - right) / (points.length - 1));
  const y = value => top + (high - value) * (height - top - bottom) / (high - low);
  const line = points.map((point, index) => `${index ? 'L' : 'M'}${x(index).toFixed(1)},${y(Number(point[metric])).toFixed(1)}`).join(' ');
  const area = `${line} L${x(points.length - 1).toFixed(1)},${height - bottom} L${x(0).toFixed(1)},${height - bottom} Z`;
  const id = `chartFill-${metric}-${Math.random().toString(36).slice(2, 8)}`;
  const time = stamp => new Intl.DateTimeFormat('vi-VN', { hour: '2-digit', minute: '2-digit' }).format(new Date(stamp));
  const labelIndexes = [...new Set([0, Math.floor((points.length - 1) / 2), points.length - 1])];
  let band = '';
  if (bounds && bounds.every(Number.isFinite)) {
    const yTop = y(Math.max(...bounds)), yBottom = y(Math.min(...bounds));
    band = `<rect class="chart-band" x="${left}" y="${yTop.toFixed(1)}" width="${width - left - right}" height="${Math.max(1, yBottom - yTop).toFixed(1)}" rx="4"/><text class="chart-threshold-label" x="${left + 7}" y="${Math.max(top + 10, yTop + 12).toFixed(1)}">Khoảng phù hợp đã cấu hình</text>`;
  }
  const grids = [0, .5, 1].map(ratio => {
    const yy = top + ratio * (height - top - bottom);
    const value = high - ratio * (high - low);
    return `<line class="chart-grid" x1="${left}" y1="${yy.toFixed(1)}" x2="${width - right}" y2="${yy.toFixed(1)}"/><text class="chart-label" x="4" y="${(yy + 3).toFixed(1)}">${fixed(value, metric)}</text>`;
  }).join('');
  const times = labelIndexes.map(index => `<text class="chart-label" text-anchor="${index === 0 ? 'start' : index === points.length - 1 ? 'end' : 'middle'}" x="${x(index).toFixed(1)}" y="${height - 9}">${escapeHtml(time(points[index].observed_at))}</text>`).join('');
  return `<svg viewBox="0 0 ${width} ${height}" role="img" aria-label="Biểu đồ ${escapeHtml(sensorSpecs[metric].label.toLowerCase())} trong ${insight.windowHours} giờ">
    <defs><linearGradient id="${id}" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="${sensorSpecs[metric].color}" stop-opacity=".24"/><stop offset="1" stop-color="${sensorSpecs[metric].color}" stop-opacity="0"/></linearGradient></defs>
    ${grids}${band}<path class="chart-area" style="fill:url(#${id})" d="${area}"/><path class="chart-line" style="stroke:${sensorSpecs[metric].color}" d="${line}"/>
    <circle class="chart-dot" style="stroke:${sensorSpecs[metric].color}" cx="${x(points.length - 1).toFixed(1)}" cy="${y(values.at(-1)).toFixed(1)}" r="5"/>${times}
  </svg>`;
}

function appendInsight(column, insight) {
  const spec = sensorSpecs[insight.metric];
  const assessment = insightAssessment(insight);
  const trendThreshold = Math.max(Math.abs(insight.average) * .01, insight.metric === 'ph' ? .05 : .2);
  const trend = Math.abs(insight.change) < trendThreshold ? 'Ổn định' : insight.change > 0 ? `Tăng ${fixed(Math.abs(insight.change), insight.metric)} ${spec.unit}` : `Giảm ${fixed(Math.abs(insight.change), insight.metric)} ${spec.unit}`;
  const rangeText = insight.bounds ? `${fixed(insight.bounds[0], insight.metric)}–${fixed(insight.bounds[1], insight.metric)} ${spec.unit}` : 'Chưa cấu hình';
  const freshness = insight.isStale ? `Dữ liệu đã trễ; đây là ${insight.windowHours} giờ gần nhất có số đo.` : `Biểu đồ dùng số đo trong ${insight.windowHours} giờ được hỏi.`;
  const approval = insight.approved
    ? `Ngưỡng đã xác nhận cho ${insight.crop}.`
    : `Ngưỡng đang là cấu hình tham chiếu cho ${insight.crop}, chưa thay thế tư vấn của chuyên gia theo giai đoạn cây.`;
  const card = document.createElement('section');
  card.className = 'insight-card';
  card.innerHTML = `
    <div class="insight-top">
      <div><p class="insight-kicker">${escapeHtml(spec.label)} · ${insight.windowHours} GIỜ ĐƯỢC HỎI${insight.zoneName ? ` · ${escapeHtml(insight.zoneName)}` : ''}</p><div class="insight-value"><strong>${fixed(insight.current, insight.metric)}</strong><span>${escapeHtml(spec.unit)}</span></div></div>
      <span class="status-pill ${assessment.key}">${escapeHtml(assessment.label)}</span>
    </div>
    <div class="chart-shell">${chartMarkup(insight)}</div>
    <div class="insight-stats">
      <div class="insight-stat"><span>Thấp nhất</span><strong>${fixed(insight.min, insight.metric)} ${escapeHtml(spec.unit)}</strong></div>
      <div class="insight-stat"><span>Trung bình</span><strong>${fixed(insight.average, insight.metric)} ${escapeHtml(spec.unit)}</strong></div>
      <div class="insight-stat"><span>Xu hướng</span><strong>${escapeHtml(trend)}</strong></div>
    </div>
    <div class="insight-analysis"><span>✦</span><p><strong>Hiểu nhanh:</strong> ${escapeHtml(assessment.message)} Ngưỡng tham chiếu: ${escapeHtml(rangeText)}.<small>${escapeHtml(freshness)} ${escapeHtml(approval)}</small></p></div>
    <p class="measurement-caution">Số đo cảm biến luôn có sai số. Nhận xét cao/thấp dựa trên khoảng ngưỡng đã cấu hình và chuỗi số đo gần đây, không phải kết luận tuyệt đối từ một điểm đo.</p>`;
  column.append(card);
  scrollMessages();
}

function appendInsightError(column, error) {
  const note = document.createElement('div');
  note.className = 'insight-error';
  note.textContent = error?.message || 'Chưa thể tải biểu đồ lúc này.';
  column.append(note);
}

async function loadConversation() {
  resetMessages();
  try {
    const history = await api(`/api/chatbot/conversations/current/messages?device_id=${encodeURIComponent(state.device.device_id)}`);
    for (const message of history.items || []) {
      appendMessage(message.question, { user: true });
      appendMessage(message.answer, { chatId: message.id });
    }
  } catch (error) { showError(error); }
}

async function selectFarm(farm) {
  state.farm = farm;
  state.device = farm.primary;
  const configuredZone = profileOf(state.device).zones?.[0] || null;
  state.zone = configuredZone?.zone_id || null;
  $('#farmChooser').hidden = true;
  $('#workspace').hidden = false;
  $('#activeFarmName').textContent = farm.name;
  $('#farmName').textContent = farm.name;
  $('#cropName').textContent = farm.crop;
  updateZoneContext();
  renderFarmProfile();
  $('#farmSwitcher').hidden = state.farms.length < 2;
  const isDemo = /synthetic|simulated|demo/i.test(String(state.device.data_origin || ''));
  $('#demoNotice').hidden = !isDemo;
  await loadConversation();
  $('#message').focus();
}

async function enter() {
  const result = await api('/api/farm/devices');
  state.devices = result.items || [];
  state.user = result.user || {};
  $('#login').hidden = true;
  $('#logout').hidden = false;

  if (state.user.role === 'technician') {
    $('#technician').hidden = false;
    $('#technicianName').textContent = state.user.display_name || 'kỹ thuật viên';
    return;
  }

  state.farms = groupFarms(state.devices);
  if (!state.farms.length) throw new Error('Tài khoản chưa được gắn với vườn nào. Hãy liên hệ kỹ thuật viên.');
  renderFarmChoices();
  if (state.farms.length === 1) await selectFarm(state.farms[0]);
  else $('#farmChooser').hidden = false;
}

$('#loginForm').addEventListener('submit', async event => {
  event.preventDefault();
  const button = event.currentTarget.querySelector('button');
  button.disabled = true;
  try {
    const result = await api('/api/identity/auth/login', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ username: $('#username').value.trim(), password: $('#password').value }),
    });
    state.token = result.access_token;
    sessionStorage.setItem('nf_device_token', state.token);
    $('#password').value = '';
    await enter();
  } catch (error) { showError(error); }
  finally { button.disabled = false; }
});

$('#logout').addEventListener('click', () => {
  sessionStorage.removeItem('nf_device_token');
  location.reload();
});

$('#farmSwitcher').addEventListener('click', () => {
  if (state.farms.length < 2) return;
  $('#workspace').hidden = true;
  $('#farmChooser').hidden = false;
});

document.addEventListener('click', event => {
  const suggestion = event.target.closest('[data-q-template]');
  if (!suggestion || !state.device) return;
  if (suggestion.closest('#questionSuggestions')) {
    window.openGardenData([...document.querySelectorAll('#questionSuggestions button')].indexOf(suggestion));
    return;
  }
  $('#message').value = questionWithContext(suggestion.dataset.qTemplate);
  $('#message').dispatchEvent(new Event('input'));
  $('#chatForm').requestSubmit();
});

$('#zoneSelector').addEventListener('click', () => { renderZoneOptions(); openDialog('#zoneDialog'); });
$('#chatZoneSelector').addEventListener('click', () => { renderZoneOptions(); openDialog('#zoneDialog'); });
$('#farmProfileToggle').addEventListener('click', () => { renderFarmProfile(); openDialog('#farmProfileDialog'); });
$('#chatProfileToggle').addEventListener('click', () => { renderFarmProfile(); openDialog('#farmProfileDialog'); });
$$('[data-close-dialog]').forEach(button => button.addEventListener('click', closeDialogs));
$$('.modal-backdrop').forEach(backdrop => backdrop.addEventListener('click', event => { if (event.target === backdrop) closeDialogs(); }));
document.addEventListener('keydown', event => { if (event.key === 'Escape') closeDialogs(); });

$('#message').addEventListener('input', event => {
  event.target.style.height = 'auto';
  event.target.style.height = `${Math.min(event.target.scrollHeight, 140)}px`;
});

$('#message').addEventListener('keydown', event => {
  if (event.key === 'Enter' && !event.shiftKey) {
    event.preventDefault();
    $('#chatForm').requestSubmit();
  }
});

$('#clearChat').addEventListener('click', scrollMessages);

$('#chatForm').addEventListener('submit', async event => {
  event.preventDefault();
  if (!state.device) return showError('Hãy chọn vườn trước khi đặt câu hỏi.');
  const message = $('#message').value.trim();
  if (!message) return;

  const send = $('#send');
  send.disabled = true;
  appendMessage(message, { user: true });
  $('#message').value = '';
  $('#message').style.height = 'auto';
  const typing = appendMessage('', { loading: true });
  const sensorMode = sensorQuestionMode(message);
  const windowHours = historyWindowHours(message);
  const insightRequests = sensorMode === 'history'
    ? detectedMetrics(message).map(metric => ({ metric, promise: loadInsight(metric, message, windowHours) }))
    : [];

  try {
    const result = await api('/api/chatbot/chat', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ device_id: state.device.device_id, zone_id: state.zone, message }),
    });
    typing.row.remove();
    const response = appendMessage(result.answer, { chatId: result.chat_id });
    for (const request of insightRequests) {
      try { appendInsight(response.column, await request.promise); }
      catch (error) { appendInsightError(response.column, error); }
    }
  } catch (error) {
    typing.row.remove();
    appendMessage('Mình chưa thể lấy số liệu lúc này. Bạn thử lại sau ít phút nhé.');
    showError(error);
  } finally {
    send.disabled = false;
    $('#message').focus();
  }
});

if (state.token) {
  enter().catch(error => {
    sessionStorage.removeItem('nf_device_token');
    state.token = null;
    $('#login').hidden = false;
    $('#logout').hidden = true;
    showError(error);
  });
}
