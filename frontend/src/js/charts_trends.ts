/**
 * frontend/src/js/charts_trends.ts
 *
 * Gráficos analíticos: Divisão do Casal, Maiores Ofensores e Evolução Diária.
 */
import { Chart } from "chart.js";
import { formatBRL, formatDateBR } from "./format";
import type { TransactionResponse } from "./state";

let chartCasalInstance: Chart | null = null;
let chartOfensoresInstance: Chart | null = null;
let chartDiasInstance: Chart | null = null;

function normalizarNomePessoa(source: unknown): string {
  if (!source) return "Manual";
  const s = String(source).trim();
  const sLower = s.toLowerCase();
  if (sLower.includes("let") || sLower.includes("tícia") || sLower.includes("ticia"))
    return "Letícia";
  if (sLower.includes("bruno")) return "Bruno";
  return s;
}

export function renderChartCasal(listaTrans: TransactionResponse[]): void {
  const containerCasal = document.getElementById("container-chart-casal");
  const badgeCasal = document.getElementById("badge-comparativo-lider");
  if (!containerCasal) return;

  const transCasal = listaTrans.filter(
    (t) =>
      (t.tipo === "despesa_variavel" || t.tipo === "despesa_fixa") &&
      (t.author || (t.source && t.source !== "Manual"))
  );

  let totalBruno = 0;
  let countBruno = 0;
  let totalLeticia = 0;
  let countLeticia = 0;

  transCasal.forEach((t) => {
    const nome = normalizarNomePessoa(t.author || t.source);
    const val = Number(t.valor || 0);
    if (nome === "Bruno") {
      totalBruno += val;
      countBruno += 1;
    } else if (nome === "Letícia") {
      totalLeticia += val;
      countLeticia += 1;
    }
  });

  const totalCasal = totalBruno + totalLeticia;

  if (badgeCasal) {
    if (totalBruno > totalLeticia) {
      badgeCasal.innerText = `Líder: Bruno (${formatBRL(totalBruno)})`;
      badgeCasal.style.color = "#3B82F6";
    } else if (totalLeticia > totalBruno) {
      badgeCasal.innerText = `Líder: Letícia (${formatBRL(totalLeticia)})`;
      badgeCasal.style.color = "#EC4899";
    } else if (totalCasal > 0) {
      badgeCasal.innerText = "Empate técnico";
      badgeCasal.style.color = "var(--text-dim)";
    } else {
      badgeCasal.innerText = "Sem gastos registrados";
      badgeCasal.style.color = "var(--text-dim)";
    }
  }

  const statBrunoVal = document.getElementById("stat-casal-bruno-val");
  const statBrunoCount = document.getElementById("stat-casal-bruno-count");
  const statLeticiaVal = document.getElementById("stat-casal-leticia-val");
  const statLeticiaCount = document.getElementById("stat-casal-leticia-count");

  if (statBrunoVal) statBrunoVal.innerText = formatBRL(totalBruno);
  if (statBrunoCount) statBrunoCount.innerText = `${countBruno} lançamentos`;
  if (statLeticiaVal) statLeticiaVal.innerText = formatBRL(totalLeticia);
  if (statLeticiaCount) statLeticiaCount.innerText = `${countLeticia} lançamentos`;

  if (totalCasal === 0) {
    if (chartCasalInstance) {
      chartCasalInstance.destroy();
      chartCasalInstance = null;
    }
    containerCasal.innerHTML = `
      <div class="chart-empty">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8">
          <path d="M17 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2"></path>
          <circle cx="9" cy="7" r="4"></circle>
          <path d="M23 21v-2a4 4 0 0 0-3-3.87"></path>
          <path d="M16 3.13a4 4 0 0 1 0 7.75"></path>
        </svg>
        <div>Nenhum gasto do casal registrado</div>
      </div>
    `;
  } else {
    let canvasCasal = document.getElementById("chart-casal") as HTMLCanvasElement | null;
    if (!canvasCasal) {
      containerCasal.innerHTML = '<canvas id="chart-casal"></canvas>';
      canvasCasal = document.getElementById("chart-casal") as HTMLCanvasElement | null;
    }
    if (!canvasCasal) return;

    const dataCasal = [totalBruno, totalLeticia];
    const labelsCasal = ["Bruno", "Letícia"];

    if (chartCasalInstance) {
      chartCasalInstance.data.datasets[0].data = dataCasal;
      chartCasalInstance.update();
    } else {
      const ctxCasal = canvasCasal.getContext("2d");
      if (!ctxCasal) return;

      chartCasalInstance = new Chart(ctxCasal, {
        type: "doughnut",
        data: {
          labels: labelsCasal,
          datasets: [
            {
              data: dataCasal,
              backgroundColor: [
                "#3B82F6", // Azul Bruno
                "#EC4899", // Rosa Letícia
              ],
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
              position: "bottom",
              labels: {
                color: "#CBD5E1",
                font: { size: 12, family: "'Plus Jakarta Sans', sans-serif" },
                padding: 14,
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
                  const pct = totalCasal > 0 ? ((val / totalCasal) * 100).toFixed(1) : 0;
                  return ` ${context.label}: ${formatBRL(val)} (${pct}%)`;
                },
              },
            },
          },
          cutout: "65%",
        },
      });
    }
  }
}

