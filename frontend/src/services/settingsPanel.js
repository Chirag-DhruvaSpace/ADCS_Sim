/* made by chirag malik | malikchirag.2005@gmail.com | linkedin: malikchirag */
import { createLifecycle } from "./lifecycle.js";
export function bindSettingsPanel() {
  const lifecycle = createLifecycle();
  const {
    listen,
    fetch
  } = lifecycle;
  const $ = id => document.getElementById(id);
  const settings = $('settings-panel'),
    settingsBackdrop = document.querySelector('.mission-settings-backdrop');
  const motion = matchMedia('(prefers-reduced-motion: reduce)');
  document.querySelectorAll('.set-row').forEach(row => {
    const label = row.querySelector('label'),
      control = row.querySelector('input[id],select[id]');
    if (label && control) label.htmlFor = control.id;
  });
  document.querySelectorAll('#mount-position input,#mount-normal input,#mount-fov').forEach(input => input.step = 'any');
  const save = $('mount-save');
  listen(save, 'click', async () => {
    save.disabled = true;
    try {
      const response = await fetch('/api/imu/defaults', {
        method: 'POST'
      });
      const result = await response.json();
      if (!response.ok) throw Error(result.error);
      $('mount-status').textContent = result.status;
    } catch (error) {
      $('mount-status').textContent = error.message;
    } finally {
      save.disabled = false;
    }
  });
  listen(document, 'keydown', event => {
    if (event.key === 'Escape') window.setSettingsOpen(false);
  });
  listen(document, 'change', event => {
    if (!settings.contains(event.target)) return;
    const element = event.target.closest('.set-row') || event.target;
    element.getAnimations().forEach(animation => animation.cancel());
    if (!motion.matches) element.animate([{
      opacity: .65,
      transform: 'translateY(3px)'
    }, {
      opacity: 1,
      transform: 'translateY(0)'
    }], {
      duration: 180,
      easing: 'ease-out'
    });
  });
  let panelMotion = null;
  let requestedOpen = false;
  window.setSettingsOpen = open => {
    if (requestedOpen === open) return;
    requestedOpen = open;
    const wasDisplayed = settings.classList.contains('open');
    const current = getComputedStyle(settings);
    const opacity = wasDisplayed ? Number(current.opacity) : 0;
    const scale = wasDisplayed && current.scale !== 'none' ? Number(current.scale) : .985;
    panelMotion?.cancel();
    settingsBackdrop.classList.toggle('open', open);
    settings.inert = !open;
    $('settings-toggle').setAttribute('aria-expanded', String(open));
    if (open) {
      settings.classList.add('open');
      $('settings-close').focus();
    } else $('settings-toggle').focus();
    if (motion.matches) {
      settings.classList.toggle('open', open);
      return;
    }
    panelMotion = settings.animate([
      { opacity, scale },
      { opacity: open ? 1 : 0, scale: open ? 1 : .985 }
    ], { duration: open ? 320 : 200, easing: 'cubic-bezier(.16,1,.3,1)', fill: 'both' });
    const animation = panelMotion;
    animation.finished.then(() => {
      if (panelMotion !== animation) return;
      if (!requestedOpen) settings.classList.remove('open');
      animation.cancel();
      panelMotion = null;
    }).catch(() => {});
  };
  /* made by chirag malik | malikchirag.2005@gmail.com | linkedin: malikchirag */
  settings.inert = true;
  let mounts = [];
  const select = document.getElementById('mount-select');
  const status = document.getElementById('mount-status');
  function showMount() {
    const m = mounts.find(x => x.name === select.value);
    if (!m) return;
    document.querySelectorAll('#mount-position input').forEach((el, i) => el.value = m.position[i]);
    document.querySelectorAll('#mount-normal input').forEach((el, i) => el.value = (m.normal || [0, 0, 1])[i]);
    document.getElementById('mount-fov').value = m.fov || 90;
    document.getElementById('mount-normal-row').style.display = m.kind === 'Sun' ? '' : 'none';
    document.getElementById('mount-fov-row').style.display = m.kind === 'Sun' ? '' : 'none';
  }
  fetch('/api/imu/mounts').then(r => r.json()).then(data => {
    mounts = data;
    for (const m of mounts) select.add(new Option(m.name, m.name));
    showMount();
  }).catch(() => status.textContent = 'Mount configuration unavailable.');
  listen(select, 'change', showMount);
  listen(document.getElementById('mount-apply'), 'click', async () => {
    try {
      const response = await fetch('/api/imu/mounts', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json'
        },
        body: JSON.stringify({
          name: select.value,
          position: [...document.querySelectorAll('#mount-position input')].map(e => e.valueAsNumber),
          normal: [...document.querySelectorAll('#mount-normal input')].map(e => e.valueAsNumber),
          fov: document.getElementById('mount-fov').valueAsNumber
        })
      });
      const data = await response.json();
      if (!response.ok) throw new Error(data.error);
      mounts = data.mounts;
      status.textContent = data.status;
    } catch (error) {
      status.textContent = error.message;
    }
  });
  for (const [button, page] of [['tlm-tab-tlm', 'tlm-page-tlm'], ['tlm-tab-sen', 'tlm-page-sensors']]) {
    listen(document.getElementById(button), 'click', () => {
      document.querySelectorAll('.tlm-page').forEach(p => p.hidden = p.id !== page);
      document.querySelectorAll('.tlm-tab').forEach(b => b.classList.toggle('active', b.id === button));
    });
  }
  document.querySelectorAll('[data-settings-tab]').forEach(b => listen(b, 'click', () => {
    document.querySelectorAll('[data-settings-page]').forEach(p => p.hidden = p.dataset.settingsPage !== b.dataset.settingsTab);
    document.querySelectorAll('[data-settings-tab]').forEach(t => t.setAttribute('aria-selected', String(t === b)));
    const pane = document.querySelector(`[data-settings-page="${b.dataset.settingsTab}"]`);
    settings.querySelectorAll('[data-settings-page]').forEach(page => {
      page.getAnimations().forEach(animation => animation.cancel());
    });
    if (!motion.matches) pane.animate([{opacity: 0, transform: 'translate3d(0,6px,0)'}, {opacity: 1, transform: 'translate3d(0,0,0)'}], {
      duration: 240, easing: 'cubic-bezier(.16,1,.3,1)'
    });
  }));
  return () => {
    panelMotion?.cancel();
    lifecycle.dispose();
    window.gsap?.killTweensOf([settings, settingsBackdrop]);
    delete window.setSettingsOpen;
  };
}
