const EVENT_META = {
  plant: { label: "种植", color: "var(--event-plant)" },
  water: { label: "浇水", color: "var(--event-water)" },
  harvest: { label: "收获", color: "var(--event-harvest)" },
  theft: { label: "被偷菜", color: "var(--event-theft)" },
  raid: { label: "偷别人菜", color: "var(--event-raid)" },
  bless: { label: "祝福", color: "var(--event-bless)" },
};

const LEDGER_TYPE_LABELS = {
  seed_purchase: "买种支出",
  harvest_income: "收获入账",
  fruit_sell: "卖出果实",
  steal_income: "偷菜收入",
  theft_loss: "被偷损失",
};

const CLOCK_KIND_LABELS = {
  reset: "每日重置",
  steal: "偷菜窗口",
  weekend: "周末双倍",
  "day-night": "昼夜切换",
  mixed: "关键节点",
};

const WEEKDAY_LABELS = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"];

const WEEKLY_ROUTINE = [
  {
    id: "thu-plant",
    title: "周四 12:42 / 18:00 · 满地种 32 小时英雄作物",
    detail: "种下后只浇一次水。32 小时作物一次浇水减 8 小时，为周五晚卡周末双倍留好空间。",
  },
  {
    id: "thu-check",
    title: "周四 18:35 · 检查变异",
    detail: "没出变异词条的格子直接铲掉，换 16 小时经济作物留给周末，别浪费祝福。",
  },
  {
    id: "fri-bless",
    title: "周五 04:30-05:00 · 重置前倾泻祝福",
    detail: "每天 05:00 祝福次数重置。重置前把 30 次被祝福额度全部打给英雄作物，每次祝福都是一次变异判定。",
  },
  {
    id: "fri-water",
    title: "周五 18:00 后 · 浇水卡双倍",
    detail: "周五 18:00 周末双倍开启。之后浇水压缩，让成熟时间刚好落在双倍窗口内。",
  },
  {
    id: "fri-harvest",
    title: "周五晚 · 先收未变异，留变异吃偷",
    detail: "未变异的先收；变异作物留着让好友偷（每株 4 次）再回祝（每株 3 次），共 7 次额外变异机会，英雄变异不可被偷。",
  },
  {
    id: "stop-water",
    title: "全程 · 收获前 3 小时停水",
    detail: "水条保持低水位变异率更高；32 小时作物最后 64 分钟浇水反而会延后成熟。",
  },
  {
    id: "sun-end",
    title: "周日 24:00 前 · 清空地块",
    detail: "周末双倍周日 24:00 结束，收晚了就按单倍结算，还暴露在可偷时段。",
  },
  {
    id: "weekend-economy",
    title: "周末 · 16 小时经济作物轮种",
    detail: "双倍窗口内改种 16 小时经济作物（香蕉 / 柚子 / 西瓜 / 木瓜档），两轮正好吃满整个周末。",
  },
];

const state = {
  config: null,
  crops: [],
  mechanics: null,
  wateringRules: [],
  mutations: null,
  heroCrops: [],
  fields: [],
  wallet: null,
  ledger: [],
  raids: [],
  events: [],
  farmSummary: null,
  seedInventory: [],
  fruitsInStock: [],
  fruitsSold: [],
  fruitUnitPrices: {},
  cultivation: [],
  collection: [],
  blessing: null,
  stealQuota: null,
  clockEvents: [],
  experiences: null,
  planner: null,
  ui: {
    section: "home",
    plannerCropId: "",
    plannerSlotCount: null,
    inboundCropId: "",
    outboundCropId: "",
    farmEditorCropId: "",
    selectedSlotId: "",
    farmScopeMode: "all",
    farmScopeFieldNo: 1,
    farmScopeSlotId: "",
    farmMutationEntries: new Set(),
    statsMonth: "",
    visibleEventTypes: new Set(Object.keys(EVENT_META)),
    plannerPlans: {},
    bagTab: "seeds",
    expFilterTag: "",
    calcCropId: "",
    calcCultivationLevel: 1,
  },
};

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;");
}

function request(path, options = {}) {
  return fetch(path, {
    headers: {
      "Content-Type": "application/json",
      ...(options.headers || {}),
    },
    ...options,
  }).then(async (response) => {
    if (!response.ok) {
      const text = await response.text();
      let message = text;
      try {
        message = JSON.parse(text).message || text;
      } catch (error) { /* keep raw text */ }
      throw new Error(message || `Request failed: ${response.status}`);
    }
    return response.json();
  });
}

function formatCurrency(value) {
  return Number(value || 0).toLocaleString("zh-CN", { maximumFractionDigits: 2 });
}

function signedCurrency(value) {
  const amount = Number(value || 0);
  return `${amount > 0 ? "+" : ""}${formatCurrency(amount)}`;
}

function pad(number) {
  return String(number).padStart(2, "0");
}

function toDate(value) {
  if (!value) {
    return null;
  }
  const normalized = String(value).includes("T") ? String(value) : String(value).replace(" ", "T");
  const date = new Date(normalized);
  return Number.isNaN(date.getTime()) ? null : date;
}

function formatDateTime(value) {
  const date = toDate(value);
  if (!date) {
    return "—";
  }
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())} ${pad(date.getHours())}:${pad(date.getMinutes())}`;
}

function nowLocalInputValue() {
  const now = new Date();
  now.setSeconds(0, 0);
  return `${now.getFullYear()}-${pad(now.getMonth() + 1)}-${pad(now.getDate())}T${pad(now.getHours())}:${pad(now.getMinutes())}`;
}

function formatCountdown(ms) {
  const totalMinutes = Math.max(0, Math.round(ms / 60000));
  const days = Math.floor(totalMinutes / 1440);
  const hours = Math.floor((totalMinutes % 1440) / 60);
  const minutes = totalMinutes % 60;
  if (days) return `${days}天${hours}小时`;
  if (hours) return `${hours}小时${minutes}分`;
  return `${minutes}分钟`;
}

function formatMinuteLabel(totalMinutes) {
  const hours = Math.floor(totalMinutes / 60);
  const minutes = totalMinutes % 60;
  return `${pad(hours)}:${pad(minutes)}`;
}

function getMonthKey(value) {
  const date = toDate(value);
  if (!date) {
    return "";
  }
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}`;
}

function getGreeting() {
  const hour = new Date().getHours();
  if (hour < 6) return "凌晨好";
  if (hour < 12) return "上午好";
  if (hour < 18) return "下午好";
  return "晚上好";
}

function getISOWeekKey(date = new Date()) {
  const target = new Date(Date.UTC(date.getFullYear(), date.getMonth(), date.getDate()));
  const dayNumber = (target.getUTCDay() + 6) % 7;
  target.setUTCDate(target.getUTCDate() - dayNumber + 3);
  const firstThursday = new Date(Date.UTC(target.getUTCFullYear(), 0, 4));
  const firstDayNumber = (firstThursday.getUTCDay() + 6) % 7;
  firstThursday.setUTCDate(firstThursday.getUTCDate() - firstDayNumber + 3);
  const week = 1 + Math.round((target - firstThursday) / (7 * 24 * 3600 * 1000));
  return `${target.getUTCFullYear()}-W${pad(week)}`;
}

/* ---------------- 主题 ---------------- */

function applyTheme(theme) {
  const resolved = theme === "dark" ? "dark" : "light";
  document.documentElement.dataset.theme = resolved;
  try {
    localStorage.setItem("farm-theme", resolved);
  } catch (error) { /* ignore */ }
  const button = document.getElementById("theme-toggle");
  if (button) {
    button.textContent = resolved === "dark" ? "☀️" : "🌙";
  }
}

function resolveThemePreference(preference) {
  if (preference === "light" || preference === "dark") {
    return preference;
  }
  return window.matchMedia && window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
}

function syncThemeFromConfig() {
  const preference = state.config?.appearance?.theme || "system";
  applyTheme(resolveThemePreference(preference));
  const select = document.getElementById("appearance-theme");
  if (select) {
    select.value = preference;
  }
}

async function saveThemePreference(theme) {
  const payload = { ...(state.config || {}), appearance: { theme } };
  const response = await request("/api/settings", {
    method: "POST",
    body: JSON.stringify(payload),
  });
  state.config = response.config;
  applyTheme(theme === "system" ? resolveThemePreference("system") : theme);
}

/* ---------------- 数据落地 ---------------- */

function applyDashboard(dashboard) {
  state.config = dashboard.config;
  state.crops = dashboard.crops;
  state.mechanics = dashboard.mechanics;
  state.wateringRules = dashboard.watering_rules || [];
  state.mutations = dashboard.mutations || null;
  state.heroCrops = dashboard.hero_crops || [];
  state.fields = dashboard.fields;
  state.wallet = dashboard.wallet;
  state.ledger = dashboard.ledger;
  state.raids = dashboard.raids;
  state.events = dashboard.events;
  state.farmSummary = dashboard.farm_summary;
  state.seedInventory = dashboard.seed_inventory || [];
  state.fruitsInStock = dashboard.fruits_in_stock || [];
  state.fruitsSold = dashboard.fruits_sold || [];
  state.fruitUnitPrices = dashboard.fruit_unit_prices || {};
  state.cultivation = dashboard.cultivation || [];
  state.collection = dashboard.collection || [];
  state.blessing = dashboard.blessing || null;
  state.stealQuota = dashboard.steal_quota || null;
  state.clockEvents = dashboard.clock_events || [];
  state.experiences = dashboard.experiences || null;
}

function getAllSlots() {
  return state.fields.flatMap((field) => field.slots.map((slot) => ({ ...slot, field_no: field.field_no })));
}

function getSlotById(slotId) {
  return getAllSlots().find((slot) => slot.slot_id === slotId) || null;
}

function getSlotsByField(fieldNo) {
  return getAllSlots().filter((slot) => slot.field_no === Number(fieldNo));
}

function cropLabel(crop) {
  return `${crop.name} · ${crop.growth_label} · Lv${crop.unlock_level}`;
}

function findCropById(cropId) {
  return state.crops.find((crop) => crop.crop_id === cropId) || null;
}

function findWateringRuleByCropId(cropId) {
  const crop = findCropById(cropId);
  if (!crop) {
    return null;
  }
  return state.wateringRules.find((rule) => Number(rule.natural_minutes) === Number(crop.growth_minutes)) || null;
}

function findCropByQuery(query) {
  const text = String(query || "").trim().toLowerCase();
  if (!text) {
    return null;
  }

  const exactDisplay = state.crops.find((crop) => cropLabel(crop).toLowerCase() === text);
  if (exactDisplay) return exactDisplay;

  const exactName = state.crops.find((crop) => crop.name.toLowerCase() === text);
  if (exactName) return exactName;

  const includeName = state.crops.find((crop) => crop.name.toLowerCase().includes(text));
  if (includeName) return includeName;

  return state.crops.find((crop) => cropLabel(crop).toLowerCase().includes(text)) || null;
}

