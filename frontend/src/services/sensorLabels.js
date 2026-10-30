export function sunCellLabel(cell, index) {
  const id=cell.fss_id || `FSS${index+1}`;
  return cell.name ? `${id} (${cell.name})` : id;
}
