// 카테고리 색상: dataviz 팔레트 검증(validate_palette.js) 통과한 고정 순서 7색 + 기타(회색) + 에러(상태색·적색)
// 순서를 바꾸면 인접 색상의 색약 구분성(CVD ΔE)이 깨질 수 있으므로 임의로 재배열하지 않는다.
const CATEGORY_COLORS = {
  "휴가/휴직": "#007dfd",
  "근태/근무형태": "#eb6834",
  "급여/보수": "#1c9bae",
  "채용/임용": "#eda100",
  "인사/승진": "#4a3aa7",
  "복리후생": "#92bc58",
  "징계/행동강령": "#e87ba4",
  "기타": "#898781",
  "에러": "#d03b3b",
};

const INK_600 = "#4b5063";
const INK_400 = "#8a8f9e";
const LINE_200 = "#e2e4ea";
const NAVY_900 = "#1c2b48";
const ACCENT_600 = "#007dfd";

Chart.defaults.font.family = "'Noto Sans KR', -apple-system, BlinkMacSystemFont, sans-serif";
Chart.defaults.color = INK_600;

document.addEventListener("DOMContentLoaded", async function () {
  const res = await fetch("/admin/stats/api/summary");
  if (!res.ok) return;

  const data = await res.json();

  renderStatCards(data.user_summary);
  renderCategoryDonut(data.category_ratio);
  renderDailyTrend(data.daily_trend);
  renderFaqTable(data.faq_top10);
});

function escapeHtml(text) {
  const div = document.createElement("div");
  div.textContent = text;
  return div.innerHTML;
}

function renderStatCards(summary) {
  const container = document.getElementById("stat-cards");

  const cards = [
    { label: "총 질문 수", value: `${summary.total_questions}건` },
    { label: "활성 유저 수", value: `${summary.active_users}명` },
    { label: "유저당 평균 질문 수", value: `${summary.avg_per_user}건` },
    { label: "최다 질문 유저", value: `${escapeHtml(summary.top_user_name)} (${summary.top_user_count}건)` },
  ];

  container.innerHTML = cards.map(c => `
        <div class="stat-card">
            <div class="stat-card-label">${c.label}</div>
            <div class="stat-card-value">${c.value}</div>
        </div>
    `).join("");
}

// 도넛 중앙에 총 문의 건수를 표시하는 플러그인. 범례 없이도 전체 규모를 한눈에 읽을 수 있게 한다.
function buildCenterTextPlugin(total) {
  return {
    id: "donut-center-text",
    afterDraw(chart) {
      const { ctx, chartArea } = chart;
      if (!chartArea) return;

      const x = (chartArea.left + chartArea.right) / 2;
      const y = (chartArea.top + chartArea.bottom) / 2;

      ctx.save();
      ctx.textAlign = "center";
      ctx.textBaseline = "middle";

      ctx.font = "700 24px 'Noto Sans KR', sans-serif";
      ctx.fillStyle = NAVY_900;
      ctx.fillText(`${total}`, x, y - 10);

      ctx.font = "400 11px 'Noto Sans KR', sans-serif";
      ctx.fillStyle = INK_400;
      ctx.fillText("전체 문의", x, y + 13);

      ctx.restore();
    },
  };
}

function renderCategoryDonut(items) {
  const ctx = document.getElementById("category-donut");
  const colors = items.map(i => CATEGORY_COLORS[i.category] || CATEGORY_COLORS["기타"]);
  const total = items.reduce((sum, i) => sum + i.count, 0);

  new Chart(ctx, {
    type: "doughnut",
    data: {
      labels: items.map(i => i.category),
      datasets: [{
        data: items.map(i => i.count),
        backgroundColor: colors,
        borderColor: "#ffffff",
        borderWidth: 2,
        hoverOffset: 6,
      }],
    },
    options: {
      cutout: "68%",
      maintainAspectRatio: false,
      animation: { animateRotate: true, duration: 500 },
      plugins: {
        legend: { display: false },
        tooltip: {
          backgroundColor: NAVY_900,
          titleFont: { size: 13, weight: "600" },
          bodyFont: { size: 13 },
          padding: 10,
          cornerRadius: 8,
          displayColors: true,
          boxPadding: 4,
          callbacks: {
            label: function (ctx) {
              const item = items[ctx.dataIndex];
              return `${item.category}: ${item.count}건 (${item.percent}%)`;
            },
          },
        },
      },
    },
    plugins: [buildCenterTextPlugin(total)],
  });

  const legend = document.getElementById("category-legend");

  if (!items.length) {
    legend.innerHTML = `<li class="legend-empty">데이터가 없습니다</li>`;
    return;
  }

  legend.innerHTML = items.map((item, idx) => `
        <li>
            <span class="legend-dot" style="background:${colors[idx]}"></span>
            <span class="legend-name">${escapeHtml(item.category)}</span>
            <span class="legend-value">${item.percent}%<span class="legend-count">${item.count}건</span></span>
        </li>
    `).join("");
}