function setCropInputValue(inputId, hiddenId, cropId) {
  const input = document.getElementById(inputId);
  const hidden = document.getElementById(hiddenId);
  const crop = findCropById(cropId);
  if (!input || !hidden) {
    return;
  }
  if (!crop) {
    hidden.value = "";
    return;
  }
  input.value = cropLabel(crop);
  hidden.value = crop.crop_id;
}

function syncCropInput(inputId, hiddenId, { autoCorrect = false } = {}) {
  const input = document.getElementById(inputId);
  const hidden = document.getElementById(hiddenId);
  if (!input || !hidden) {
    return null;
  }
  const crop = findCropByQuery(input.value);
  if (!crop) {
    hidden.value = "";
    return null;
  }
  hidden.value = crop.crop_id;
  if (autoCorrect) {
    input.value = cropLabel(crop);
  }
  return crop;
}

function attachCropSearch(inputId, hiddenId, onSelect) {
  const input = document.getElementById(inputId);
  if (!input) {
    return;
  }
  const handle = (autoCorrect) => {
    const crop = syncCropInput(inputId, hiddenId, { autoCorrect });
    if (crop && typeof onSelect === "function") {
      onSelect(crop.crop_id);
    }
  };
  input.addEventListener("input", () => handle(false));
  input.addEventListener("change", () => handle(true));
  input.addEventListener("blur", () => handle(true));
}

function renderCropDatalist() {
  const datalist = document.getElementById("crop-search-datalist");
  datalist.innerHTML = state.crops.map((crop) => `<option value="${escapeHtml(cropLabel(crop))}"></option>`).join("");
}

/* ---------------- 变异 ---------------- */

function getMutationType(name) {
  return (state.mutations?.mutation_types || []).find((item) => item.name === name) || null;
}

function mutationBadgeHtml(entryName) {
  const type = getMutationType(entryName);
  const badgeClass = type ? `badge-${type.badge || "neutral"}` : "badge-neutral";
  return `<span class="badge ${badgeClass}">${escapeHtml(entryName)}</span>`;
}

function mutationBadgesHtml(slot) {
  const parts = [];
  (slot.mutation_entries || []).forEach((name) => parts.push(mutationBadgeHtml(name)));
  if (slot.hero_flag) parts.push(`<span class="badge badge-hero">防偷</span>`);
  if (slot.mutation_multiplier && slot.mutation_multiplier > 1) {
    parts.push(`<span class="badge badge-purple">×${slot.mutation_multiplier}</span>`);
  }
  return parts.join("");
}

function renderMutationOptions() {
  const container = document.getElementById("farm-mutation-options");
  if (!container) return;
  const types = state.mutations?.mutation_types || [];
  container.innerHTML = types.map((type) => {
    const active = state.ui.farmMutationEntries.has(type.name);
    return `
      <button type="button" class="exp-filter-tag ${active ? "active" : ""}" data-mutation-name="${escapeHtml(type.name)}">
        ${escapeHtml(type.name)} ×${type.multiplier}
      </button>
    `;
  }).join("") || `<span class="muted">规则文件里还没有变异词条数据。</span>`;
}

function selectedMutationMultiplier() {
  let multiplier = 1;
  state.ui.farmMutationEntries.forEach((name) => {
    const type = getMutationType(name);
    if (type) multiplier *= Number(type.multiplier || 1);
  });
  return multiplier;
}

/* ---------------- 侧栏 / 顶栏 ---------------- */

function setSection(sectionId) {
  state.ui.section = sectionId;
  document.querySelectorAll(".nav-item").forEach((button) => {
    button.classList.toggle("active", button.dataset.section === sectionId);
  });
  document.querySelectorAll(".section-panel").forEach((section) => {
    section.classList.toggle("active", section.id === `section-${sectionId}`);
  });
}

function renderSidebar() {
  const profile = document.getElementById("sidebar-profile");
  const nickname = state.config.player.nickname || "农场主";
  const blessingRules = state.blessing?.rules || {};
  const givenToday = state.blessing?.given_today ?? 0;
  profile.innerHTML = `
    <div class="profile-title">
      <div class="profile-avatar">${escapeHtml(nickname.slice(0, 1))}</div>
      <div>
        <p class="profile-name">${escapeHtml(nickname)}</p>
        <p class="profile-subtitle">等级 ${state.config.player.level}${state.config.player.game_id ? ` · ID ${escapeHtml(state.config.player.game_id)}` : ""}</p>
      </div>
    </div>
    <div class="profile-grid">
      <div class="profile-chip"><span>已开格子</span><strong>${state.config.farm.unlocked_slot_count}</strong></div>
      <div class="profile-chip"><span>小摊加成</span><strong>${state.config.player.stall_bonus_pct}%</strong></div>
      <div class="profile-chip"><span>今日祝福</span><strong>${givenToday}/${blessingRules.daily_give_limit ?? 10}</strong></div>
      <div class="profile-chip"><span>防偷窗口</span><strong>${state.config.planner.anti_theft_enabled ? `${state.config.planner.anti_theft_safe_start}-${state.config.planner.anti_theft_safe_end}` : "关闭"}</strong></div>
    </div>
  `;

  document.getElementById("sidebar-safe-window").textContent = state.config.planner.anti_theft_enabled
    ? `防偷 ${state.config.planner.anti_theft_safe_start}-${state.config.planner.anti_theft_safe_end}`
    : "防偷已关闭";
  document.getElementById("sidebar-slot-count").textContent = `已开 ${state.config.farm.unlocked_slot_count} / 48 格`;

  const next = state.clockEvents[0];
  const pill = document.getElementById("sidebar-next-event");
  if (next) {
    const countdown = formatCountdown(toDate(next.at).getTime() - Date.now());
    pill.textContent = `${CLOCK_KIND_LABELS[next.kind] || "关键节点"} · 还有 ${countdown}`;
  } else {
    pill.textContent = "暂无关键节点";
  }
}

function renderTopbar() {
  document.getElementById("topbar-title").textContent = `${getGreeting()}，${state.config.player.nickname || "农场主"}`;
  document.getElementById("topbar-balance").textContent = formatCurrency(state.wallet.balance);
  document.getElementById("topbar-net").textContent = signedCurrency(state.wallet.today_net);
}

function summaryCard(title, value, note = "", extraClass = "") {
  return `
    <article class="summary-card ${extraClass}">
      <span>${escapeHtml(title)}</span>
      <strong>${escapeHtml(value)}</strong>
      ${note ? `<p>${escapeHtml(note)}</p>` : ""}
    </article>
  `;
}

/* ---------------- 首页 ---------------- */

function renderHome() {
  const inStockValue = state.fruitsInStock.reduce((total, item) => total + Number(item.estimated_total || 0), 0);
  document.getElementById("wallet-summary-grid").innerHTML = [
    summaryCard("当前余额", formatCurrency(state.wallet.balance), "总流水实时汇总"),
    summaryCard("今日收入", formatCurrency(state.wallet.today_income), "卖出果实与偷别人的菜"),
    summaryCard("今日支出", formatCurrency(state.wallet.today_expense), "种子与被偷损失"),
    summaryCard("背包果实估值", formatCurrency(inStockValue), `${state.fruitsInStock.length} 个批次在库，卖出后入账`),
  ].join("");

  const ledgerBody = document.getElementById("ledger-table-body");
  if (!state.ledger.length) {
    ledgerBody.innerHTML = `<tr><td colspan="5" class="muted">还没有任何流水。</td></tr>`;
  } else {
    ledgerBody.innerHTML = state.ledger.map((row) => `
      <tr>
        <td>${escapeHtml(formatDateTime(row.occurred_at))}</td>
        <td>${escapeHtml(LEDGER_TYPE_LABELS[row.type] || row.type)}</td>
        <td class="${Number(row.amount_signed) >= 0 ? "amount-positive" : "amount-negative"}">${escapeHtml(signedCurrency(row.amount_signed))}</td>
        <td>${escapeHtml(formatCurrency(row.balance_after))}</td>
        <td class="wrap-cell">${escapeHtml(row.note || "")}</td>
      </tr>
    `).join("");
  }

  const homeSummary = document.getElementById("home-farm-summary");
  homeSummary.innerHTML = `
    <div class="stack-item">
      <strong>当前农场状态</strong>
      <div class="muted">规划中 ${state.farmSummary.planned_slots} 格 · 生长中 ${state.farmSummary.active_slots} 格 · 可收获 ${state.farmSummary.ready_slots} 格</div>
    </div>
    <div class="stack-item">
      <strong>今日祝福 / 偷菜</strong>
      <div class="muted">发出祝福 ${state.blessing?.given_today ?? 0}/${state.blessing?.rules?.daily_give_limit ?? 10} · 被祝福 ${state.blessing?.received_today ?? 0}/${state.blessing?.rules?.daily_receive_limit ?? 30} · 偷菜 ${state.stealQuota?.outbound_today ?? 0}/${state.stealQuota?.rules?.daily_quota ?? 100}</div>
    </div>
    <div class="stack-item">
      <strong>最近偷菜动态</strong>
      <div class="muted">${state.raids.length ? `${state.raids[0].direction === "outbound" ? "你偷了别人的菜" : "别人偷了你的菜"} · ${formatDateTime(state.raids[0].occurred_at)}` : "目前还没有偷菜进出账记录。"}</div>
    </div>
  `;
}

function renderClockList() {
  const container = document.getElementById("home-clock-list");
  if (!container) return;
  const now = Date.now();
  const rows = state.clockEvents.slice(0, 6).map((event, index) => {
    const date = toDate(event.at);
    const countdown = formatCountdown(date.getTime() - now);
    return `
      <div class="clock-item ${index === 0 ? "next" : ""}">
        <span class="clock-time">${pad(date.getHours())}:${pad(date.getMinutes())}</span>
        <span class="clock-label">${WEEKDAY_LABELS[date.getDay() === 0 ? 6 : date.getDay() - 1]} · ${escapeHtml(event.label)}</span>
        <span class="clock-countdown">还有 ${countdown}</span>
      </div>
    `;
  });
  container.innerHTML = rows.join("") || `<div class="muted">暂无关键节点。</div>`;
}

/* ---------------- 农场页 ---------------- */

function renderFarmSummary() {
  document.getElementById("farm-summary-grid").innerHTML = [
    summaryCard("已开格子", String(state.config.farm.unlocked_slot_count), "按格子解锁"),
    summaryCard("已规划", String(state.farmSummary.planned_slots), "还没开始种"),
    summaryCard("生长中", String(state.farmSummary.active_slots), "已经手动确认种植"),
    summaryCard("可收获", String(state.farmSummary.ready_slots), "到点了就能登记收获"),
    summaryCard("变异中", String(getAllSlots().filter((slot) => (slot.mutation_entries || []).length > 0).length), "已标记词条的格子"),
    summaryCard("预计收入", formatCurrency(state.farmSummary.expected_income), "含双倍 / 小摊 / 变异"),
  ].join("");
}