export function renderChartOfensores(listaTrans: TransactionResponse[]): void {
  const containerOfensores = document.getElementById("container-chart-ofensores");
  const badgeOfensorTop = document.getElementById("badge-maior-ofensor");
  if (!containerOfensores) return;

  const transVariaveis = listaTrans.filter((t) => t.tipo === "despesa_variavel");

  interface AggOfensor {
    total: number;
    count: number;
  }
  const agrupado: Record<string, AggOfensor> = {};

  transVariaveis.forEach((t) => {
    let chave = (t.descricao || t.categoria || "Outro").trim();
    chave = chave.charAt(0).toUpperCase() + chave.slice(1).toLowerCase();
    const val = Number(t.valor || 0);

    if (!agrupado[chave]) {
      agrupado[chave] = { total: 0, count: 0 };
    }
    agrupado[chave].total += val;
    agrupado[chave].count += 1;
  });

  const rankingOfensores = Object.entries(agrupado)
    .sort((a, b) => b[1].total - a[1].total)
    .slice(0, 5);

  if (rankingOfensores.length > 0 && badgeOfensorTop) {
    badgeOfensorTop.innerText = `1º: ${rankingOfensores[0][0]} (${formatBRL(rankingOfensores[0][1].total)})`;
  } else if (badgeOfensorTop) {
    badgeOfensorTop.innerText = "1º: -";
  }

  if (rankingOfensores.length === 0) {
    if (chartOfensoresInstance) {
      chartOfensoresInstance.destroy();
      chartOfensoresInstance = null;
    }
    containerOfensores.innerHTML = `
      <div class="chart-empty">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8">
          <path d="M13 2L3 14h9l-1 8 10-12h-9l1-8z"></path>
        </svg>
        <div>Nenhuma despesa variável encontrada</div>
      </div>
    `;
  } else {
    let canvasOfensores = document.getElementById("chart-ofensores") as HTMLCanvasElement | null;
    if (!canvasOfensores) {
      containerOfensores.innerHTML = '<canvas id="chart-ofensores"></canvas>';
      canvasOfensores = document.getElementById("chart-ofensores") as HTMLCanvasElement | null;
    }
    if (!canvasOfensores) return;

    const labelsOfensores = rankingOfensores.map(([desc, info]) => `${desc} (${info.count}x)`);
    const valuesOfensores = rankingOfensores.map(([_, info]) => info.total);

    if (chartOfensoresInstance) {
      chartOfensoresInstance.data.labels = labelsOfensores;
      chartOfensoresInstance.data.datasets[0].data = valuesOfensores;
      chartOfensoresInstance.update();
    } else {
      const ctxOfensores = canvasOfensores.getContext("2d");
      if (!ctxOfensores) return;

      chartOfensoresInstance = new Chart(ctxOfensores, {
        type: "bar",
        data: {
          labels: labelsOfensores,
          datasets: [
            {
              label: "Total Gasto (R$)",
              data: valuesOfensores,
              backgroundColor: "rgba(245, 158, 11, 0.85)", // Âmbar
              borderColor: "#F59E0B",
              borderWidth: 1.5,
              borderRadius: 7,
              barPercentage: 0.6,
            },
          ],
        },
        options: {
          indexAxis: "y",
          responsive: true,
          maintainAspectRatio: false,
          plugins: {
            legend: { display: false },
            tooltip: {
              backgroundColor: "#1E293B",
              titleColor: "#F8FAFC",
              bodyColor: "#E2E8F0",
              borderColor: "rgba(255, 255, 255, 0.1)",
              borderWidth: 1,
              padding: 10,
              callbacks: {
                label: function (context) {
                  return ` Gasto acumulado: ${formatBRL(context.raw)}`;
                },
              },
            },
          },
          scales: {
            x: {
              grid: { color: "rgba(255, 255, 255, 0.05)" },
              ticks: {
                color: "#94A3B8",
                callback: function (val) {
                  const num = Number(val);
                  return "R$ " + (num >= 1000 ? (num / 1000).toFixed(1) + "k" : String(num));
                },
              },
            },
            y: {
              grid: { display: false },
              ticks: {
                color: "#CBD5E1",
                font: { weight: "bold", size: 12 },
              },
            },
          },
        },
      });
    }
  }
}

