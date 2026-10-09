
  document.addEventListener('DOMContentLoaded', () => {
    let mounts = [];
    const select = document.getElementById('mount-select');
    const status = document.getElementById('mount-status');
    function showMount() {
      const m = mounts.find(x => x.name === select.value);
      if (!m) return;
      document.querySelectorAll('#mount-position input').forEach((el,i) => el.value = m.position[i]);
      document.querySelectorAll('#mount-normal input').forEach((el,i) => el.value = (m.normal || [0,0,1])[i]);
      document.getElementById('mount-fov').value = m.fov || 90;
      document.getElementById('mount-normal-row').style.display = m.kind === 'Sun' ? '' : 'none';
      document.getElementById('mount-fov-row').style.display = m.kind === 'Sun' ? '' : 'none';
    }
    fetch('/api/imu/mounts').then(r => r.json()).then(data => {
      mounts = data;
      for (const m of mounts) select.add(new Option(m.name, m.name));
      showMount();
    }).catch(() => status.textContent = 'Mount configuration unavailable.');
    select.addEventListener('change', showMount);
    document.getElementById('mount-apply').addEventListener('click', async () => {
      try {
        const response = await fetch('/api/imu/mounts', {method:'POST', headers:{'Content-Type':'application/json'},
          body: JSON.stringify({name: select.value,
            position: [...document.querySelectorAll('#mount-position input')].map(e => e.valueAsNumber),
            normal: [...document.querySelectorAll('#mount-normal input')].map(e => e.valueAsNumber),
            fov: document.getElementById('mount-fov').valueAsNumber})});
        const data = await response.json();
        if (!response.ok) throw new Error(data.error);
        mounts = data.mounts; status.textContent = data.status;
      } catch(error) { status.textContent = error.message; }
    });
    for (const [button, page] of [['tlm-tab-tlm', 'tlm-page-tlm'], ['tlm-tab-sen', 'tlm-page-sensors']]) {
      document.getElementById(button).addEventListener('click', () => {
        document.querySelectorAll('.tlm-page').forEach(p => p.hidden = p.id !== page);
        document.querySelectorAll('.tlm-tab').forEach(b => b.classList.toggle('active', b.id === button));
      });
    }
    document.querySelectorAll('[data-settings-tab]').forEach(b => b.addEventListener('click', () => {
      document.querySelectorAll('[data-settings-page]').forEach(p => p.hidden = p.dataset.settingsPage !== b.dataset.settingsTab);
      document.querySelectorAll('[data-settings-tab]').forEach(t => t.setAttribute('aria-selected', String(t === b)));
      const pane = document.querySelector(`[data-settings-page="${b.dataset.settingsTab}"]`);
      if (window.gsap && !matchMedia('(prefers-reduced-motion: reduce)').matches)
        window.gsap.fromTo(pane.children, { autoAlpha: 0, y: 12 }, { autoAlpha: 1, y: 0, stagger: .025, duration: .4, ease: 'power3.out' });
    }));
  });
  