function renderFieldSelects() {
  const fieldSelect = document.getElementById("farm-scope-field");
  fieldSelect.innerHTML = [1, 2, 3, 4].map((fieldNo) => `<option value="${fieldNo}">地块 ${fieldNo}</option>`).join("");
  fieldSelect.value = String(state.ui.farmScopeFieldNo || 1);

  const slotSelect = document.getElementById("farm-scope-slot");
  const scopedFieldNo = Number(state.ui.farmScopeFieldNo || 1);
  const options = getSlotsByField(scopedFieldNo)
    .filter((slot) => slot.is_unlocked)
    .map((slot) => {
      const title = slot.crop_name ? `${slot.slot_id} · ${slot.crop_name}` : `${slot.slot_id} · 空地`;
      return `<option value="${slot.slot_id}">${escapeHtml(title)}</option>`;
    })
    .join("");
  slotSelect.innerHTML = options;
  const fallbackSlotId = state.ui.farmScopeSlotId || state.ui.selectedSlotId;
  if (fallbackSlotId) {
    slotSelect.value = fallbackSlotId;
  }
}

function renderFarmEditor() {
  document.getElementById("farm-unlocked-slot-count").value = state.config.farm.unlocked_slot_count;
  renderFieldSelects();
  renderMutationOptions();

  const mode = state.ui.farmScopeMode || "all";
  const fieldSelect = document.getElementById("farm-scope-field");
  const slotSelect = document.getElementById("farm-scope-slot");
  const modeSelect = document.getElementById("farm-scope-mode");
  modeSelect.value = mode;
  fieldSelect.disabled = mode === "all";
  slotSelect.disabled = mode !== "slot";

  const selectedSlotId = mode === "slot" ? (state.ui.farmScopeSlotId || state.ui.selectedSlotId) : "";
  const selectedSlot = selectedSlotId ? getSlotById(selectedSlotId) : null;
  const summary = document.getElementById("farm-plan-summary");
  const mutationMultiplier = selectedMutationMultiplier();
  summary.innerHTML = `
    <div class="stack-item">
      <strong>当前规划总额</strong>
      <div class="muted">花费 ${formatCurrency(state.farmSummary.expected_cost)} · 收入 ${formatCurrency(state.farmSummary.expected_income)} · 净收益 ${formatCurrency(state.farmSummary.expected_net_income)}</div>
    </div>
    <div class="stack-item">
      <strong>当前选择</strong>
      <div class="muted">${selectedSlot ? `${selectedSlot.slot_id} · ${selectedSlot.crop_name || "空地"} · ${selectedSlot.status_label}` : "还没有选中具体格子。可用表单选范围，也可直接点击格子。"}</div>
      ${selectedSlot && (selectedSlot.mutation_entries || []).length ? `<div class="slot-badges" style="margin-top:6px;">${mutationBadgesHtml(selectedSlot)}</div>` : ""}
    </div>
    <div class="stack-item">
      <strong>变异编辑器</strong>
      <div class="muted">${state.ui.farmMutationEntries.size ? `已选 ${state.ui.farmMutationEntries.size} 条词条，总倍率 ×${mutationMultiplier}，更新所选后生效。` : "点击上方词条徽章给选中格子标记 / 取消变异。上限：普通 3 条，60 级+英雄作物 4 条。"}</div>
    </div>
  `;

  if (selectedSlot) {
    document.getElementById("farm-scope-slot").value = selectedSlot.slot_id;
    document.getElementById("farm-scope-field").value = String(selectedSlot.field_no);
    if (selectedSlot.crop_id) {
      state.ui.farmEditorCropId = selectedSlot.crop_id;
      setCropInputValue("farm-edit-crop-search", "farm-edit-crop-id", selectedSlot.crop_id);
    }
    const startValue = selectedSlot.planted_at || selectedSlot.planned_start_at || "";
    const harvestValue = selectedSlot.harvest_at || "";
    document.getElementById("farm-edit-phase").value = selectedSlot.phase || "planned";
    document.getElementById("farm-edit-start-at").value = startValue ? startValue.replace(" ", "T").slice(0, 16) : "";
    document.getElementById("farm-edit-harvest-at").value = harvestValue ? harvestValue.replace(" ", "T").slice(0, 16) : "";
    document.getElementById("farm-edit-note").value = selectedSlot.note || "";
    const waterRule = findWateringRuleByCropId(selectedSlot.crop_id);
    document.getElementById("farm-water-at").value = nowLocalInputValue();
    document.getElementById("farm-water-reduce").value = waterRule ? waterRule.reduce_minutes : "";
    let waterHint = waterRule
      ? `推荐单次浇水减少 ${waterRule.reduce_minutes} 分钟，间隔约 ${waterRule.interval_minutes} 分钟，最多 ${waterRule.max_count} 次。`
      : "当前作物没有匹配到浇水规则，也可以手动输入减时数。";
    if (waterRule && waterRule.late_block_minutes) {
      waterHint += ` 最后 ${waterRule.late_block_minutes} 分钟内浇水会延后成熟。`;
    }
    if (selectedSlot.remaining_minutes != null && selectedSlot.remaining_minutes <= 180 && selectedSlot.phase === "planted") {
      waterHint += " 距收获不足 3 小时，按攻略建议停水，保持低水位提高变异率。";
    }
    document.getElementById("farm-water-hint").textContent = waterHint;
  } else {
    document.getElementById("farm-water-at").value = nowLocalInputValue();
    document.getElementById("farm-water-reduce").value = "";
    document.getElementById("farm-water-hint").textContent = mode === "all"
      ? "当前会对全部已开格子生效，地块和格子选择已锁定。"
      : mode === "field"
        ? "当前会对整块地生效，格子选择已锁定。"
        : "选择已种植格子后，这里会给出推荐浇水减时。";
  }
}

function renderFarmLayout() {
  const container = document.getElementById("farm-layout");
  const blessingRules = state.blessing?.rules || {};
  const perCropMax = blessingRules.per_crop_max ?? 3;
  container.innerHTML = state.fields.map((field) => `
    <article class="field-card ${field.unlocked_slot_count ? "" : "locked"}">
      <div class="field-top">
        <div>
          <h4>地块 ${field.field_no}</h4>
          <div class="muted">${field.unlocked_slot_count}/${field.slots.length} 格已开</div>
        </div>
        <span class="field-badge">${field.planned_slot_count} 规划 / ${field.active_slot_count} 生长</span>
      </div>
      <div class="field-meta">
        <span class="field-chip">横 4 · 竖 3</span>
        <span class="field-chip">${field.unlocked_slot_count ? "可编辑" : "先开格子"}</span>
      </div>
      <div class="slot-grid">
        ${field.slots.map((slot) => {
          const selected = state.ui.selectedSlotId === slot.slot_id;
          const classNames = ["slot-card"];
          if (!slot.is_unlocked) {
            classNames.push("locked");
          } else {
            if (slot.phase === "planned") classNames.push("is-planned");
            if (slot.phase === "planted" || slot.phase === "ready") classNames.push(slot.phase === "ready" ? "is-ready" : "is-planted");
            if ((slot.mutation_entries || []).length) classNames.push("is-mutated");
            if (slot.hero_flag) classNames.push("is-hero");
          }
          if (selected) classNames.push("selected");
          const title = slot.crop_name || (slot.is_unlocked ? "空地" : "锁定");
          const detail = !slot.is_unlocked
            ? "未解锁"
            : slot.crop_name
              ? (slot.remaining_label || slot.status_label)
              : "待种植";
          const badges = [
            mutationBadgesHtml(slot),
            slot.blessing_count ? `<span class="badge badge-teal">祝${slot.blessing_count}/${perCropMax}</span>` : "",
          ].filter(Boolean).join("");
          return `
            <button class="${classNames.join(" ")}" data-slot-id="${slot.slot_id}" ${slot.is_unlocked ? "" : "disabled"}>
              <span class="slot-code">${escapeHtml(slot.slot_id)}</span>
              <strong class="slot-crop">${escapeHtml(title)}</strong>
              <span class="slot-status">${escapeHtml(detail)}</span>
              ${badges ? `<span class="slot-badges">${badges}</span>` : ""}
            </button>
          `;
        }).join("")}
      </div>
    </article>
  `).join("");
}

function renderBlessingPanel() {
  const container = document.getElementById("farm-blessing-panel");
  if (!container) return;
  const blessing = state.blessing || {};
  const rules = blessing.rules || {};
  const givenLimit = rules.daily_give_limit ?? 10;
  const receiveLimit = rules.daily_receive_limit ?? 30;
  const givenPct = Math.min(100, Math.round(((blessing.given_today || 0) / givenLimit) * 100));
  const receivedPct = Math.min(100, Math.round(((blessing.received_today || 0) / receiveLimit) * 100));
  container.innerHTML = `
    <div class="two-panel-grid">
      <div class="quota-row">
        <div class="quota-head"><span>今日发出祝福</span><strong>${blessing.given_today ?? 0} / ${givenLimit}</strong></div>
        <div class="progress-track"><div class="progress-fill ${givenPct >= 100 ? "red" : ""}" style="width:${givenPct}%"></div></div>
        <div class="muted">优先祝福已变异 / 长周期作物；蓝色词条作物直接跳过；1 小时及以下的作物别浪费祝福。</div>
      </div>
      <div class="quota-row">
        <div class="quota-head"><span>今日被祝福</span><strong>${blessing.received_today ?? 0} / ${receiveLimit}</strong></div>
        <div class="progress-track"><div class="progress-fill ${receivedPct >= 100 ? "red" : "green"}" style="width:${receivedPct}%"></div></div>
        <div class="muted">吃满 30 次需要 3+ 小号或固定互祝好友组；每次祝福都是一次变异判定。</div>
      </div>
    </div>
  `;
}

/* ---------------- 规划页 ---------------- */

function buildPlanCard(title, key, plan, fallback) {
  if (!plan) {
    return `
      <article class="plan-card">
        <strong>${escapeHtml(title)}</strong>
        <div class="muted">${escapeHtml(fallback)}</div>
      </article>
    `;
  }

  state.ui.plannerPlans[key] = plan;
  return `
    <article class="plan-card ${plan.warning ? "warning" : ""}">
      <strong>${escapeHtml(title)}</strong>
      <div class="muted">${escapeHtml(plan.summary || "")}</div>
      <div class="plan-tags">
        <span class="plan-tag">播种 ${escapeHtml(formatDateTime(plan.plant_at))}</span>
        <span class="plan-tag">收获 ${escapeHtml(formatDateTime(plan.harvest_at))}</span>
        <span class="plan-tag">${escapeHtml(plan.strategy_name)}</span>
        ${plan.is_anti_theft_safe ? '<span class="plan-tag">防偷窗口内</span>' : '<span class="plan-tag warning">可偷时段</span>'}
        ${plan.is_weekend_bonus_time ? '<span class="plan-tag">周末双倍</span>' : ""}
      </div>
      <div class="muted">花费 ${formatCurrency(plan.seed_cost_total)} · 收入 ${formatCurrency(plan.estimated_income)} · 净收益 ${formatCurrency(plan.estimated_net_income)}</div>
      <div class="muted">${plan.watering_times.length ? `浇水：${plan.watering_times.map((item) => item.label).join(" / ")}` : "不需要额外浇水提醒。"}</div>
      <div class="editor-actions" style="margin-top:12px;">
        <button class="accent-button" type="button" data-plan-key="${escapeHtml(key)}">应用到已开格子</button>
      </div>
    </article>
  `;
}

