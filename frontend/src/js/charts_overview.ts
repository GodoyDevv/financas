/**
 * frontend/src/js/charts_overview.ts
 *
 * Gráficos analíticos: Distribuição por Categoria e Balanço Financeiro.
 */
import { Chart } from "chart.js";
import { formatBRL } from "./format";
import type { MetricsResponse } from "./state";

let chartCategoriasInstance: Chart | null = null;
let chartBalancoInstance: Chart | null = null;

const PALETA_CATEGORIAS = [
  "#3B82F6",
  "#10B981",
  "#F59E0B",
  "#EC4899",
  "#8B5CF6",
  "#06B6D4",
  "#F97316",
  "#14B8A6",
  "#6366F1",
  "#64748B",
];

export function renderChartCategorias(metrics: MetricsResponse | null): void {
  const containerCat = document.getElementById("container-chart-categorias");
  if (!containerCat || !metrics) return;

  const categorias = metrics.categorias || [];
  const totalDespesas = (metrics.contas_fixas || 0) + (metrics.gastos_whatsapp || 0);

  const badgeTopCat = document.getElementById("badge-top-cat");
  if (categorias && categorias.length > 0 && badgeTopCat) {
    badgeTopCat.innerText = `Top: ${categorias[0].categoria} (${categorias[0].percentual}%)`;
  } else if (badgeTopCat) {
    badgeTopCat.innerText = "Top: -";
  }

  if (!categorias || categorias.length === 0 || totalDespesas <= 0) {
    if (chartCategoriasInstance) {
      chartCategoriasInstance.destroy();
      chartCategoriasInstance = null;
    }
    containerCat.innerHTML = `
      <div class="chart-empty">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8">
          <circle cx="12" cy="12" r="10"></circle>
          <line x1="8" y1="12" x2="16" y2="12"></line>
        </svg>
        <div>Nenhuma despesa para exibir no gráfico</div>
      </div>
    `;
  } else {
    let canvasCat = document.getElementById("chart-categorias") as HTMLCanvasElement | null;
    if (!canvasCat) {
      containerCat.innerHTML = '<canvas id="chart-categorias"></canvas>';
      canvasCat = document.getElementById("chart-categorias") as HTMLCanvasElement | null;
    }
    if (!canvasCat) return;

    const labelsCat = categorias.map((c) => c.categoria);
    const dataCat = categorias.map((c) => c.total);
    const colorsCat = categorias.map(
      (_, idx) => PALETA_CATEGORIAS[idx % PALETA_CATEGORIAS.length]
    );

    if (chartCategoriasInstance) {
      chartCategoriasInstance.data.labels = labelsCat;
      chartCategoriasInstance.data.datasets[0].data = dataCat;
      chartCategoriasInstance.data.datasets[0].backgroundColor = colorsCat;
      chartCategoriasInstance.update();
    } else {
      const ctxCat = canvasCat.getContext("2d");
      if (!ctxCat) return;

      chartCategoriasInstance = new Chart(ctxCat, {
        type: "doughnut",
        data: {
          labels: labelsCat,
          datasets: [
            {
              data: dataCat,
              backgroundColor: colorsCat,
              borderColor: "#1E293B",
              borderWidth: 2,
              hoverOffset: 6,
            },
          ],
        },
        options: {
          responsive: true,
          maintainAspectRatio: false,
          plugins: {
            legend: {
              position: "right",
              labels: {
                color: "#CBD5E1",
                font: { size: 12, family: "'Plus Jakarta Sans', sans-serif" },
                padding: 12,
                boxWidth: 12,
                boxHeight: 12,
                usePointStyle: true,
                pointStyle: "circle",
              },
            },
            tooltip: {
              backgroundColor: "#1E293B",
              titleColor: "#F8FAFC",
              bodyColor: "#E2E8F0",
              borderColor: "rgba(255, 255, 255, 0.1)",
              borderWidth: 1,
              padding: 10,
              boxPadding: 4,
              callbacks: {
                label: function (context) {
                  const val = context.raw as number;
                  const pct = totalDespesas > 0 ? ((val / totalDespesas) * 100).toFixed(1) : 0;
                  return ` ${context.label}: ${formatBRL(val)} (${pct}%)`;
                },
              },
            },
          },
          cutout: "68%",
        },
      });
    }
  }
}

