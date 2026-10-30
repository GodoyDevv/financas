/**
 * frontend/src/js/charts_trends.js
 *
 * Gr�ficos anal�ticos: Divis�o do Casal, Maiores Ofensores e Evolu��o Di�ria.
 */
import { formatBRL, formatDateBR } from './format.js';

let chartCasalInstance = null;
let chartOfensoresInstance = null;
let chartDiasInstance = null;

function normalizarNomePessoa(source) {
  if (!source) return 'Manual';
  const s = String(source).trim();
  const sLower = s.toLowerCase();
  if (sLower.includes('let') || sLower.includes('t�cia') || sLower.includes('ticia')) return 'Let�cia';
  if (sLower.includes('bruno')) return 'Bruno';
  return s;
}

export function renderChartCasal(listaTrans) {
      // -------------------------------------------------------------
      const containerCasal = document.getElementById('container-chart-casal');
      const badgeCasal = document.getElementById('badge-comparativo-lider');

      // Considera despesas de consumo do dia a dia inseridas via WhatsApp
      const transCasal = listaTrans.filter(t => (t.tipo === 'despesa_variavel' || t.tipo === 'despesa_fixa') && (t.author || (t.source && t.source !== 'Manual')));

      let totalBruno = 0;
      let countBruno = 0;
      let totalLeticia = 0;
      let countLeticia = 0;

      transCasal.forEach(t => {
        const nome = normalizarNomePessoa(t.author || t.source);
        const val = Number(t.valor || 0);
        if (nome === 'Bruno') {
          totalBruno += val;
          countBruno += 1;
        } else if (nome === 'Letícia') {
          totalLeticia += val;
          countLeticia += 1;
        }
      });

      const totalCasal = totalBruno + totalLeticia;

      if (badgeCasal) {
        if (totalBruno > totalLeticia) {
          badgeCasal.innerText = `Líder: Bruno (${formatBRL(totalBruno)})`;
        } else if (totalLeticia > totalBruno) {
          badgeCasal.innerText = `Líder: Letícia (${formatBRL(totalLeticia)})`;
        } else if (totalCasal > 0) {
          badgeCasal.innerText = 'Empatados!';
        } else {
          badgeCasal.innerText = 'Líder: -';
        }
      }

      if (totalCasal <= 0) {
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
            <div>Nenhum gasto registrado via WhatsApp pelo casal</div>
          </div>
        `;
      } else {
        let canvasCasal = document.getElementById('chart-casal');
        if (!canvasCasal) {
          containerCasal.innerHTML = '<canvas id="chart-casal"></canvas>';
          canvasCasal = document.getElementById('chart-casal');
        }

        const labelsCasal = [
          `Bruno (${countBruno} lançamentos)`,
          `Letícia (${countLeticia} lançamentos)`
        ];
        const valuesCasal = [totalBruno, totalLeticia];

        if (chartCasalInstance) {
          chartCasalInstance.data.labels = labelsCasal;
          chartCasalInstance.data.datasets[0].data = valuesCasal;
          chartCasalInstance.update();
        } else {
          const ctxCasal = canvasCasal.getContext('2d');
          chartCasalInstance = new Chart(ctxCasal, {
            type: 'doughnut',
            data: {
              labels: labelsCasal,
              datasets: [{
                data: valuesCasal,
                backgroundColor: [
                  '#3B82F6', // Azul elétrico (Bruno)
                  '#EC4899'  // Rosa vibrante (Letícia)
                ],
                borderColor: '#0B0F19',
                borderWidth: 2.5,
                hoverOffset: 6
              }]
            },
            options: {
              responsive: true,
              maintainAspectRatio: false,
              plugins: {
                legend: {
                  position: 'bottom',
                  labels: {
                    boxWidth: 12,
                    boxHeight: 12,
                    padding: 14,
                    color: '#CBD5E1',
                    font: { size: 12, weight: 600 }
                  }
                },
                tooltip: {
                  backgroundColor: '#1E293B',
                  titleColor: '#F8FAFC',
                  bodyColor: '#E2E8F0',
                  borderColor: 'rgba(255, 255, 255, 0.1)',
                  borderWidth: 1,
                  padding: 10,
                  boxPadding: 4,
                  callbacks: {
                    label: function(context) {
                      const val = context.raw || 0;
                      const pct = totalCasal > 0 ? ((val / totalCasal) * 100).toFixed(1) : 0;
                      return ` ${context.label}: ${formatBRL(val)} (${pct}%)`;
                    }
                  }
                }
              },
              cutout: '66%'
            }
          });
        }
      }

      // -------------------------------------------------------------
}

export function renderChartOfensores(listaTrans) {
      // -------------------------------------------------------------
      const containerOfensores = document.getElementById('container-chart-ofensores');
      const badgeTopGasto = document.getElementById('badge-top-gasto');

      // Agrupa gastos de despesa_variavel por descrição normalizada (remove parcela)
      const mapaGastosVar = new Map();
      listaTrans
        .filter(t => t.tipo === 'despesa_variavel')
        .forEach(t => {
          const raw = (t.descricao || t.categoria || 'Gasto sem nome').trim();
          const nomeLimpo = raw.replace(/\s*\(\d+\/\d+\)\s*$/, '').trim() || raw;
          const val = Number(t.valor || 0);
          if (!mapaGastosVar.has(nomeLimpo)) {
            mapaGastosVar.set(nomeLimpo, { total: 0, count: 0 });
          }
          const item = mapaGastosVar.get(nomeLimpo);
          item.total += val;
          item.count += 1;
        });

      const rankingOfensores = Array.from(mapaGastosVar.entries())
        .sort((a, b) => b[1].total - a[1].total)
        .slice(0, 6);

      if (rankingOfensores.length > 0 && badgeTopGasto) {
        badgeTopGasto.innerText = `Maior: ${rankingOfensores[0][0]} (${formatBRL(rankingOfensores[0][1].total)})`;
      } else if (badgeTopGasto) {
        badgeTopGasto.innerText = 'Maior: -';
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
        let canvasOfensores = document.getElementById('chart-ofensores');
        if (!canvasOfensores) {
          containerOfensores.innerHTML = '<canvas id="chart-ofensores"></canvas>';
          canvasOfensores = document.getElementById('chart-ofensores');
        }

        const labelsOfensores = rankingOfensores.map(([desc, info]) => `${desc} (${info.count}x)`);
        const valuesOfensores = rankingOfensores.map(([_, info]) => info.total);

        if (chartOfensoresInstance) {
          chartOfensoresInstance.data.labels = labelsOfensores;
          chartOfensoresInstance.data.datasets[0].data = valuesOfensores;
          chartOfensoresInstance.update();
        } else {
          const ctxOfensores = canvasOfensores.getContext('2d');
          chartOfensoresInstance = new Chart(ctxOfensores, {
            type: 'bar',
            data: {
              labels: labelsOfensores,
              datasets: [{
                label: 'Total Gasto (R$)',
                data: valuesOfensores,
                backgroundColor: 'rgba(245, 158, 11, 0.85)', // Âmbar / Laranja
                borderColor: '#F59E0B',
                borderWidth: 1.5,
                borderRadius: 7,
                barPercentage: 0.6
              }]
            },
            options: {
              indexAxis: 'y', // Barra horizontal para leitura confortável de nomes longos
              responsive: true,
              maintainAspectRatio: false,
              plugins: {
                legend: { display: false },
                tooltip: {
                  backgroundColor: '#1E293B',
                  titleColor: '#F8FAFC',
                  bodyColor: '#E2E8F0',
                  borderColor: 'rgba(255, 255, 255, 0.1)',
                  borderWidth: 1,
                  padding: 10,
                  callbacks: {
                    label: function(context) {
                      return ` Gasto acumulado: ${formatBRL(context.raw)}`;
                    }
                  }
                }
              },
              scales: {
                x: {
                  grid: { color: 'rgba(255, 255, 255, 0.05)', drawBorder: false },
                  ticks: {
                    color: '#94A3B8',
                    callback: function(val) {
                      return 'R$ ' + (val >= 1000 ? (val / 1000).toFixed(1) + 'k' : val);
                    }
                  }
                },
                y: {
                  grid: { display: false, drawBorder: false },
                  ticks: {
                    color: '#CBD5E1',
                    font: { weight: 600, size: 11.5 }
                  }
                }
              }
            }
          });
        }
      }

      // -------------------------------------------------------------
}

export function renderChartDias(listaTrans) {
      // -------------------------------------------------------------
      const containerDias = document.getElementById('container-chart-dias');
      const badgePicoDia = document.getElementById('badge-pico-dia');

      // Agrupa todas as despesas (fixas + variáveis) por dia
      const mapaDias = new Map();
      listaTrans
        .filter(t => t.tipo === 'despesa_variavel' || t.tipo === 'despesa_fixa')
        .forEach(t => {
          const diaFormatado = formatDateBR(t.data);
          const val = Number(t.valor || 0);
          mapaDias.set(diaFormatado, (mapaDias.get(diaFormatado) || 0) + val);
        });

      // Ordena por datas cronológicas
      const listaDias = Array.from(mapaDias.entries()).sort((a, b) => {
        const pA = a[0].split('/').reverse().join('-');
        const pB = b[0].split('/').reverse().join('-');
        return pA.localeCompare(pB);
      });

      // Identifica o dia de maior pico
      let diaPico = null;
      let maiorGastoDia = 0;
      listaDias.forEach(([dia, total]) => {
        if (total > maiorGastoDia) {
          maiorGastoDia = total;
          diaPico = dia;
        }
      });

      if (diaPico && badgePicoDia) {
        badgePicoDia.innerText = `Pico: ${diaPico} (${formatBRL(maiorGastoDia)})`;
      } else if (badgePicoDia) {
        badgePicoDia.innerText = 'Pico: -';
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
        let canvasDias = document.getElementById('chart-dias');
        if (!canvasDias) {
          containerDias.innerHTML = '<canvas id="chart-dias"></canvas>';
          canvasDias = document.getElementById('chart-dias');
        }

        const labelsDias = listaDias.map(([dia]) => dia);
        const valuesDias = listaDias.map(([_, val]) => val);

        if (chartDiasInstance) {
          chartDiasInstance.data.labels = labelsDias;
          chartDiasInstance.data.datasets[0].data = valuesDias;
          chartDiasInstance.update();
        } else {
          const ctxDias = canvasDias.getContext('2d');
          chartDiasInstance = new Chart(ctxDias, {
            type: 'line',
            data: {
              labels: labelsDias,
              datasets: [{
                label: 'Despesas no Dia (R$)',
                data: valuesDias,
                borderColor: '#06B6D4', // Ciano brilhante
                backgroundColor: 'rgba(6, 182, 212, 0.12)',
                borderWidth: 2.5,
                fill: true,
                tension: 0.35,
                pointBackgroundColor: '#06B6D4',
                pointBorderColor: '#0B0F19',
                pointBorderWidth: 2,
                pointRadius: 5,
                pointHoverRadius: 7
              }]
            },
            options: {
              responsive: true,
              maintainAspectRatio: false,
              plugins: {
                legend: { display: false },
                tooltip: {
                  backgroundColor: '#1E293B',
                  titleColor: '#F8FAFC',
                  bodyColor: '#E2E8F0',
                  borderColor: 'rgba(255, 255, 255, 0.1)',
                  borderWidth: 1,
                  padding: 10,
                  callbacks: {
                    label: function(context) {
                      return ` Total no dia: ${formatBRL(context.raw)}`;
                    }
                  }
                }
              },
              scales: {
                x: {
                  grid: { display: false, drawBorder: false },
                  ticks: {
                    color: '#CBD5E1',
                    font: { weight: 600, size: 11.5 }
                  }
                },
                y: {
                  grid: { color: 'rgba(255, 255, 255, 0.05)', drawBorder: false },
                  ticks: {
                    color: '#94A3B8',
                    callback: function(val) {
                      return 'R$ ' + (val >= 1000 ? (val / 1000).toFixed(1) + 'k' : val);
                    }
                  }
                }
              }
            }
          });
        }
      }
}