function renderPlanner() {
  document.getElementById("planner-slot-count").value = state.ui.plannerSlotCount || state.config.farm.unlocked_slot_count;
  if (!state.ui.plannerCropId && state.crops.length) {
    state.ui.plannerCropId = state.crops[0].crop_id;
  }
  setCropInputValue("planner-crop-search", "planner-crop-id", state.ui.plannerCropId);

  const container = document.getElementById("planner-results");
  state.ui.plannerPlans = {};
  if (!state.planner) {
    container.innerHTML = `
      <article class="plan-card">
        <strong>先生成一份方案</strong>
        <div class="muted">选中作物与格子数后，系统会生成现在种、最早防偷、最优周末、双条件叠加四类方案。</div>
      </article>
    `;
    return;
  }

  const cards = [];
  state.planner.plant_now_assessments.forEach((plan, index) => {
    cards.push(buildPlanCard(`如果现在就种 · ${plan.strategy_name}`, `now-${index}`, plan, ""));
  });
  cards.push(buildPlanCard("最早防偷方案", "anti", state.planner.anti_theft_recommendation, "当前搜索范围内没找到能卡进防偷窗口的方案。"));
  cards.push(buildPlanCard("最优周末双倍方案", "weekend", state.planner.weekend_recommendation, "当前搜索范围内没找到合适的周末双倍方案。"));
  cards.push(buildPlanCard("周末 + 防偷叠加方案", "combined", state.planner.combined_recommendation, "还没有找到同时满足双倍和防偷的方案。"));
  if (state.planner.warning) {
    cards.unshift(`
      <article class="plan-card warning">
        <strong>当前判断</strong>
        <div class="muted">${escapeHtml(state.planner.warning)}</div>
      </article>
    `);
  }
  container.innerHTML = cards.join("");
}

/* ---------------- 收益页 ---------------- */

function cultivationMultiplierFor(cropId, fallbackLevel = null) {
  if (fallbackLevel) {
    const levels = state.mechanics?.cultivation_levels || [];
    const match = levels.find((item) => Number(item.level) === Number(fallbackLevel));
    if (match) return Number(match.multiplier || 1);
  }
  const row = state.cultivation.find((item) => item.crop_id === cropId);
  return row ? Number(row.multiplier || 1) : 1;
}

function expectedMutationMultiplier() {
  const types = state.mutations?.mutation_types || [];
  const trigger = state.mutations?.trigger_rules || {};
  const chance = Number(trigger.base_chance ?? 0.2);
  if (!types.length) return 1;
  const meanMultiplier = types.reduce((sum, item) => sum + Number(item.multiplier || 1), 0) / types.length;
  return 1 + chance * (meanMultiplier - 1);
}

function computeProfit(crop, options) {
  const stallPct = Number(state.config?.player?.stall_bonus_pct || 0);
  const cultivationMultiplier = cultivationMultiplierFor(crop.crop_id, options.cultivationLevel);
  const unitPrice = crop.base_sell_price * cultivationMultiplier * (1 + stallPct / 100);
  const weekendMultiplier = options.weekend ? Number(state.mechanics?.weekend_bonus_multiplier || 2) : 1;
  const tier2Multiplier = options.tier2 ? 1 + Number(state.mechanics?.tier2_field?.yield_bonus_ratio ?? 0.5) : 1;
  const mutationMultiplier = options.mutation ? expectedMutationMultiplier() : 1;
  const expectedUnit = unitPrice * weekendMultiplier * mutationMultiplier;
  const totalIncome = expectedUnit * options.plotCount * tier2Multiplier;
  const totalCost = crop.seed_cost * options.plotCount;
  const netIncome = totalIncome - totalCost;
  const hours = Math.max(1 / 60, crop.growth_minutes / 60);
  return {
    unitPrice,
    cultivationMultiplier,
    weekendMultiplier,
    tier2Multiplier,
    mutationMultiplier,
    expectedUnit,
    totalIncome,
    totalCost,
    netIncome,
    netPerHour: netIncome / hours,
    incomePerHour: totalIncome / hours,
  };
}

function calcRow(label, value, note = "", isTotal = false) {
  return `
    <div class="calc-row ${isTotal ? "total" : ""}">
      <span>${escapeHtml(label)}${note ? ` <span class="muted">(${escapeHtml(note)})</span>` : ""}</span>
      <span class="calc-value">${escapeHtml(value)}</span>
    </div>
  `;
}

function renderProfit() {
  const playerLevel = Number(state.config?.player?.level || 1);
  const unlockedCrops = state.crops.filter((crop) => crop.unlock_level <= playerLevel);
  if (!state.ui.calcCropId) {
    const preferred = [...unlockedCrops].sort((a, b) => b.hourly_income - a.hourly_income)[0] || state.crops[0];
    state.ui.calcCropId = preferred ? preferred.crop_id : "";
  }
  setCropInputValue("calc-crop-search", "calc-crop-id", state.ui.calcCropId);

  const crop = findCropById(state.ui.calcCropId);
  if (crop) {
    const options = {
      cultivationLevel: Number(document.getElementById("calc-cultivation-level").value || 1),
      plotCount: Number(document.getElementById("calc-plot-count").value || 1),
      weekend: document.getElementById("calc-weekend").checked,
      tier2: document.getElementById("calc-tier2").checked,
      mutation: document.getElementById("calc-mutation").checked,
    };
    const result = computeProfit(crop, options);

    document.getElementById("calc-summary").innerHTML = [
      summaryCard("单株期望售价", formatCurrency(result.expectedUnit), `含培育 ×${result.cultivationMultiplier}、小摊 +${state.config.player.stall_bonus_pct}%`),
      summaryCard("总收入预估", formatCurrency(result.totalIncome), `${options.plotCount} 格 × 产量系数`),
      summaryCard("总净收益", formatCurrency(result.netIncome), `扣除种子 ${formatCurrency(result.totalCost)}`),
      summaryCard("折算每小时", formatCurrency(result.netPerHour), "净收益 ÷ 自然成熟时长"),
    ].join("");

    document.getElementById("calc-breakdown").innerHTML = [
      calcRow("初始单株售价", formatCurrency(crop.base_sell_price)),
      calcRow("培育等级倍率", `×${result.cultivationMultiplier}`, options.cultivationLevel ? `当前按 ${options.cultivationLevel} 级` : "背包实际等级"),
      calcRow("小摊加成", `×${(1 + state.config.player.stall_bonus_pct / 100).toFixed(2)}`, `+${state.config.player.stall_bonus_pct}%`),
      calcRow("周末双倍", options.weekend ? `×${result.weekendMultiplier}` : "未启用"),
      calcRow("2 级地", options.tier2 ? `×${result.tier2Multiplier.toFixed(2)}` : "未启用", "产量 +50%"),
      calcRow("变异期望", options.mutation ? `×${result.mutationMultiplier.toFixed(2)}` : "未启用", "自然变异率 20% × 平均词条倍率"),
      calcRow("单株期望售价", formatCurrency(result.expectedUnit), "", true),
      calcRow("种植总成本", `-${formatCurrency(result.totalCost)}`, `${options.plotCount} 格种子`),
      calcRow("净收益", formatCurrency(result.netIncome), "", true),
    ].join("");
  }

  const advisor = document.getElementById("calc-advisor");
  const strategy = state.mechanics?.level_stall_strategy || {};
  const tailDigit = playerLevel % 10;
  let advice = "";
  if ((strategy.hero_tail_digits || []).includes(tailDigit)) {
    advice = `尾数是 ${tailDigit}：优先种英雄作物（32 小时档），收获后刚好跨级跳档解锁高阶作物。`;
  } else if ((strategy.economy_tail_digits || []).includes(tailDigit)) {
    advice = `尾数是 ${tailDigit}：优先种经济作物（16 小时档），把农场币攒够再冲级。`;
  } else if ((strategy.collab_tail_digits || []).includes(tailDigit)) {
    advice = `尾数是 ${tailDigit}：适合种联名 / 赛季种子，卡等级跳档收益最高。`;
  } else {
    advice = `尾数是 ${tailDigit}：正常按收益表种，保持每格都在周转即可。`;
  }
  advisor.innerHTML = `
    <div class="advisor-card">
      <strong>当前农场等级 ${playerLevel} · ${advice}</strong>
      <div class="muted">原理：收获结算的经验在升级瞬间「跳档」，等级尾数决定种什么能让跳档收益最大。赛季种子建议在尾数 4/9 时下地。</div>
    </div>
    <div class="advisor-card">
      <strong>开支顺序（社区共识）</strong>
      <div class="muted">先开满 12 格地 → 农场 44 级后升 2 级地（产量 +50%）→ 最后升满小摊。中途别乱花农场币抽卡。</div>
    </div>
    <div class="advisor-card">
      <strong>变异优先级</strong>
      <div class="muted">已变异（紫+/英雄）> 已出任意词条 > 普通 > 蓝色词条（跳过）。英雄变异自带防偷，留着吃满 4 次被偷 + 3 次回祝。</div>
    </div>
  `;

  const compareRows = unlockedCrops.map((item) => {
    const result = computeProfit(item, {
      cultivationLevel: null,
      plotCount: 1,
      weekend: true,
      tier2: false,
      mutation: false,
    });
    return { crop: item, result };
  }).sort((a, b) => b.result.netPerHour - a.result.netPerHour);
  const bestCropId = compareRows[0]?.crop.crop_id || "";

  const table = document.getElementById("calc-compare-table");
  table.innerHTML = `
    <thead>
      <tr>
        <th>作物</th><th>解锁</th><th>成熟</th><th>种子</th><th>单株售价</th><th>周末净收益/格</th><th>净收益/小时</th><th>变异</th>
      </tr>
    </thead>
    <tbody>
      ${compareRows.slice(0, 24).map(({ crop: item, result }) => `
        <tr class="${item.crop_id === bestCropId ? "is-recommended" : ""}">
          <td>${escapeHtml(item.name)}</td>
          <td>Lv${item.unlock_level}</td>
          <td>${escapeHtml(item.growth_label)}</td>
          <td>${formatCurrency(item.seed_cost)}</td>
          <td>${formatCurrency(result.unitPrice)}</td>
          <td>${formatCurrency(result.netIncome)}</td>
          <td>${formatCurrency(result.netPerHour)}</td>
          <td>${item.can_mutate ? "✅" : "—"}</td>
        </tr>
      `).join("")}
    </tbody>
  `;
}

