const EVENT_META = {
  plant: { label: "种植", color: "#43c363" },
  water: { label: "浇水", color: "#35b3a6" },
  harvest: { label: "收获", color: "#ffc145" },
  theft: { label: "被偷菜", color: "#ef6b62" },
  raid: { label: "偷别人菜", color: "#b57cff" },
};

const state = {
  config: null,
  crops: [],
  mechanics: null,
  wateringRules: [],
  fields: [],
  wallet: null,
  ledger: [],
  raids: [],
  events: [],
  farmSummary: null,
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
    statsMonth: "",
    visibleEventTypes: new Set(Object.keys(EVENT_META)),
    plannerPlans: {},
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
      throw new Error(text || `Request failed: ${response.status}`);
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

function applyDashboard(dashboard) {
  state.config = dashboard.config;
  state.crops = dashboard.crops;
  state.mechanics = dashboard.mechanics;
  state.wateringRules = dashboard.watering_rules || [];
  state.fields = dashboard.fields;
  state.wallet = dashboard.wallet;
  state.ledger = dashboard.ledger;
  state.raids = dashboard.raids;
  state.events = dashboard.events;
  state.farmSummary = dashboard.farm_summary;
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
      <div class="profile-chip"><span>防偷窗口</span><strong>${state.config.planner.anti_theft_enabled ? `${state.config.planner.anti_theft_safe_start}-${state.config.planner.anti_theft_safe_end}` : "关闭"}</strong></div>
      <div class="profile-chip"><span>周末目标</span><strong>${state.config.planner.weekend_target_time}</strong></div>
    </div>
  `;

  document.getElementById("sidebar-safe-window").textContent = state.config.planner.anti_theft_enabled
    ? `防偷 ${state.config.planner.anti_theft_safe_start}-${state.config.planner.anti_theft_safe_end}`
    : "防偷已关闭";
  document.getElementById("sidebar-slot-count").textContent = `已开 ${state.config.farm.unlocked_slot_count} / 48 格`;
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

function renderHome() {
  document.getElementById("wallet-summary-grid").innerHTML = [
    summaryCard("当前余额", formatCurrency(state.wallet.balance), "总流水实时汇总"),
    summaryCard("今日收入", formatCurrency(state.wallet.today_income), "包括收获与偷别人的菜"),
    summaryCard("今日支出", formatCurrency(state.wallet.today_expense), "包括种子与被偷损失"),
    summaryCard("计划净收益", formatCurrency(state.wallet.planned_net), "当前农场规划的预计净收益"),
  ].join("");

  const ledgerBody = document.getElementById("ledger-table-body");
  if (!state.ledger.length) {
    ledgerBody.innerHTML = `<tr><td colspan="5" class="muted">还没有任何流水。</td></tr>`;
  } else {
    ledgerBody.innerHTML = state.ledger.map((row) => `
      <tr>
        <td>${escapeHtml(formatDateTime(row.occurred_at))}</td>
        <td>${escapeHtml(row.type)}</td>
        <td class="${Number(row.amount_signed) >= 0 ? "amount-positive" : "amount-negative"}">${escapeHtml(signedCurrency(row.amount_signed))}</td>
        <td>${escapeHtml(formatCurrency(row.balance_after))}</td>
        <td>${escapeHtml(row.note || "")}</td>
      </tr>
    `).join("");
  }

  const homeSummary = document.getElementById("home-farm-summary");
  homeSummary.innerHTML = `
    <div class="stack-item">
      <strong>已开格子</strong>
      <div class="muted">${state.config.farm.unlocked_slot_count} / 48 格</div>
    </div>
    <div class="stack-item">
      <strong>当前农场状态</strong>
      <div class="muted">规划中 ${state.farmSummary.planned_slots} 格 · 生长中 ${state.farmSummary.active_slots} 格 · 可收获 ${state.farmSummary.ready_slots} 格</div>
    </div>
    <div class="stack-item">
      <strong>最近偷菜动态</strong>
      <div class="muted">${state.raids.length ? `${state.raids[0].direction === "outbound" ? "你偷了别人的菜" : "别人偷了你的菜"} · ${formatDateTime(state.raids[0].occurred_at)}` : "目前还没有偷菜进出账记录。"}</div>
    </div>
  `;
}

function renderFarmSummary() {
  document.getElementById("farm-summary-grid").innerHTML = [
    summaryCard("已开格子", String(state.config.farm.unlocked_slot_count), "按格子解锁"),
    summaryCard("已规划", String(state.farmSummary.planned_slots), "还没开始种"),
    summaryCard("生长中", String(state.farmSummary.active_slots), "已经手动确认种植"),
    summaryCard("可收获", String(state.farmSummary.ready_slots), "到点了就能登记收获"),
    summaryCard("预计花费", formatCurrency(state.farmSummary.expected_cost), "全部当前方案"),
    summaryCard("预计收入", formatCurrency(state.farmSummary.expected_income), "包含双倍和小摊"),
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
  summary.innerHTML = `
    <div class="stack-item">
      <strong>当前规划总额</strong>
      <div class="muted">花费 ${formatCurrency(state.farmSummary.expected_cost)} · 收入 ${formatCurrency(state.farmSummary.expected_income)} · 净收益 ${formatCurrency(state.farmSummary.expected_net_income)}</div>
    </div>
    <div class="stack-item">
      <strong>当前选择</strong>
      <div class="muted">${selectedSlot ? `${selectedSlot.slot_id} · ${selectedSlot.crop_name || "空地"} · ${selectedSlot.status_label}` : "还没有选中具体格子。可用表单选范围，也可直接点击格子。"}</div>
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
    document.getElementById("farm-water-at").value = new Date().toISOString().slice(0, 16);
    document.getElementById("farm-water-reduce").value = waterRule ? waterRule.reduce_minutes : "";
    document.getElementById("farm-water-hint").textContent = waterRule
      ? `当前作物推荐单次浇水减少 ${waterRule.reduce_minutes} 分钟，间隔约 ${waterRule.interval_minutes} 分钟，最多 ${waterRule.max_count} 次。`
      : "当前作物没有匹配到浇水规则，你也可以手动输入一个减时数。";
  } else {
    document.getElementById("farm-water-at").value = new Date().toISOString().slice(0, 16);
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
          if (!slot.is_unlocked) classNames.push("locked");
          if (selected) classNames.push("selected");
          const title = slot.crop_name || (slot.is_unlocked ? "空地" : "锁定");
          const detail = !slot.is_unlocked
            ? "未解锁"
            : slot.crop_name
              ? (slot.remaining_label || slot.status_label)
              : "待种植";
          return `
            <button class="${classNames.join(" ")}" data-slot-id="${slot.slot_id}" ${slot.is_unlocked ? "" : "disabled"}>
              <span class="slot-code">${escapeHtml(slot.slot_id)}</span>
              <strong class="slot-crop">${escapeHtml(title)}</strong>
              <span class="slot-status">${escapeHtml(detail)}</span>
            </button>
          `;
        }).join("")}
      </div>
    </article>
  `).join("");
}

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
      <line x1="${margin.left}" x2="${width - margin.right}" y1="${y}" y2="${y}" stroke="rgba(255,255,255,0.08)" stroke-dasharray="4 8"></line>
      <text x="${margin.left - 12}" y="${y + 4}" fill="rgba(222,232,247,0.72)" font-size="13" text-anchor="end">${formatMinuteLabel(minuteValue)}</text>
    `;
  }).join("");

  const xTicks = Array.from({ length: daysInMonth }, (_, index) => index + 1)
    .filter((day) => day === 1 || day === daysInMonth || day % (daysInMonth > 18 ? 4 : 2) === 0)
    .map((day) => {
      const x = margin.left + ((day - 1) / Math.max(1, daysInMonth - 1)) * plotWidth;
      return `
        <line x1="${x}" x2="${x}" y1="${margin.top}" y2="${height - margin.bottom}" stroke="rgba(255,255,255,0.05)"></line>
        <text x="${x}" y="${height - 20}" fill="rgba(222,232,247,0.72)" font-size="13" text-anchor="middle">${day}日</text>
      `;
    }).join("");

  const offsetByType = {
    plant: -10,
    water: -4,
    harvest: 4,
    theft: 10,
    raid: 16,
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
        stroke="#14171d"
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
    <rect x="${margin.left}" y="${margin.top}" width="${plotWidth}" height="${plotHeight}" rx="18" fill="rgba(23,26,34,0.84)" stroke="rgba(255,255,255,0.05)"></rect>
    ${gridLines}
    ${xTicks}
    ${dots}
    <text x="${margin.left + plotWidth / 2}" y="${height - 6}" fill="rgba(222,232,247,0.72)" font-size="13" text-anchor="middle">${monthKey.replace("-", " 年 ") + " 月"}</text>
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
    <div class="stack-item"><strong>偷菜事件</strong><div class="muted">被偷 ${visibleCounts.theft} · 偷别人 ${visibleCounts.raid}</div></div>
    <div class="stack-item"><strong>最活跃时段</strong><div class="muted">${pad(hotHour)}:00</div></div>
  `;
}

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
}

function renderRaidsAndSettings() {
  renderRaidList();
  hydrateSettings();
}

function renderAll() {
  renderCropDatalist();
  renderSidebar();
  renderTopbar();
  renderHome();
  renderFarmSummary();
  renderFarmEditor();
  renderFarmLayout();
  renderPlanner();
  renderStats();
  renderRaidsAndSettings();
  setSection(state.ui.section);

  if (state.ui.inboundCropId) setCropInputValue("inbound-crop-search", "inbound-crop-id", state.ui.inboundCropId);
  if (state.ui.outboundCropId) setCropInputValue("outbound-crop-search", "outbound-crop-id", state.ui.outboundCropId);
  if (state.ui.farmEditorCropId) setCropInputValue("farm-edit-crop-search", "farm-edit-crop-id", state.ui.farmEditorCropId);
}

async function bootstrap() {
  const dashboard = await request("/api/bootstrap");
  applyDashboard(dashboard);
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
  applyDashboard(response.dashboard);
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

function bindNavigation() {
  document.querySelector(".nav-stack").addEventListener("click", (event) => {
    const button = event.target.closest(".nav-item");
    if (!button) return;
    setSection(button.dataset.section);
  });
}

function bindCropInputs() {
  attachCropSearch("planner-crop-search", "planner-crop-id", (cropId) => { state.ui.plannerCropId = cropId; });
  attachCropSearch("farm-edit-crop-search", "farm-edit-crop-id", (cropId) => { state.ui.farmEditorCropId = cropId; });
  attachCropSearch("inbound-crop-search", "inbound-crop-id", (cropId) => { state.ui.inboundCropId = cropId; });
  attachCropSearch("outbound-crop-search", "outbound-crop-id", (cropId) => { state.ui.outboundCropId = cropId; });
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
    }
    renderFarmEditor();
    renderFarmLayout();
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
    };
    const response = await request("/api/slots/update", {
      method: "POST",
      body: JSON.stringify(payload),
    });
    applyDashboard(response.dashboard);
    renderAll();
    document.getElementById("farm-editor-feedback").textContent = "所选范围已更新，预计收入和花费已经重新计算。";
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
    document.getElementById("farm-editor-feedback").textContent = `已手动开始种植 ${response.result.processed_count} 格。`;
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
    document.getElementById("farm-editor-feedback").textContent = `已登记收获 ${response.result.processed_count} 格。钱包流水已更新。`;
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
    renderAll();
    document.getElementById("farm-editor-feedback").textContent = `已清空 ${response.cleared} 个格子的规划/状态。`;
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
  const setNow = () => {
    const now = new Date();
    now.setSeconds(0, 0);
    return now.toISOString().slice(0, 16);
  };
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
}

document.addEventListener("DOMContentLoaded", async () => {
  bindNavigation();
  bindCropInputs();
  bindPlanner();
  bindFarm();
  bindStats();
  bindRaidForms();
  bindSettings();
  await bootstrap();
});