// 꺾은선 그래프의 최고점 위에 값을 직접 라벨링해 추세의 정점을 바로 읽을 수 있게 한다.
function buildPeakLabelPlugin(items) {
  const maxCount = Math.max(0, ...items.map(i => i.count));

  return {
    id: "line-peak-label",
    afterDatasetsDraw(chart) {
      if (maxCount <= 0) return;

      const { ctx } = chart;
      const meta = chart.getDatasetMeta(0);
      const peakIndex = items.findIndex(i => i.count === maxCount);
      if (peakIndex === -1 || !meta.data[peakIndex]) return;

      const point = meta.data[peakIndex];
      ctx.save();
      ctx.textAlign = "center";
      ctx.font = "700 12px 'Noto Sans KR', sans-serif";
      ctx.fillStyle = NAVY_900;
      ctx.fillText(`${maxCount}건`, point.x, point.y - 12);
      ctx.restore();
    },
  };
}

function renderDailyTrend(items) {
  const canvas = document.getElementById("daily-trend-line");
  const ctx = canvas.getContext("2d");

  const gradient = ctx.createLinearGradient(0, 0, 0, canvas.parentElement.clientHeight || 260);
  gradient.addColorStop(0, "rgba(0, 125, 253, 0.22)");
  gradient.addColorStop(1, "rgba(0, 125, 253, 0.02)");

  new Chart(ctx, {
    type: "line",
    data: {
      labels: items.map(i => i.date),
      datasets: [{
        data: items.map(i => i.count),
        borderColor: ACCENT_600,
        backgroundColor: gradient,
        borderWidth: 2,
        pointRadius: 4,
        pointHoverRadius: 6,
        pointBackgroundColor: ACCENT_600,
        pointBorderColor: "#ffffff",
        pointBorderWidth: 2,
        fill: true,
        tension: 0.3,
      }],
    },
    options: {
      maintainAspectRatio: false,
      interaction: { mode: "index", intersect: false },
      plugins: {
        legend: { display: false },
        tooltip: {
          backgroundColor: NAVY_900,
          titleFont: { size: 12, weight: "600" },
          bodyFont: { size: 13, weight: "700" },
          padding: 10,
          cornerRadius: 8,
          displayColors: false,
          callbacks: {
            title: (ctxItems) => `${ctxItems[0].label}`,
            label: (ctxItem) => `문의 ${ctxItem.parsed.y}건`,
          },
        },
      },
      scales: {
        x: {
          grid: { display: false },
          ticks: { color: INK_400, font: { size: 11 }, maxRotation: 0, autoSkipPadding: 12 },
        },
        y: {
          beginAtZero: true,
          ticks: { precision: 0, color: INK_400, font: { size: 11 }, padding: 8 },
          grid: { color: LINE_200 },
          border: { display: false },
        },
      },
    },
    plugins: [buildPeakLabelPlugin(items)],
  });
}

function renderFaqTable(items) {
  const tbody = document.getElementById("faq-list");

  if (!items.length) {
    tbody.innerHTML = `<tr><td colspan="4" class="empty-cell">아직 문의 데이터가 없습니다.</td></tr>`;
    return;
  }

  tbody.innerHTML = items.map(item => `
        <tr>
            <td>${item.rank}</td>
            <td>${escapeHtml(item.message)}</td>
            <td><span class="badge badge-category">${escapeHtml(item.category)}</span></td>
            <td>${item.count}</td>
        </tr>
    `).join("");
}