/* ---------------- 背包页 ---------------- */

function setBagTab(tabId) {
  state.ui.bagTab = tabId;
  document.querySelectorAll("#bag-tabs .tab-item").forEach((button) => {
    button.classList.toggle("active", button.dataset.bagTab === tabId);
  });
  ["seeds", "fruits", "cultivation", "dex"].forEach((tab) => {
    const panel = document.getElementById(`bag-tab-${tab}`);
    if (panel) panel.hidden = tab !== tabId;
  });
}

function renderBag() {
  setBagTab(state.ui.bagTab);

  const seedBody = document.getElementById("seed-table-body");
  seedBody.innerHTML = state.seedInventory.length
    ? state.seedInventory.map((row) => `
        <tr>
          <td>${escapeHtml(row.crop_name)}</td>
          <td>${row.quantity}</td>
          <td>${escapeHtml(row.source || "—")}</td>
          <td class="wrap-cell">${escapeHtml(row.note || "")}</td>
          <td>${escapeHtml(formatDateTime(row.updated_at))}</td>
        </tr>
      `).join("")
    : `<tr><td colspan="5" class="muted">种子背包是空的。赛季奖励的种子记得先登记进来，种植时会优先消耗。</td></tr>`;

  const fruitBody = document.getElementById("fruit-table-body");
  fruitBody.innerHTML = state.fruitsInStock.length
    ? state.fruitsInStock.map((row) => `
        <tr>
          <td><input type="checkbox" class="fruit-check" data-fruit-id="${row.id}"></td>
          <td>${escapeHtml(row.crop_name)}</td>
          <td>×${row.quantity}${row.quantity > 1 ? '<span class="badge badge-green">双倍</span>' : ""}</td>
          <td>${(row.mutation_entries || []).length ? row.mutation_entries.map((name) => mutationBadgeHtml(name)).join("") : '<span class="muted">普通</span>'}</td>
          <td>${row.mutation_multiplier > 1 ? `×${row.mutation_multiplier}` : "—"}</td>
          <td>${formatCurrency(row.estimated_total)}</td>
          <td>${escapeHtml(formatDateTime(row.harvested_at))}</td>
        </tr>
      `).join("")
    : `<tr><td colspan="7" class="muted">背包里还没有果实，去农场页登记收获吧。</td></tr>`;

  const soldBody = document.getElementById("fruit-sold-table-body");
  soldBody.innerHTML = state.fruitsSold.length
    ? state.fruitsSold.map((row) => `
        <tr>
          <td>${escapeHtml(formatDateTime(row.sold_at))}</td>
          <td>${escapeHtml(row.crop_name)}</td>
          <td>×${row.quantity}</td>
          <td>${(row.mutation_entries || []).length ? row.mutation_entries.map((name) => mutationBadgeHtml(name)).join("") : "—"}</td>
          <td class="amount-positive">+${formatCurrency(row.sell_total)}</td>
        </tr>
      `).join("")
    : `<tr><td colspan="5" class="muted">还没有卖出记录。</td></tr>`;

  const cultivationList = document.getElementById("cultivation-list");
  cultivationList.innerHTML = state.cultivation.length
    ? state.cultivation.map((row) => {
        const pct = row.is_max
          ? 100
          : Math.min(100, Math.round((row.points / (row.next_level_points || row.points || 1)) * 100));
        return `
          <div class="quota-row">
            <div class="quota-head">
              <span><strong>${escapeHtml(row.crop_name)}</strong> · ${row.level} 级（售价 ×${row.multiplier}）</span>
              <strong>${row.is_max ? "已满级" : `${row.points} / ${row.next_level_points} 培育值`}</strong>
            </div>
            <div class="progress-track"><div class="progress-fill ${row.is_max ? "green" : ""}" style="width:${pct}%"></div></div>
          </div>
        `;
      }).join("")
    : `<div class="muted">还没有培育值记录。每次收获一株 +10 点（12 级及以上作物）。</div>`;

  const collectedByCrop = new Map();
  state.collection.forEach((row) => {
    if (!collectedByCrop.has(row.crop_id)) collectedByCrop.set(row.crop_id, []);
    collectedByCrop.get(row.crop_id).push(row);
  });
  const dexCrops = state.crops.filter((crop) => crop.can_mutate);
  const collectedCount = dexCrops.filter((crop) => collectedByCrop.has(crop.crop_id)).length;
  document.getElementById("dex-summary").textContent = `可变异作物 ${collectedCount} / ${dexCrops.length} 已有收获记录（普通 + 各词条组合分别计入）`;
  document.getElementById("dex-grid").innerHTML = dexCrops.map((crop) => {
    const combos = collectedByCrop.get(crop.crop_id) || [];
    const comboBadges = combos
      .slice(0, 6)
      .map((combo) => combo.mutation_entries.length
        ? combo.mutation_entries.map((name) => mutationBadgeHtml(name)).join("")
        : `<span class="badge badge-green">普通</span>`)
      .join("");
    return `
      <div class="dex-cell ${combos.length ? "collected" : "missing"}">
        <div class="dex-name">${escapeHtml(crop.name)}</div>
        <div class="dex-sub">Lv${crop.unlock_level} · ${combos.length ? `${combos.length} 种组合` : "未收获"}</div>
        <div class="slot-badges" style="margin-top:6px;">${comboBadges}</div>
      </div>
    `;
  }).join("");
}

/* ---------------- 统计页 ---------------- */

function ensureStatsMonth() {
  const months = Array.from(new Set(state.events.map((item) => getMonthKey(item.occurred_at)).filter(Boolean))).sort();
  const current = months.includes(state.ui.statsMonth) ? state.ui.statsMonth : (months[months.length - 1] || getMonthKey(new Date().toISOString()));
  state.ui.statsMonth = current;
  return months.length ? months : [current];
}

function filteredEvents() {
  return state.events.filter((item) => {
    const monthMatch = getMonthKey(item.occurred_at) === state.ui.statsMonth;
    const typeMatch = state.ui.visibleEventTypes.has(item.event_type);
    return monthMatch && typeMatch;
  });
}

function renderStatsChart(events) {
  const chart = document.getElementById("stats-chart");
  const tooltip = document.getElementById("chart-tooltip");
  const monthKey = state.ui.statsMonth;
  if (!monthKey) {
    chart.innerHTML = "";
    tooltip.classList.remove("visible");
    return;
  }

  const [yearText, monthText] = monthKey.split("-");
  const year = Number(yearText);
  const month = Number(monthText);
  const daysInMonth = new Date(year, month, 0).getDate();
  const width = 1200;
  const height = 560;
  const margin = { top: 30, right: 20, bottom: 54, left: 70 };
  const plotWidth = width - margin.left - margin.right;
  const plotHeight = height - margin.top - margin.bottom;
  const yTicks = [0, 360, 720, 1080, 1439];

  const gridLines = yTicks.map((minuteValue) => {
    const y = margin.top + plotHeight - (minuteValue / 1439) * plotHeight;
    return `
      <line x1="${margin.left}" x2="${width - margin.right}" y1="${y}" y2="${y}" stroke="var(--chart-grid)" stroke-dasharray="4 8"></line>
      <text x="${margin.left - 12}" y="${y + 4}" fill="var(--chart-text)" font-size="13" text-anchor="end">${formatMinuteLabel(minuteValue)}</text>
    `;
  }).join("");

  const xTicks = Array.from({ length: daysInMonth }, (_, index) => index + 1)
    .filter((day) => day === 1 || day === daysInMonth || day % (daysInMonth > 18 ? 4 : 2) === 0)
    .map((day) => {
      const x = margin.left + ((day - 1) / Math.max(1, daysInMonth - 1)) * plotWidth;
      return `
        <line x1="${x}" x2="${x}" y1="${margin.top}" y2="${height - margin.bottom}" stroke="var(--chart-grid-soft)"></line>
        <text x="${x}" y="${height - 20}" fill="var(--chart-text)" font-size="13" text-anchor="middle">${day}日</text>
      `;
    }).join("");

  const offsetByType = {
    plant: -12,
    water: -5,
    harvest: 2,
    theft: 9,
    raid: 16,
    bless: -19,
  };

  const dots = events.map((item) => {
    const date = toDate(item.occurred_at);
    if (!date || !EVENT_META[item.event_type]) {
      return "";
    }
    const dayIndex = date.getDate();
    const minuteOfDay = date.getHours() * 60 + date.getMinutes();
    const x = margin.left + ((dayIndex - 1) / Math.max(1, daysInMonth - 1)) * plotWidth + (offsetByType[item.event_type] || 0);
    const y = margin.top + plotHeight - (minuteOfDay / 1439) * plotHeight;
    const meta = EVENT_META[item.event_type];
    const title = `${meta.label} · ${formatDateTime(item.occurred_at)}`;
    const note = item.note || `${item.related_name || ""}${item.crop_id ? ` · ${item.crop_id}` : ""}`.trim();
    return `
      <circle
        cx="${x}"
        cy="${y}"
        r="5.5"
        fill="${meta.color}"
        stroke="var(--chart-dot-stroke)"
        stroke-width="2"
        data-title="${escapeHtml(title)}"
        data-detail="${escapeHtml(note)}"
      >
        <title>${escapeHtml(`${title} ${note}`)}</title>
      </circle>
    `;
  }).join("");

  chart.innerHTML = `
    <rect x="0" y="0" width="${width}" height="${height}" fill="transparent"></rect>
    <rect x="${margin.left}" y="${margin.top}" width="${plotWidth}" height="${plotHeight}" rx="14" fill="var(--chart-plot)" stroke="var(--chart-grid-soft)"></rect>
    ${gridLines}
    ${xTicks}
    ${dots}
    <text x="${margin.left + plotWidth / 2}" y="${height - 6}" fill="var(--chart-text)" font-size="13" text-anchor="middle">${monthKey.replace("-", " 年 ") + " 月"}</text>
  `;

  tooltip.classList.remove("visible");
}

