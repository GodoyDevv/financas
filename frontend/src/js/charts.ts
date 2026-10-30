/**
 * frontend/src/js/charts.ts
 *
 * Ponto de entrada para renderizacao dos graficos analiticos Chart.js.
 * Registra estritamente os componentes necessarios da biblioteca via npm (tree-shaking).
 */

import {
  Chart,
  ArcElement,
  LineElement,
  BarElement,
  PointElement,
  CategoryScale,
  LinearScale,
  Tooltip,
  Legend,
  Filler,
} from "chart.js";
import { renderChartCategorias, renderChartBalanco } from "./charts_overview";
import { renderChartCasal, renderChartOfensores, renderChartDias } from "./charts_trends";
import type { MetricsResponse, TransactionResponse } from "./state";

// Registra apenas os elementos, escalas e plugins utilizados
Chart.register(
  ArcElement,
  LineElement,
  BarElement,
  PointElement,
  CategoryScale,
  LinearScale,
  Tooltip,
  Legend,
  Filler
);

export function atualizarGraficos(
  metrics: MetricsResponse | null,
  trans: TransactionResponse[] | null
): void {
  const listaTrans = trans || [];

  // Configuracao padrao global para tema Dark
  Chart.defaults.color = "#94A3B8";
  Chart.defaults.font.family = "'Plus Jakarta Sans', sans-serif";

  // 1. Graficos de Visao Geral (Categorias e Balanco)
  renderChartCategorias(metrics);
  renderChartBalanco(metrics);

  // 2. Graficos de Tendencias e Detalhamento (Casal, Maiores Gastos e Linha do Tempo)
  renderChartCasal(listaTrans);
  renderChartOfensores(listaTrans);
  renderChartDias(listaTrans);
}

export { Chart };
