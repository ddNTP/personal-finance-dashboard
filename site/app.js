(() => {
  const state = { data: null, viewId: "combined", sourceId: "platform", counterpartyYear: "all" };
  const CURRENCY = new Intl.NumberFormat("zh-CN", { style: "currency", currency: "CNY", minimumFractionDigits: 2, maximumFractionDigits: 2 });
  const NUMBER = new Intl.NumberFormat("zh-CN");

  const $ = (selector) => document.querySelector(selector);
  const escapeHtml = (value) => String(value ?? "").replace(/[&<>"']/g, (char) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[char]));
  const money = (value) => CURRENCY.format(Number(value || 0));
  const compactMoney = (value) => {
    const number = Number(value || 0);
    const sign = number < 0 ? "-" : "";
    const absolute = Math.abs(number);
    if (absolute >= 10000) return `${sign}¥${(absolute / 10000).toFixed(1)}万`;
    return `${sign}¥${Math.round(absolute).toLocaleString("zh-CN")}`;
  };
  const count = (value) => NUMBER.format(Number(value || 0));
  const signedClass = (value) => Number(value) >= 0 ? "positive" : "negative";

  function renderError(error) {
    const message = `数据加载失败：${escapeHtml(error?.message || "无法读取 summary.json")}`;
    ["metrics", "trendChart", "trendTable", "categoryChart", "incomeChart", "counterpartyChart", "yearlyTable", "insights"].forEach((id) => {
      const node = document.getElementById(id);
      if (node) node.innerHTML = `<div class="error-box">${message}</div>`;
    });
  }

  function fillAccountSelect() {
    const select = $("#accountSelect");
    const options = state.data.meta.view_options || [{ id: "combined", label: "支付平台合计", description: "微信支付 + 支付宝" }];
    select.innerHTML = options.map((option) => {
      const view = state.data.views[option.id];
      const records = view ? count(view.metrics.records) : "0";
      return `<option value="${escapeHtml(option.id)}">${escapeHtml(option.label)} · ${records} 条</option>`;
    }).join("");
    select.value = state.viewId;
    select.addEventListener("change", () => {
      state.viewId = select.value;
      state.sourceId = "platform";
      state.counterpartyYear = "all";
      fillSourceSelect();
      render();
    });
  }

  function fillSourceSelect() {
    const select = $("#sourceSelect");
    if (!select || !state.data) return;
    const options = state.data.meta.source_options || [];
    const available = options.filter((option) => {
      const viewId = option.id === "platform"
        ? state.viewId
        : state.viewId === "combined"
          ? option.id
          : `${state.viewId}:${option.id === "bank" ? "cmb" : option.id}`;
      return Boolean(state.data.views[viewId]);
    });
    if (!available.some((option) => option.id === state.sourceId)) state.sourceId = "platform";
    select.innerHTML = available.map((option) => `<option value="${escapeHtml(option.id)}">${escapeHtml(option.label)}</option>`).join("");
    select.value = state.sourceId;
  }

  function resolveView() {
    const sourceId = state.sourceId;
    const viewId = sourceId === "platform"
      ? state.viewId
      : state.viewId === "combined"
        ? sourceId
        : `${state.viewId}:${sourceId === "bank" ? "cmb" : sourceId}`;
    return state.data.views[viewId] || state.data.views[state.viewId] || state.data.views.combined;
  }

  function renderCounterpartyYearOptions(view) {
    const select = $("#counterpartyYear");
    if (!select) return;
    const years = new Set();
    (view.counterparties || []).forEach((item) => Object.keys(item.years || {}).forEach((year) => years.add(year)));
    const options = ["<option value=\"all\">全部年度</option>", ...Array.from(years).sort().map((year) => `<option value=\"${escapeHtml(year)}\">${escapeHtml(year)} 年</option>`)];
    select.innerHTML = options.join("");
    if (!years.has(state.counterpartyYear)) state.counterpartyYear = "all";
    select.value = state.counterpartyYear;
  }

  function renderMeta(view) {
    const meta = state.data.meta;
    $("#coverage").textContent = `${view.date_start || meta.date_start} — ${view.date_end || meta.date_end}`;
    $("#freshness").textContent = `${count(view.metrics.records)} 条记录 · ${view.label}${view.source_label ? ` · ${view.source_label}` : ""}`;
    const bankRange = meta.bank_date_start ? ` · 银行流水单独覆盖 ${meta.bank_date_start} — ${meta.bank_date_end}` : "";
    $("#methodMeta").textContent = `生成时间：${new Date(state.data.generated_at).toLocaleString("zh-CN", { timeZone: "Asia/Shanghai" })} · 来源文件 ${meta.source_file_count} 份 · 支付平台记录 ${count(meta.platform_record_count)} 条${bankRange}`;
  }

  function renderMetrics(view) {
    const m = view.metrics;
    const cards = [
      { label: "总收入", value: money(m.gross_income), foot: `不含退款收入 ${money(m.income_ex_refunds)}` },
      { label: "总支出", value: money(m.gross_expense), foot: `其中转账/红包 ${money(m.transfer_like_expense)}` },
      { label: "净现金流", value: money(m.net_cashflow), foot: "账单收入减支出 · 方向性净额", className: signedClass(m.net_cashflow) },
      { label: "有效消费", value: money(m.consumption), foot: `${count(m.consumption_count)} 笔 · 已扣除退款` },
      { label: "退款回流", value: money(m.refunds), foot: "按收入方向单独统计" },
    ];
    $("#metrics").innerHTML = cards.map((card) => `
      <article class="kpi">
        <div class="kpi-label">${escapeHtml(card.label)}</div>
        <div class="kpi-value ${card.className || ""}">${escapeHtml(card.value)}</div>
        <div class="kpi-foot">${escapeHtml(card.foot)}</div>
      </article>`).join("");
  }

  function chartPath(rows, key, scaleX, scaleY) {
    return rows.map((row, index) => `${index === 0 ? "M" : "L"} ${scaleX(index).toFixed(1)} ${scaleY(Number(row[key] || 0)).toFixed(1)}`).join(" ");
  }

  function renderTrend(view) {
    const rows = view.monthly || [];
    if (!rows.length) { $("#trendChart").innerHTML = `<div class="empty">暂无月度数据</div>`; return; }
    const width = 1000;
    const height = 330;
    const left = 58;
    const right = 24;
    const top = 18;
    const bottom = 46;
    const innerWidth = width - left - right;
    const innerHeight = height - top - bottom;
    const maxValue = Math.max(1, ...rows.flatMap((row) => [row.income, row.expense, row.consumption]));
    const scaleX = (index) => rows.length === 1 ? left + innerWidth / 2 : left + index * innerWidth / (rows.length - 1);
    const scaleY = (value) => top + innerHeight - (value / maxValue) * innerHeight;
    const lines = [
      { key: "income", className: "income" },
      { key: "expense", className: "expense" },
      { key: "consumption", className: "consumption" },
    ];
    const grid = [0, 0.25, 0.5, 0.75, 1].map((ratio) => {
      const y = top + innerHeight * (1 - ratio);
      return `<line class="chart-gridline" x1="${left}" x2="${width - right}" y1="${y}" y2="${y}"/><text class="chart-axis-label" x="${left - 11}" y="${y + 4}" text-anchor="end">${escapeHtml(compactMoney(maxValue * ratio))}</text>`;
    }).join("");
    const step = Math.max(1, Math.ceil(rows.length / 8));
    const xLabels = rows.map((row, index) => {
      if (index % step !== 0 && index !== rows.length - 1) return "";
      const label = row.month.slice(0, 7);
      return `<text class="chart-x-label" x="${scaleX(index)}" y="${height - 12}" text-anchor="middle">${escapeHtml(label)}</text>`;
    }).join("");
    const paths = lines.map((line) => `<path class="chart-line ${line.className}" d="${chartPath(rows, line.key, scaleX, scaleY)}"/>`).join("");
    const dots = lines.map((line) => rows.map((row, index) => `<circle class="chart-dot ${line.className}" cx="${scaleX(index)}" cy="${scaleY(Number(row[line.key] || 0))}" r="${index === rows.length - 1 ? 4 : 2.6}"><title>${escapeHtml(row.month)} ${escapeHtml(line.key === "income" ? "收入" : line.key === "expense" ? "支出" : "有效消费")} ${escapeHtml(money(row[line.key]))}</title></circle>`).join("")).join("");
    $("#trendChart").innerHTML = `<svg viewBox="0 0 ${width} ${height}" role="img" aria-label="月度收入、支出和有效消费趋势图"><title>月度收入、支出和有效消费趋势</title>${grid}<line class="chart-gridline" x1="${left}" x2="${width - right}" y1="${top + innerHeight}" y2="${top + innerHeight}"/>${paths}${dots}${xLabels}</svg>`;

    const latest = rows.slice(-6).reverse();
    $("#trendTable").innerHTML = `<table class="trend-table"><thead><tr><th>月份</th><th>收入</th><th>支出</th><th>有效消费</th><th>净现金流</th></tr></thead><tbody>${latest.map((row) => `<tr><td>${escapeHtml(row.month)}</td><td>${escapeHtml(money(row.income))}</td><td>${escapeHtml(money(row.expense))}</td><td>${escapeHtml(money(row.consumption))}</td><td class="${Number(row.net_cashflow) >= 0 ? "up" : "down"}">${escapeHtml(money(row.net_cashflow))}</td></tr>`).join("")}</tbody></table>`;
  }

  function renderBars(containerId, items, warm = false, maxItems = 8) {
    const container = $(containerId);
    if (!items?.length) { container.innerHTML = `<div class="empty">暂无数据</div>`; return; }
    const visible = items.slice(0, maxItems);
    const max = Math.max(1, visible[0].amount);
    container.innerHTML = visible.map((item) => `
      <div class="bar-row">
        <div class="bar-label-line"><span>${escapeHtml(item.label)}</span><strong>${escapeHtml(money(item.amount))}</strong></div>
        <div class="bar-track"><div class="bar-fill ${warm ? "warm" : ""}" style="width: ${Math.max(1.5, item.amount / max * 100)}%"></div></div>
        <div class="bar-foot"><span>${count(item.count)} 笔</span><span>${(Number(item.share || 0) * 100).toFixed(1)}%</span></div>
      </div>`).join("");
  }

  function renderBreakdowns(view) {
    renderBars("#categoryChart", view.categories, false, 8);
    renderBars("#incomeChart", view.income_sources, true, 6);
    const categoryTotal = view.metrics.consumption;
    const incomeTotal = view.metrics.gross_income;
    const sourceHint = view.id === "bank" ? "招商银行流水与微信/支付宝保持分开，避免快捷支付重复记账。" : "转账和红包单列，不挤入日常消费类别。";
    $("#categoryFootnote").textContent = `共 ${count(view.metrics.consumption_count)} 笔消费，调整后合计 ${money(categoryTotal)}。${sourceHint}`;
    $("#incomeFootnote").textContent = `总收入 ${money(incomeTotal)}，已识别退款 ${money(view.metrics.refunds)}；中性退款会从有效消费总额中扣除。`;
  }

  function renderCounterparties(view) {
    const container = $("#counterpartyChart");
    const footnote = $("#counterpartyFootnote");
    renderCounterpartyYearOptions(view);
    const items = view.counterparties || [];
    if (!items.length) {
      container.innerHTML = `<div class="empty">当前来源没有可拆分的转账对象</div>`;
      footnote.textContent = "银行快捷支付与支付平台分开展示；切换账户或支付平台来源查看对应的转账对象。";
      return;
    }
    const year = state.counterpartyYear;
    const rows = items.map((item) => {
      const detail = year === "all" ? item : (item.years?.[year] || { income: 0, expense: 0, net: 0, count: 0 });
      return { label: item.label, income: Number(detail.income || 0), expense: Number(detail.expense || 0), net: Number(detail.net || 0), count: Number(detail.count || 0) };
    }).filter((item) => item.count > 0).sort((a, b) => Math.abs(b.net) - Math.abs(a.net));
    const visible = rows.slice(0, 12);
    const maxAbs = Math.max(1, ...visible.map((item) => Math.abs(item.net)));
    container.innerHTML = visible.map((item) => {
      const tone = item.net >= 0 ? "positive" : "negative";
      const width = Math.max(1.5, Math.abs(item.net) / maxAbs * 100);
      return `<div class="counterparty-row">
        <div class="counterparty-name" title="${escapeHtml(item.label)}">${escapeHtml(item.label)}</div>
        <div class="counterparty-track"><div class="counterparty-bar"><span class="${tone}" style="width:${width}%"></span></div><div class="counterparty-meta"><span>收入 ${escapeHtml(money(item.income))}</span><span>支出 ${escapeHtml(money(item.expense))}</span></div></div>
        <div class="counterparty-net ${tone}">${escapeHtml(money(item.net))}<small> · ${count(item.count)} 笔</small></div>
      </div>`;
    }).join("");
    const scope = year === "all" ? "全部年度" : `${year} 年`;
    footnote.textContent = `当前视图：${view.label} · ${scope} · 按净流入绝对值排序，展示前 ${visible.length} 个对象；正数表示流入更多，负数表示流出更多。`;
  }

  function renderYearly(view) {
    const rows = view.yearly || [];
    $("#yearlyTable").innerHTML = rows.length ? `<table class="data-table"><thead><tr><th>年度</th><th>收入</th><th>支出</th><th>消费</th><th>净额</th></tr></thead><tbody>${rows.map((row) => `<tr><td class="emphasis">${escapeHtml(row.label)}</td><td>${escapeHtml(money(row.income))}</td><td>${escapeHtml(money(row.expense))}</td><td>${escapeHtml(money(row.consumption))}</td><td class="${Number(row.net_cashflow) >= 0 ? "up" : "down"}">${escapeHtml(money(row.net_cashflow))}</td></tr>`).join("")}</tbody></table>` : `<div class="empty">暂无年度数据</div>`;
  }

  function renderInsights(view) {
    const insights = view.insights || [];
    $("#insights").innerHTML = insights.length ? insights.map((item) => `<div class="insight"><div><div class="insight-title">${escapeHtml(item.title)}</div><div class="insight-value">${escapeHtml(item.value)}</div></div><div class="insight-detail">${escapeHtml(item.detail)}</div></div>`).join("") : `<div class="empty">暂无洞察</div>`;
  }

  function render() {
    const view = resolveView();
    renderMeta(view);
    renderMetrics(view);
    renderTrend(view);
    renderBreakdowns(view);
    renderCounterparties(view);
    renderYearly(view);
    renderInsights(view);
  }

  async function init() {
    try {
      const response = await fetch("data/summary.json", { cache: "no-store" });
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      state.data = await response.json();
      fillAccountSelect();
      fillSourceSelect();
      const sourceSelect = $("#sourceSelect");
      if (sourceSelect) sourceSelect.addEventListener("change", () => { state.sourceId = sourceSelect.value; state.counterpartyYear = "all"; render(); });
      const counterpartyYear = $("#counterpartyYear");
      if (counterpartyYear) counterpartyYear.addEventListener("change", () => { state.counterpartyYear = counterpartyYear.value; render(); });
      render();
    } catch (error) {
      renderError(error);
      console.error(error);
    }
  }

  init();
})();
