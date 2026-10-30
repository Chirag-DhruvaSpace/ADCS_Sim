// Optical indication only. Eligibility and firmware selection do not change light.
export function sunSignalLevel(data, cellName, enabled = true) {
  if (!enabled || data.sun_arr_valid === false) return 0;
  const head = data.fss_heads?.find(item => item.cell === cellName);
  if (head && Number.isFinite(head.q_sum)) {
    const fullScale = Number.isFinite(head.full_scale_counts) && head.full_scale_counts > 0
      ? head.full_scale_counts : 10000;
    return Math.max(0, Math.min(1, head.q_sum/fullScale));
  }
  const cell = data.sun_arr_cells?.find(item => item.name === cellName);
  return Number.isFinite(cell?.output_pct) ? Math.max(0, Math.min(1, cell.output_pct/100)) : 0;
}