export function renderChartDias(listaTrans: TransactionResponse[]): void {
  const containerDias = document.getElementById("container-chart-dias");
  const badgePicoDia = document.getElementById("badge-pico-dia");
  if (!containerDias) return;

  const transDespesas = listaTrans.filter(
    (t) => t.tipo === "despesa_variavel" || t.tipo === "despesa_fixa"
  );

  const diasAgrupados: Record<string, number> = {};
  transDespesas.forEach((t) => {
    if (!t.data) return;
    const diaFormatado = formatDateBR(t.data);
    const val = Number(t.valor || 0);
    diasAgrupados[diaFormatado] = (diasAgrupados[diaFormatado] || 0) + val;
  });

  const listaDias = Object.entries(diasAgrupados).sort((a, b) => {
    const parseData = (d: string) => {
      const p = d.split("/");
      return new Date(Number(p[2]), Number(p[1]) - 1, Number(p[0])).getTime();
    };
    return parseData(a[0]) - parseData(b[0]);
  });

  let maiorGastoDia = 0;
  let diaPico = "";
  listaDias.forEach(([dia, val]) => {
    if (val > maiorGastoDia) {
      maiorGastoDia = val;
      diaPico = dia;
    }
  });

  if (diaPico && badgePicoDia) {
    badgePicoDia.innerText = `Pico: ${diaPico} (${formatBRL(maiorGastoDia)})`;
  } else if (badgePicoDia) {
    badgePicoDia.innerText = "Pico: -";
  }

  if (listaDias.length === 0) {
    if (chartDiasInstance) {
      chartDiasInstance.destroy();
      chartDiasInstance = null;
    }
    containerDias.innerHTML = `
      <div class="chart-empty">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8">
          <rect x="3" y="4" width="18" height="18" rx="2" ry="2"></rect>
          <line x1="16" y1="2" x2="16" y2="6"></line>
          <line x1="8" y1="2" x2="8" y2="6"></line>
        </svg>
        <div>Nenhuma despesa diária para traçar o gráfico de consumo</div>
      </div>
    `;
  } else {
    let canvasDias = document.getElementById("chart-dias") as HTMLCanvasElement | null;
    if (!canvasDias) {
      containerDias.innerHTML = '<canvas id="chart-dias"></canvas>';
      canvasDias = document.getElementById("chart-dias") as HTMLCanvasElement | null;
    }
    if (!canvasDias) return;

    const labelsDias = listaDias.map(([dia]) => dia);
    const valuesDias = listaDias.map(([_, val]) => val);

    if (chartDiasInstance) {
      chartDiasInstance.data.labels = labelsDias;
      chartDiasInstance.data.datasets[0].data = valuesDias;
      chartDiasInstance.update();
    } else {
      const ctxDias = canvasDias.getContext("2d");
      if (!ctxDias) return;

      chartDiasInstance = new Chart(ctxDias, {
        type: "line",
        data: {
          labels: labelsDias,
          datasets: [
            {
              label: "Despesas no Dia (R$)",
              data: valuesDias,
              borderColor: "#06B6D4", // Ciano
              backgroundColor: "rgba(6, 182, 212, 0.12)",
              borderWidth: 2.5,
              fill: true,
              tension: 0.35,
              pointBackgroundColor: "#06B6D4",
              pointBorderColor: "#0B0F19",
              pointBorderWidth: 2,
              pointRadius: 5,
              pointHoverRadius: 7,
            },
          ],
        },
        options: {
          responsive: true,
          maintainAspectRatio: false,
          plugins: {
            legend: { display: false },
            tooltip: {
              backgroundColor: "#1E293B",
              titleColor: "#F8FAFC",
              bodyColor: "#E2E8F0",
              borderColor: "rgba(255, 255, 255, 0.1)",
              borderWidth: 1,
              padding: 10,
              callbacks: {
                label: function (context) {
                  return ` Total no dia: ${formatBRL(context.raw)}`;
                },
              },
            },
          },
          scales: {
            x: {
              grid: { display: false },
              ticks: {
                color: "#CBD5E1",
                font: { weight: "bold", size: 11.5 },
              },
            },
            y: {
              grid: { color: "rgba(255, 255, 255, 0.05)" },
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
