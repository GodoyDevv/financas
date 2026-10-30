/**
 * frontend/src/js/charts.js
 *
 * Ponto de entrada para renderizacao dos graficos analiticos Chart.js.
 * Delega para charts_overview e charts_trends mantendo cada modulo < 400 linhas.
 */

import { renderChartCategorias, renderChartBalanco } from './charts_overview.js';
import { renderChartCasal, renderChartOfensores, renderChartDias } from './charts_trends.js';

export function atualizarGraficos(metrics, trans) {
  if (typeof Chart === 'undefined') {
    console.warn('Chart.js ainda nao esta carregado.');
    return;
  }

  const listaTrans = trans || [];

  // Configuracao padrao global para tema Dark
  Chart.defaults.color = '#94A3B8';
  Chart.defaults.font.family = "'Plus Jakarta Sans', sans-serif";

  // 1. Graficos de Visao Geral (Categorias e Balanco)
  renderChartCategorias(metrics);
  renderChartBalanco(metrics);

  // 2. Graficos de Tendencias e Detalhamento (Casal, Maiores Gastos e Linha do Tempo)
  renderChartCasal(listaTrans);
  renderChartOfensores(listaTrans);
  renderChartDias(listaTrans);
}