export function renderChartBalanco(metrics: MetricsResponse | null): void {
  const containerBalanco = document.getElementById("container-chart-balanco");
  if (!containerBalanco || !metrics) return;

  const totalReceitas = metrics.receitas_totais || 0;
  const totalFixas = metrics.contas_fixas || 0;
  const totalWhatsapp = metrics.gastos_whatsapp || 0;

  const badgeBalanco = document.getElementById("badge-balanco");
  if (badgeBalanco) {
    const economizado = totalReceitas - (totalFixas + totalWhatsapp);
    if (totalReceitas > 0) {
      const pctLivre = Math.round((economizado / totalReceitas) * 100);
      badgeBalanco.innerText = `Livre: ${pctLivre}% (${formatBRL(economizado)})`;
      badgeBalanco.style.color =
        economizado >= 0 ? "var(--accent-emerald)" : "var(--accent-red)";
    } else {
      badgeBalanco.innerText = "Sem receitas";
      badgeBalanco.style.color = "var(--text-dim)";
    }
  }

  if (totalReceitas === 0 && totalFixas === 0 && totalWhatsapp === 0) {
    if (chartBalancoInstance) {
      chartBalancoInstance.destroy();
      chartBalancoInstance = null;
    }
    containerBalanco.innerHTML = `
      <div class="chart-empty">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8">
          <circle cx="12" cy="12" r="10"></circle>
          <line x1="8" y1="12" x2="16" y2="12"></line>
        </svg>
        <div>Nenhuma movimentao para exibir no balano</div>
      </div>
    `;
  } else {
    let canvasBalanco = document.getElementById("chart-balanco") as HTMLCanvasElement | null;
    if (!canvasBalanco) {
      containerBalanco.innerHTML = '<canvas id="chart-balanco"></canvas>';
      canvasBalanco = document.getElementById("chart-balanco") as HTMLCanvasElement | null;
    }
    if (!canvasBalanco) return;

    const labelsBalanco = ["Receitas", "Contas Fixas", "Variveis"];
    const valuesBalanco = [totalReceitas, totalFixas, totalWhatsapp];

    if (chartBalancoInstance) {
      chartBalancoInstance.data.labels = labelsBalanco;
      chartBalancoInstance.data.datasets[0].data = valuesBalanco;
      chartBalancoInstance.update();
    } else {
      const ctxBalanco = canvasBalanco.getContext("2d");
      if (!ctxBalanco) return;

      chartBalancoInstance = new Chart(ctxBalanco, {
        type: "bar",
        data: {
          labels: labelsBalanco,
          datasets: [
            {
              label: "Total (R$)",
              data: valuesBalanco,
              backgroundColor: [
                "rgba(16, 185, 129, 0.85)", // Verde
                "rgba(245, 158, 11, 0.85)", // Ambar
                "rgba(236, 72, 153, 0.85)", // Rosa
              ],
              borderColor: ["#10B981", "#F59E0B", "#EC4899"],
              borderWidth: 1.5,
              borderRadius: 8,
              borderSkipped: false,
              barPercentage: 0.55,
            },
          ],
        },
        options: {
          responsive: true,
          maintainAspectRatio: false,
          plugins: {
            legend: {
              display: false,
            },
            tooltip: {
              backgroundColor: "#1E293B",
              titleColor: "#F8FAFC",
              bodyColor: "#E2E8F0",
              borderColor: "rgba(255, 255, 255, 0.1)",
              borderWidth: 1,
              padding: 10,
              boxPadding: 4,
              callbacks: {
                label: function (context) {
                  return ` Valor: ${formatBRL(context.raw)}`;
                },
              },
            },
          },
          scales: {
            x: {
              grid: {
                display: false,
              },
              ticks: {
                color: "#CBD5E1",
                font: { weight: "bold", size: 12 },
              },
            },
            y: {
              grid: {
                color: "rgba(255, 255, 255, 0.05)",
              },
              ticks: {
                color: "#94A3B8",
                callback: function (val) {
                  const num = Number(val);
                  return "R$ " + (num >= 1000 ? (num / 1000).toFixed(1) + "k" : String(num));
                },
              },
            },
          },
        },
      });
    }
  }
}
