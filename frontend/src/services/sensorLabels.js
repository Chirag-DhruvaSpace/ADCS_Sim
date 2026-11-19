export function sunCellLabel(cell, index) {
  if (cell.coarse_only && cell.name) return cell.name;
  const id=cell.fss_id || `FSS${index+1}`;
  return cell.name ? `${id} (${cell.name})` : id;
}
