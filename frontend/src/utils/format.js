// Formatting helpers shared by all components.
let currency = 'INR';
export const setCurrency = (c) => { currency = c || 'INR'; };
export const getCurrency = () => currency;

export function money(value, opts = {}) {
  if (value === null || value === undefined || Number.isNaN(Number(value))) return '—';
  const v = Number(value);
  const locale = currency === 'INR' ? 'en-IN' : 'en-US';
  return new Intl.NumberFormat(locale, {
    style: 'currency',
    currency,
    maximumFractionDigits: opts.compact || Math.abs(v) >= 1000 ? 0 : 2,
    minimumFractionDigits: 0,
  }).format(v);
}

export const pct = (v, digits = 1) =>
  v === null || v === undefined ? '—' : `${v > 0 ? '+' : ''}${Number(v).toFixed(digits)}%`;

export const num = (v, digits = 0) =>
  v === null || v === undefined ? '—' : Number(v).toLocaleString('en-IN', { maximumFractionDigits: digits });

export const clockTime = (iso) =>
  iso ? new Date(iso).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }) : '—';

export const dateTime = (iso) =>
  iso ? new Date(iso).toLocaleString([], { day: '2-digit', month: 'short', hour: '2-digit', minute: '2-digit' }) : '—';

export const categoryKey = (c = '') => c.toLowerCase().replace(/[\s-]+/g, '_');
const ICONS = { umbrella: '☂️', ice_cream: '🍦', ticket: '🎫', hot_beverage: '☕', generic: '🛍️' };
export const categoryIcon = (c) => ICONS[categoryKey(c)] || '🛍️';
export const categoryLabel = (c = '') => c.replace(/_/g, ' ');

export const FACTOR_LABELS = {
  weather: 'Weather',
  time_of_day: 'Time & Season',
  holiday_effect: 'Events & Holidays',
  demand: 'Demand',
  inventory: 'Stock Level',
  competition: 'Competition',
  guardrails: 'Guardrails',
  manual_adjustment: 'Manual Adjustment',
};
export const factorLabel = (k) => FACTOR_LABELS[k] || k.replace(/_/g, ' ');

export const MODEL_LABELS = {
  linear: 'Linear Regression',
  random_forest: 'Random Forest',
  gradient_boosting: 'Gradient Boosting',
  rule_based: 'Rule-based (fallback)',
  static: 'Static pricing',
  oracle: 'Oracle (upper bound)',
};
export const modelLabel = (k) => MODEL_LABELS[k] || k;

export const CONSTRAINT_LABELS = {
  price_min: 'Minimum price',
  price_max: 'Maximum price',
  margin_floor: 'Margin floor',
  max_discount: 'Max-discount rule',
  max_markup: 'Max-markup rule',
  volatility_cap: 'Volatility cap',
  price_frozen: 'Price freeze',
};
export const constraintLabel = (k) => CONSTRAINT_LABELS[k] || k;