function renderStats() {
  const monthOptions = ensureStatsMonth();
  const monthFilter = document.getElementById("stats-month-filter");
  monthFilter.innerHTML = monthOptions.map((monthKey) => `<option value="${monthKey}">${monthKey.replace("-", " 年 ") + " 月"}</option>`).join("");
  monthFilter.value = state.ui.statsMonth;

  const typeFilter = document.getElementById("stats-type-filter");
  const monthEvents = state.events.filter((item) => getMonthKey(item.occurred_at) === state.ui.statsMonth);
  const counts = Object.fromEntries(Object.keys(EVENT_META).map((type) => [type, monthEvents.filter((item) => item.event_type === type).length]));

  typeFilter.innerHTML = Object.entries(EVENT_META).map(([type, meta]) => `
    <button
      class="legend-button ${state.ui.visibleEventTypes.has(type) ? "active" : ""}"
      data-event-type="${type}"
      style="color:${meta.color};"
    >
      ${meta.label} · ${counts[type]}
    </button>
  `).join("");

  const events = filteredEvents();
  renderStatsChart(events);
  const visibleCounts = Object.fromEntries(Object.keys(EVENT_META).map((type) => [type, events.filter((item) => item.event_type === type).length]));
  const summary = document.getElementById("stats-summary-grid");
  const hourBuckets = Array.from({ length: 24 }, () => 0);
  events.forEach((item) => {
    const date = toDate(item.occurred_at);
    if (date) {
      hourBuckets[date.getHours()] += 1;
    }
  });
  const hotHour = hourBuckets.reduce((bestIndex, value, index, array) => (value > array[bestIndex] ? index : bestIndex), 0);

  summary.innerHTML = `
    <div class="stack-item"><strong>当前筛选记录</strong><div class="muted">${events.length} 条</div></div>
    <div class="stack-item"><strong>种植 / 浇水 / 收获</strong><div class="muted">${visibleCounts.plant} / ${visibleCounts.water} / ${visibleCounts.harvest}</div></div>
    <div class="stack-item"><strong>偷菜 / 祝福</strong><div class="muted">被偷 ${visibleCounts.theft} · 偷别人 ${visibleCounts.raid} · 祝福 ${visibleCounts.bless}</div></div>
    <div class="stack-item"><strong>最活跃时段</strong><div class="muted">${pad(hotHour)}:00</div></div>
  `;
}

/* ---------------- 偷菜页 ---------------- */

function renderTheftQuota() {
  const container = document.getElementById("theft-quota-panel");
  if (!container) return;
  const quota = state.stealQuota || {};
  const rules = quota.rules || {};
  const used = quota.outbound_today ?? 0;
  const limit = rules.daily_quota ?? 100;
  const pct = Math.min(100, Math.round((used / limit) * 100));

  const now = new Date();
  const nowMinutes = now.getHours() * 60 + now.getMinutes();
  const windowStart = rules.window_start || "08:00";
  const windowEnd = rules.window_end || "24:00";
  const [startH, startM] = windowStart.split(":").map(Number);
  const [endH, endM] = windowEnd.split(":").map(Number);
  const isOpen = nowMinutes >= startH * 60 + startM && nowMinutes < (endH === 24 ? 1440 : endH * 60 + endM);
  const closeMinutes = (endH === 24 ? 1440 : endH * 60 + endM) - nowMinutes;
  const windowText = isOpen
    ? `窗口开放中 · ${closeMinutes > 0 ? `${Math.floor(closeMinutes / 60)}小时${closeMinutes % 60}分后关闭` : "即将关闭"}`
    : `已关闭 · 明早 ${windowStart} 开启（夜间保护）`;

  container.innerHTML = `
    <article class="summary-card">
      <span>今日偷菜次数</span>
      <strong>${used} / ${limit}</strong>
      <div class="progress-track" style="margin-top:8px;"><div class="progress-fill ${pct >= 100 ? "red" : ""}" style="width:${pct}%"></div></div>
      <p>每天 05:00 重置，超出配额当天偷不了。</p>
    </article>
    <article class="summary-card">
      <span>偷菜窗口（${windowStart}-${windowEnd}）</span>
      <strong>${isOpen ? "开放中" : "已关闭"}</strong>
      <p>${windowText}</p>
    </article>
    <article class="summary-card">
      <span>单株规则</span>
      <strong>4 次 / 40%</strong>
      <p>每株作物最多被偷 ${rules.per_plant_max_takes ?? 4} 次，单株累计不超过 ${Math.round((rules.per_plant_cap_ratio ?? 0.4) * 100)}%。</p>
    </article>
    <article class="summary-card">
      <span>英雄变异</span>
      <strong>免疫被偷</strong>
      <p>标记了英雄词条的作物不可被偷；被偷+回祝各算一次变异判定。</p>
    </article>
  `;
}

function renderRaidList() {
  const raidList = document.getElementById("raid-list");
  if (!state.raids.length) {
    raidList.innerHTML = `<div class="stack-item"><strong>暂无记录</strong><div class="muted">偷别人菜和被偷菜都会显示在这里。</div></div>`;
    return;
  }

  raidList.innerHTML = state.raids.map((raid) => `
    <div class="stack-item">
      <strong>${raid.direction === "outbound" ? "我偷了别人的菜" : "别人偷了我的菜"}</strong>
      <div class="muted">${formatDateTime(raid.occurred_at)} · ${escapeHtml(raid.crop_id)} × ${raid.quantity} · ${raid.direction === "outbound" ? "+" : "-"}${formatCurrency(raid.amount)}</div>
      <div class="muted">${escapeHtml(raid.counterparty_name || "")}${raid.slot_id ? ` · ${escapeHtml(raid.slot_id)}` : ""}</div>
    </div>
  `).join("");
}

/* ---------------- 经验页 ---------------- */

function loadChecklistState() {
  const weekKey = getISOWeekKey();
  try {
    const raw = JSON.parse(localStorage.getItem("farm-weekly-checklist") || "null");
    if (raw && raw.week === weekKey && Array.isArray(raw.checked)) {
      return new Set(raw.checked);
    }
  } catch (error) { /* ignore */ }
  return new Set();
}

function saveChecklistState(checkedSet) {
  try {
    localStorage.setItem(
      "farm-weekly-checklist",
      JSON.stringify({ week: getISOWeekKey(), checked: Array.from(checkedSet) }),
    );
  } catch (error) { /* ignore */ }
}

function renderWeeklyChecklist() {
  const container = document.getElementById("weekly-checklist");
  if (!container) return;
  const checked = loadChecklistState();
  container.innerHTML = WEEKLY_ROUTINE.map((item) => `
    <label class="check-item">
      <input type="checkbox" data-check-id="${escapeHtml(item.id)}" ${checked.has(item.id) ? "checked" : ""}>
      <span class="check-body">
        <strong>${escapeHtml(item.title)}</strong>
        <span class="muted">${escapeHtml(item.detail)}</span>
      </span>
    </label>
  `).join("");
}

function renderExpPage() {
  const payload = state.experiences || { items: [] };
  const repoUrl = (payload.repo_url || "").replace(/\/$/, "");
  const submitButton = document.getElementById("exp-submit-button");
  const issuesButton = document.getElementById("exp-issues-button");
  if (submitButton) {
    submitButton.href = repoUrl ? `${repoUrl}/issues/new?template=experience.md` : "https://github.com/June6699/wzry-farm-reminder/issues/new?template=experience.md";
  }
  if (issuesButton) {
    issuesButton.href = repoUrl ? `${repoUrl}/issues?q=label%3Aexperience` : "https://github.com/June6699/wzry-farm-reminder/issues?q=label%3Aexperience";
  }

  const items = payload.items || [];
  const tags = Array.from(new Set(items.flatMap((item) => item.tags || [])));
  const activeTag = state.ui.expFilterTag;

  const tagContainer = document.getElementById("exp-filter-tags");
  tagContainer.innerHTML = [
    `<button type="button" class="exp-filter-tag ${!activeTag ? "active" : ""}" data-exp-tag="">全部</button>`,
    ...tags.map((tag) => `<button type="button" class="exp-filter-tag ${activeTag === tag ? "active" : ""}" data-exp-tag="${escapeHtml(tag)}">${escapeHtml(tag)}</button>`),
  ].join("");

  const filtered = activeTag ? items.filter((item) => (item.tags || []).includes(activeTag)) : items;
  const list = document.getElementById("exp-list");
  list.innerHTML = filtered.length
    ? filtered.map((item) => `
        <article class="exp-card">
          <h4>${escapeHtml(item.title)}</h4>
          <div class="exp-meta">
            ${(item.tags || []).map((tag) => `<span class="badge badge-blue">${escapeHtml(tag)}</span>`).join("")}
            <span>${escapeHtml(item.author || "社区")}</span>
            <span>${escapeHtml(item.date || "")}</span>
          </div>
          <p class="exp-body">${escapeHtml(item.body || "")}</p>
          ${item.source_url ? `<a class="link-button exp-source" href="${escapeHtml(item.source_url)}" target="_blank" rel="noopener">来源链接 →</a>` : ""}
        </article>
      `).join("")
    : `<div class="muted">这个标签下还没有内容。</div>`;
}

/* ---------------- 设置页 ---------------- */

function hydrateSettings() {
  document.getElementById("player-nickname").value = state.config.player.nickname;
  document.getElementById("player-game-id").value = state.config.player.game_id;
  document.getElementById("player-level").value = state.config.player.level;
  document.getElementById("player-avatar-path").value = state.config.player.avatar_path;
  document.getElementById("player-stall-bonus").value = state.config.player.stall_bonus_pct;
  document.getElementById("settings-unlocked-slot-count").value = state.config.farm.unlocked_slot_count;
  document.getElementById("notify-buffer").value = state.config.notifications.operation_buffer_min;
  document.getElementById("notify-plant-ahead").value = state.config.notifications.plant_remind_ahead_min;
  document.getElementById("notify-water-ahead").value = state.config.notifications.water_remind_ahead_min;
  document.getElementById("notify-harvest-ahead").value = state.config.notifications.harvest_remind_ahead_min;
  document.getElementById("planner-weekend-target").value = state.config.planner.weekend_target_time;
  document.getElementById("planner-prefer-weekend").checked = state.config.planner.prefer_weekend_bonus;
  document.getElementById("planner-prefer-anti-theft").checked = state.config.planner.prefer_anti_theft;
  document.getElementById("planner-auto-watering").checked = state.config.planner.auto_use_watering_strategy;
  document.getElementById("planner-search-horizon").value = state.config.planner.search_horizon_days;
  document.getElementById("planner-anti-theft-enabled").checked = state.config.planner.anti_theft_enabled;
  document.getElementById("planner-safe-start").value = state.config.planner.anti_theft_safe_start;
  document.getElementById("planner-safe-end").value = state.config.planner.anti_theft_safe_end;
  const themeSelect = document.getElementById("appearance-theme");
  if (themeSelect) themeSelect.value = state.config.appearance?.theme || "system";
}

function renderRaidsAndSettings() {
  renderRaidList();
  hydrateSettings();
}

/* ---------------- 汇总渲染 ---------------- */

