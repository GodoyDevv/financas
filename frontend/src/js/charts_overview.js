/**
 * frontend/src/js/charts_overview.js
 *
 * Gr·ficos analÌticos: DistribuiÁ„o por Categoria e BalanÁo Financeiro.
 */
import { formatBRL } from './format.js';

let chartCategoriasInstance = null;
let chartBalancoInstance = null;

const PALETA_CATEGORIAS = [
  '#3B82F6', '#10B981', '#F59E0B', '#EC4899', '#8B5CF6',
  '#06B6D4', '#F97316', '#14B8A6', '#6366F1', '#64748B'
];

export function renderChartCategorias(metrics) {
      // -------------------------------------------------------------
      const containerCat = document.getElementById('container-chart-categorias');
      const categorias = metrics.categorias || [];
      const totalDespesas = (metrics.contas_fixas || 0) + (metrics.gastos_whatsapp || 0);

      const badgeTopCat = document.getElementById('badge-top-cat');
      if (categorias && categorias.length > 0 && badgeTopCat) {
        badgeTopCat.innerText = `Top: ${categorias[0].categoria} (${categorias[0].percentual}%)`;
      } else if (badgeTopCat) {
        badgeTopCat.innerText = 'Top: -';
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
            <div>Nenhuma despesa para exibir no gr√°fico</div>
          </div>
        `;
      } else {
        // Assegura canvas no container
        let canvasCat = document.getElementById('chart-categorias');
        if (!canvasCat) {
          containerCat.innerHTML = '<canvas id="chart-categorias"></canvas>';
          canvasCat = document.getElementById('chart-categorias');
        }

        const labelsCat = categorias.map(c => c.categoria);
        const dataCat = categorias.map(c => Number(c.total) || 0);
        const bgColors = categorias.map((_, i) => PALETA_CATEGORIAS[i % PALETA_CATEGORIAS.length]);

        if (chartCategoriasInstance) {
          chartCategoriasInstance.data.labels = labelsCat;
          chartCategoriasInstance.data.datasets[0].data = dataCat;
          chartCategoriasInstance.data.datasets[0].backgroundColor = bgColors;
          chartCategoriasInstance.update();
        } else {
          const ctxCat = canvasCat.getContext('2d');
          chartCategoriasInstance = new Chart(ctxCat, {
            type: 'doughnut',
            data: {
              labels: labelsCat,
              datasets: [{
                data: dataCat,
                backgroundColor: bgColors,
                borderWidth: 2,
                borderColor: '#121826',
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
                      const pct = totalDespesas > 0 ? ((val / totalDespesas) * 100).toFixed(1) : 0;
                      return ` ${context.label}: ${formatBRL(val)} (${pct}%)`;
                    }
                  }
                }
              },
              cutout: '68%'
            }
          });
        }
      }

      // -------------------------------------------------------------
}

export function renderChartBalanco(metrics) {
      // Receitas vs Contas Fixas vs Gastos WhatsApp
      // -------------------------------------------------------------
      const containerBalanco = document.getElementById('container-chart-balanco');
      const rec = Number(metrics.receitas_totais) || 0;
      const fix = Number(metrics.contas_fixas) || 0;
      const zap = Number(metrics.gastos_whatsapp) || 0;
      const temDados = (rec > 0 || fix > 0 || zap > 0);

      if (!temDados) {
        if (chartBalancoInstance) {
          chartBalancoInstance.destroy();
          chartBalancoInstance = null;
        }
        containerBalanco.innerHTML = `
          <div class="chart-empty">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8">
              <line x1="18" y1="20" x2="18" y2="10"></line>
              <line x1="12" y1="20" x2="12" y2="4"></line>
              <line x1="6" y1="20" x2="6" y2="14"></line>
            </svg>
            <div>Nenhuma movimenta√ß√£o para comparar no balan√ßo</div>
          </div>
        `;
      } else {
        let canvasBalanco = document.getElementById('chart-balanco');
        if (!canvasBalanco) {
          containerBalanco.innerHTML = '<canvas id="chart-balanco"></canvas>';
          canvasBalanco = document.getElementById('chart-balanco');
        }

        const labelsBalanco = ['Receitas', 'Contas Fixas', 'Gastos WhatsApp'];
        const valuesBalanco = [rec, fix, zap];

        if (chartBalancoInstance) {
          chartBalancoInstance.data.datasets[0].data = valuesBalanco;
          chartBalancoInstance.update();
        } else {
          const ctxBalanco = canvasBalanco.getContext('2d');
          chartBalancoInstance = new Chart(ctxBalanco, {
            type: 'bar',
            data: {
              labels: labelsBalanco,
              datasets: [{
                label: 'Total (R$)',
                data: valuesBalanco,
                backgroundColor: [
                  'rgba(16, 185, 129, 0.85)', // Verde Esmeralda
                  'rgba(245, 158, 11, 0.85)', // √Çmbar Dourado
                  'rgba(236, 72, 153, 0.85)'  // Rosa / Vari√°vel
                ],
                borderColor: [
                  '#10B981',
                  '#F59E0B',
                  '#EC4899'
                ],
                borderWidth: 1.5,
                borderRadius: 8,
                borderSkipped: false,
                barPercentage: 0.55
              }]
            },
            options: {
              responsive: true,
              maintainAspectRatio: false,
              plugins: {
                legend: {
                  display: false
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
                      return ` Valor: ${formatBRL(context.raw)}`;
                    }
                  }
                }
              },
              scales: {
                x: {
                  grid: {
                    display: false,
                    drawBorder: false
                  },
                  ticks: {
                    color: '#CBD5E1',
                    font: { weight: 600, size: 12 }
                  }
                },
                y: {
                  grid: {
                    color: 'rgba(255, 255, 255, 0.05)',
                    drawBorder: false
                  },
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

      // -------------------------------------------------------------
}
