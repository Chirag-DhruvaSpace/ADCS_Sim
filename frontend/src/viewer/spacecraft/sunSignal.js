// Optical indication only. Eligibility and firmware selection do not change light.
export function sunSignalLevel(data, cellName, enabled = true) {
  if (!enabled || data.sun_arr_valid === false) return 0;
  // Match the received-light percentage shown in the Sun sensor table.
  // Fine-head quadrant counts have a narrower optical window: zero fine
  // signal does not imply zero light reaching the sensor's surface.
  const cell = data.sun_arr_cells?.find(item => item.name === cellName);
  if (cell) {
    return Number.isFinite(cell.output_pct) ? Math.max(0, Math.min(1, cell.output_pct/100)) : 0;
  }
  const head = data.fss_heads?.find(item => item.cell === cellName);
  if (head && Number.isFinite(head.q_sum)) {
    const fullScale = Number.isFinite(head.full_scale_counts) && head.full_scale_counts > 0
      ? head.full_scale_counts : 10000;
    // The firmware still receives every raw count. Only marker appearance
    // excludes the configured electronics noise envelope.
    const noise = Number.isFinite(head.display_noise_floor_counts)
      ? Math.max(0, Math.min(fullScale-1, head.display_noise_floor_counts)) : 0;
    return Math.max(0, Math.min(1, (head.q_sum-noise)/(fullScale-noise)));
  }
  return 0;
}