function renderAll() {
  renderCropDatalist();
  renderSidebar();
  renderTopbar();
  renderHome();
  renderClockList();
  renderFarmSummary();
  renderFarmEditor();
  renderFarmLayout();
  renderBlessingPanel();
  renderPlanner();
  renderProfit();
  renderBag();
  renderStats();
  renderTheftQuota();
  renderRaidList();
  renderWeeklyChecklist();
  renderExpPage();
  hydrateSettings();
  setSection(state.ui.section);

  if (state.ui.inboundCropId) setCropInputValue("inbound-crop-search", "inbound-crop-id", state.ui.inboundCropId);
  if (state.ui.outboundCropId) setCropInputValue("outbound-crop-search", "outbound-crop-id", state.ui.outboundCropId);
  if (state.ui.farmEditorCropId) setCropInputValue("farm-edit-crop-search", "farm-edit-crop-id", state.ui.farmEditorCropId);
}

async function bootstrap() {
  const dashboard = await request("/api/bootstrap");
  applyDashboard(dashboard);
  syncThemeFromConfig();
  if (!state.ui.plannerSlotCount) state.ui.plannerSlotCount = state.config.farm.unlocked_slot_count;
  if (!state.ui.plannerCropId && state.crops.length) state.ui.plannerCropId = state.crops[0].crop_id;
  if (!state.ui.inboundCropId && state.crops.length) state.ui.inboundCropId = state.crops[0].crop_id;
  if (!state.ui.outboundCropId && state.crops.length) state.ui.outboundCropId = state.crops[0].crop_id;
  if (!state.ui.farmScopeFieldNo) state.ui.farmScopeFieldNo = 1;
  renderAll();
}

async function saveConfig(payload, message) {
  const response = await request("/api/settings", {
    method: "POST",
    body: JSON.stringify(payload),
  });
  state.config = response.config;
  state.ui.plannerSlotCount = state.config.farm.unlocked_slot_count;
  renderAll();
  document.getElementById("settings-feedback").textContent = message;
}

function collectSettingsPayload() {
  return {
    player: {
      nickname: document.getElementById("player-nickname").value,
      game_id: document.getElementById("player-game-id").value,
      level: Number(document.getElementById("player-level").value),
      avatar_path: document.getElementById("player-avatar-path").value,
      stall_bonus_pct: Number(document.getElementById("player-stall-bonus").value),
    },
    farm: {
      unlocked_slot_count: Number(document.getElementById("settings-unlocked-slot-count").value),
      slots_per_field: 12,
      total_field_count: 4,
    },
    notifications: {
      operation_buffer_min: Number(document.getElementById("notify-buffer").value),
      plant_remind_ahead_min: Number(document.getElementById("notify-plant-ahead").value),
      water_remind_ahead_min: Number(document.getElementById("notify-water-ahead").value),
      harvest_remind_ahead_min: Number(document.getElementById("notify-harvest-ahead").value),
      channels: ["desktop", "sound"],
    },
    planner: {
      weekend_target_time: document.getElementById("planner-weekend-target").value,
      prefer_weekend_bonus: document.getElementById("planner-prefer-weekend").checked,
      prefer_anti_theft: document.getElementById("planner-prefer-anti-theft").checked,
      anti_theft_enabled: document.getElementById("planner-anti-theft-enabled").checked,
      anti_theft_safe_start: document.getElementById("planner-safe-start").value,
      anti_theft_safe_end: document.getElementById("planner-safe-end").value,
      auto_use_watering_strategy: document.getElementById("planner-auto-watering").checked,
      search_horizon_days: Number(document.getElementById("planner-search-horizon").value),
    },
    appearance: {
      theme: document.getElementById("appearance-theme").value || "system",
    },
  };
}

function currentScope() {
  return {
    mode: state.ui.farmScopeMode,
    field_no: Number(state.ui.farmScopeFieldNo || 1),
    slot_id: state.ui.farmScopeSlotId || state.ui.selectedSlotId || document.getElementById("farm-scope-slot").value,
  };
}

function selectedCropId(hiddenId, fallback = "") {
  const hidden = document.getElementById(hiddenId);
  return hidden.value || fallback;
}

/* ---------------- 事件绑定 ---------------- */

function bindNavigation() {
  document.querySelector(".nav-stack").addEventListener("click", (event) => {
    const button = event.target.closest(".nav-item");
    if (!button) return;
    setSection(button.dataset.section);
  });

  document.getElementById("theme-toggle").addEventListener("click", async () => {
    const current = document.documentElement.dataset.theme === "dark" ? "dark" : "light";
    const next = current === "dark" ? "light" : "dark";
    applyTheme(next);
    try {
      await saveThemePreference(next);
    } catch (error) {
      console.error(error);
    }
  });
}

function bindCropInputs() {
  attachCropSearch("planner-crop-search", "planner-crop-id", (cropId) => { state.ui.plannerCropId = cropId; });
  attachCropSearch("farm-edit-crop-search", "farm-edit-crop-id", (cropId) => { state.ui.farmEditorCropId = cropId; });
  attachCropSearch("inbound-crop-search", "inbound-crop-id", (cropId) => { state.ui.inboundCropId = cropId; });
  attachCropSearch("outbound-crop-search", "outbound-crop-id", (cropId) => { state.ui.outboundCropId = cropId; });
  attachCropSearch("seed-crop-search", "seed-crop-id");
  attachCropSearch("calc-crop-search", "calc-crop-id", (cropId) => {
    state.ui.calcCropId = cropId;
    renderProfit();
  });
}

function bindPlanner() {
  document.getElementById("planner-slot-count").addEventListener("input", (event) => {
    state.ui.plannerSlotCount = Number(event.target.value || state.config.farm.unlocked_slot_count);
  });

  document.getElementById("planner-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    const cropId = selectedCropId("planner-crop-id", state.ui.plannerCropId);
    if (!cropId) {
      document.getElementById("planner-feedback").textContent = "请先选一个作物。";
      return;
    }
    state.ui.plannerCropId = cropId;
    const slotCount = Number(document.getElementById("planner-slot-count").value || state.config.farm.unlocked_slot_count);
    const response = await request("/api/planner", {
      method: "POST",
      body: JSON.stringify({
        crop_id: cropId,
        plot_count: slotCount,
      }),
    });
    state.planner = response.planner;
    renderPlanner();
    document.getElementById("planner-feedback").textContent = "方案已生成，可以直接点“应用到已开格子”。";
  });

  document.getElementById("planner-results").addEventListener("click", async (event) => {
    const button = event.target.closest("[data-plan-key]");
    if (!button) {
      return;
    }
    const plan = state.ui.plannerPlans[button.dataset.planKey];
    const cropId = selectedCropId("planner-crop-id", state.ui.plannerCropId);
    if (!plan || !cropId) {
      return;
    }
    const response = await request("/api/plans/apply", {
      method: "POST",
      body: JSON.stringify({
        crop_id: cropId,
        slot_count: Number(document.getElementById("planner-slot-count").value || state.config.farm.unlocked_slot_count),
        plant_at: plan.plant_at,
        harvest_at: plan.harvest_at,
        strategy_id: plan.strategy_id,
        strategy_name: plan.strategy_name,
        watering_times: plan.watering_times,
      }),
    });
    applyDashboard(response.dashboard);
    renderAll();
    setSection("farm");
    document.getElementById("farm-editor-feedback").textContent = "规划已应用到已开格子。现在可以在农场页继续改单格、单块地或全部格子。";
  });
}

function bindFarm() {
  document.getElementById("farm-save-slot-count").addEventListener("click", async () => {
    const payload = collectSettingsPayload();
    payload.farm.unlocked_slot_count = Number(document.getElementById("farm-unlocked-slot-count").value);
    await saveConfig(payload, "已更新已开格子数。");
  });

  document.getElementById("farm-scope-mode").addEventListener("change", (event) => {
    state.ui.farmScopeMode = event.target.value;
    if (state.ui.farmScopeMode === "all") {
      state.ui.selectedSlotId = "";
    } else if (state.ui.farmScopeMode === "field") {
      state.ui.selectedSlotId = "";
      state.ui.farmScopeSlotId = "";
    } else if (state.ui.farmScopeMode === "slot" && !state.ui.farmScopeSlotId) {
      const firstSlot = getSlotsByField(state.ui.farmScopeFieldNo).find((slot) => slot.is_unlocked);
      if (firstSlot) {
        state.ui.farmScopeSlotId = firstSlot.slot_id;
        state.ui.selectedSlotId = firstSlot.slot_id;
      }
    }
    renderFarmEditor();
    renderFarmLayout();
  });

  document.getElementById("farm-scope-field").addEventListener("change", (event) => {
    state.ui.farmScopeFieldNo = Number(event.target.value);
    if (state.ui.farmScopeMode === "slot") {
      const firstSlot = getSlotsByField(state.ui.farmScopeFieldNo).find((slot) => slot.is_unlocked);
      state.ui.farmScopeSlotId = firstSlot ? firstSlot.slot_id : "";
      state.ui.selectedSlotId = state.ui.farmScopeSlotId;
    }
    renderFarmEditor();
    renderFarmLayout();
  });

  document.getElementById("farm-scope-slot").addEventListener("change", (event) => {
    state.ui.farmScopeSlotId = event.target.value;
    state.ui.selectedSlotId = event.target.value;
    const slot = getSlotById(event.target.value);
    if (slot) {
      state.ui.farmMutationEntries = new Set(slot.mutation_entries || []);
    }
    renderFarmEditor();
    renderFarmLayout();
  });

  document.getElementById("farm-layout").addEventListener("click", (event) => {
    const button = event.target.closest("[data-slot-id]");
    if (!button || button.disabled) return;
    state.ui.selectedSlotId = button.dataset.slotId;
    const slot = getSlotById(button.dataset.slotId);
    if (slot) {
      state.ui.farmScopeMode = "slot";
      state.ui.farmScopeFieldNo = slot.field_no;
      state.ui.farmScopeSlotId = slot.slot_id;
      state.ui.farmMutationEntries = new Set(slot.mutation_entries || []);
    }
    renderFarmEditor();
    renderFarmLayout();
  });

  document.getElementById("farm-mutation-options").addEventListener("click", (event) => {
    const button = event.target.closest("[data-mutation-name]");
    if (!button) return;
    const name = button.dataset.mutationName;
    if (state.ui.farmMutationEntries.has(name)) {
      state.ui.farmMutationEntries.delete(name);
    } else {
      state.ui.farmMutationEntries.add(name);
    }
    renderMutationOptions();
    renderFarmEditor();
  });

  document.getElementById("farm-editor-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    const payload = {
      scope: currentScope(),
      crop_id: selectedCropId("farm-edit-crop-id"),
      phase: document.getElementById("farm-edit-phase").value,
      start_at: document.getElementById("farm-edit-start-at").value,
      harvest_at: document.getElementById("farm-edit-harvest-at").value,
      note: document.getElementById("farm-edit-note").value,
      mutation_entries: Array.from(state.ui.farmMutationEntries),
    };
    try {
      const response = await request("/api/slots/update", {
        method: "POST",
        body: JSON.stringify(payload),
      });
      applyDashboard(response.dashboard);
      renderAll();
      document.getElementById("farm-editor-feedback").textContent = `所选范围已更新${state.ui.farmMutationEntries.size ? `（变异 ×${selectedMutationMultiplier()}）` : ""}，预计收入和花费已重新计算。`;
    } catch (error) {
      document.getElementById("farm-editor-feedback").textContent = `更新失败：${error.message}`;
    }
  });

  document.getElementById("farm-start-button").addEventListener("click", async () => {
    const response = await request("/api/slots/start", {
      method: "POST",
      body: JSON.stringify({
        scope: currentScope(),
        started_at: document.getElementById("farm-edit-start-at").value,
      }),
    });
    applyDashboard(response.dashboard);
    renderAll();
    const seedNote = (response.result.seed_notes || []).join("、");
    document.getElementById("farm-editor-feedback").textContent = `已手动开始种植 ${response.result.processed_count} 格。${seedNote ? `种子消耗：${seedNote}。` : ""}`;
  });

  document.getElementById("farm-water-button").addEventListener("click", async () => {
    const response = await request("/api/slots/water", {
      method: "POST",
      body: JSON.stringify({
        scope: currentScope(),
        occurred_at: document.getElementById("farm-water-at").value,
        reduce_minutes: Number(document.getElementById("farm-water-reduce").value || 0),
      }),
    });
    applyDashboard(response.dashboard);
    renderAll();
    document.getElementById("farm-editor-feedback").textContent = `已登记浇水 ${response.result.processed_count} 格，本次减时 ${response.result.reduce_minutes || 0} 分钟。`;
  });

  document.getElementById("farm-harvest-button").addEventListener("click", async () => {
    const response = await request("/api/slots/harvest", {
      method: "POST",
      body: JSON.stringify({
        scope: currentScope(),
        occurred_at: document.getElementById("farm-edit-harvest-at").value,
      }),
    });
    applyDashboard(response.dashboard);
    renderAll();
    const batches = response.result.fruit_batches || [];
    const mutatedCount = batches.filter((item) => (item.mutation_entries || []).length > 0).length;
    document.getElementById("farm-editor-feedback").textContent = `已收获 ${response.result.processed_count} 格，产出 ${batches.length} 批果实进入背包${mutatedCount ? `（含变异 ${mutatedCount} 批）` : ""}。去背包页卖出后才会入账。`;
  });

  document.getElementById("farm-clear-button").addEventListener("click", async () => {
    const response = await request("/api/slots/clear", {
      method: "POST",
      body: JSON.stringify({
        scope: currentScope(),
      }),
    });
    applyDashboard(response.dashboard);
    state.ui.selectedSlotId = "";
    state.ui.farmMutationEntries = new Set();
    renderAll();
    document.getElementById("farm-editor-feedback").textContent = `已清空 ${response.cleared} 个格子的规划/状态。`;
  });

  const blessingForm = document.getElementById("blessing-form");
  if (blessingForm) {
    blessingForm.addEventListener("submit", async (event) => {
      event.preventDefault();
      try {
        const response = await request("/api/blessings", {
          method: "POST",
          body: JSON.stringify({
            direction: document.getElementById("bless-direction").value,
            counterparty_name: document.getElementById("bless-counterparty").value,
            slot_id: document.getElementById("bless-slot").value,
            occurred_at: nowLocalInputValue(),
          }),
        });
        applyDashboard(response.dashboard);
        renderAll();
        document.getElementById("blessing-feedback").textContent = "祝福已登记。";
      } catch (error) {
        document.getElementById("blessing-feedback").textContent = `登记失败：${error.message}`;
      }
    });
  }
}

function bindBag() {
  document.getElementById("bag-tabs").addEventListener("click", (event) => {
    const button = event.target.closest("[data-bag-tab]");
    if (!button) return;
    setBagTab(button.dataset.bagTab);
  });

  document.getElementById("seed-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    try {
      const response = await request("/api/seeds", {
        method: "POST",
        body: JSON.stringify({
          crop_id: selectedCropId("seed-crop-id"),
          delta: Number(document.getElementById("seed-quantity").value || 0),
          source: document.getElementById("seed-source").value,
          note: document.getElementById("seed-note").value,
        }),
      });
      applyDashboard(response.dashboard);
      renderAll();
      document.getElementById("seed-feedback").textContent = `已登记：${response.result.crop_id} 现有 ${response.result.quantity} 个种子（本次 ${response.result.delta > 0 ? "+" : ""}${response.result.delta}）。`;
    } catch (error) {
      document.getElementById("seed-feedback").textContent = `登记失败：${error.message}`;
    }
  });

  document.getElementById("fruit-select-all").addEventListener("click", () => {
    const checks = Array.from(document.querySelectorAll(".fruit-check"));
    const allChecked = checks.length > 0 && checks.every((check) => check.checked);
    checks.forEach((check) => {
      check.checked = !allChecked;
    });
  });

  document.getElementById("fruit-sell-button").addEventListener("click", async () => {
    const fruitIds = Array.from(document.querySelectorAll(".fruit-check:checked")).map((check) => Number(check.dataset.fruitId));
    if (!fruitIds.length) {
      document.getElementById("fruit-feedback").textContent = "先勾选要卖出的批次。";
      return;
    }
    try {
      const response = await request("/api/fruits/sell", {
        method: "POST",
        body: JSON.stringify({ fruit_ids: fruitIds, occurred_at: nowLocalInputValue() }),
      });
      applyDashboard(response.dashboard);
      renderAll();
      document.getElementById("fruit-feedback").textContent = `已卖出 ${response.result.sold_count} 批，入账 ${formatCurrency(response.result.total_income)} 农场币。`;
    } catch (error) {
      document.getElementById("fruit-feedback").textContent = `卖出失败：${error.message}`;
    }
  });
}

function bindProfit() {
  ["calc-cultivation-level", "calc-plot-count", "calc-weekend", "calc-tier2", "calc-mutation"].forEach((id) => {
    const element = document.getElementById(id);
    if (!element) return;
    element.addEventListener("input", () => renderProfit());
    element.addEventListener("change", () => renderProfit());
  });
}

function bindStats() {
  document.getElementById("stats-month-filter").addEventListener("change", (event) => {
    state.ui.statsMonth = event.target.value;
    renderStats();
  });
  document.getElementById("stats-type-filter").addEventListener("click", (event) => {
    const button = event.target.closest("[data-event-type]");
    if (!button) return;
    const eventType = button.dataset.eventType;
    if (state.ui.visibleEventTypes.has(eventType)) {
      state.ui.visibleEventTypes.delete(eventType);
    } else {
      state.ui.visibleEventTypes.add(eventType);
    }
    renderStats();
  });

  const tooltip = document.getElementById("chart-tooltip");
  document.querySelector(".chart-shell").addEventListener("mousemove", (event) => {
    const dot = event.target.closest("circle[data-title]");
    if (!dot) {
      tooltip.classList.remove("visible");
      return;
    }
    const shellRect = event.currentTarget.getBoundingClientRect();
    tooltip.innerHTML = `
      <strong>${escapeHtml(dot.dataset.title)}</strong>
      <div>${escapeHtml(dot.dataset.detail || "")}</div>
    `;
    tooltip.style.left = `${event.clientX - shellRect.left + 16}px`;
    tooltip.style.top = `${event.clientY - shellRect.top + 12}px`;
    tooltip.classList.add("visible");
  });
  document.querySelector(".chart-shell").addEventListener("mouseleave", () => {
    tooltip.classList.remove("visible");
  });
}

function bindRaidForms() {
  const setNow = () => nowLocalInputValue();
  document.getElementById("inbound-occurred-at").value = setNow();
  document.getElementById("outbound-occurred-at").value = setNow();

  document.getElementById("inbound-raid-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    const response = await request("/api/raids", {
      method: "POST",
      body: JSON.stringify({
        direction: "inbound",
        occurred_at: document.getElementById("inbound-occurred-at").value,
        slot_id: document.getElementById("inbound-slot-id").value,
        crop_id: selectedCropId("inbound-crop-id", state.ui.inboundCropId),
        quantity: Number(document.getElementById("inbound-quantity").value),
        counterparty_name: document.getElementById("inbound-counterparty").value,
        is_weekend_bonus_time: document.getElementById("inbound-weekend").checked,
        note: document.getElementById("inbound-note").value,
      }),
    });
    applyDashboard(response.dashboard);
    renderAll();
  });

  document.getElementById("outbound-raid-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    const response = await request("/api/raids", {
      method: "POST",
      body: JSON.stringify({
        direction: "outbound",
        occurred_at: document.getElementById("outbound-occurred-at").value,
        crop_id: selectedCropId("outbound-crop-id", state.ui.outboundCropId),
        quantity: Number(document.getElementById("outbound-quantity").value),
        counterparty_name: document.getElementById("outbound-counterparty").value,
        is_weekend_bonus_time: document.getElementById("outbound-weekend").checked,
        note: document.getElementById("outbound-note").value,
      }),
    });
    applyDashboard(response.dashboard);
    renderAll();
  });
}

function bindSettings() {
  document.getElementById("settings-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    await saveConfig(collectSettingsPayload(), "设置已保存，当前页面已经同步到新的配置。");
  });

  const themeSelect = document.getElementById("appearance-theme");
  themeSelect.addEventListener("change", async () => {
    const theme = themeSelect.value;
    applyTheme(resolveThemePreference(theme));
    try {
      await saveThemePreference(theme);
    } catch (error) {
      console.error(error);
    }
  });
}

function bindExp() {
  document.getElementById("exp-filter-tags").addEventListener("click", (event) => {
    const button = event.target.closest("[data-exp-tag]");
    if (!button) return;
    state.ui.expFilterTag = button.dataset.expTag;
    renderExpPage();
  });

  document.getElementById("weekly-checklist").addEventListener("change", (event) => {
    const checkbox = event.target.closest("[data-check-id]");
    if (!checkbox) return;
    const checked = loadChecklistState();
    if (checkbox.checked) {
      checked.add(checkbox.dataset.checkId);
    } else {
      checked.delete(checkbox.dataset.checkId);
    }
    saveChecklistState(checked);
  });
}

document.addEventListener("DOMContentLoaded", async () => {
  bindNavigation();
  bindCropInputs();
  bindPlanner();
  bindFarm();
  bindBag();
  bindProfit();
  bindStats();
  bindRaidForms();
  bindSettings();
  bindExp();
  await bootstrap();

  window.setInterval(() => {
    renderClockList();
    const pill = document.getElementById("sidebar-next-event");
    const next = state.clockEvents[0];
    if (pill && next) {
      const countdown = formatCountdown(toDate(next.at).getTime() - Date.now());
      pill.textContent = `${CLOCK_KIND_LABELS[next.kind] || "关键节点"} · 还有 ${countdown}`;
    }
  }, 30000);
});
