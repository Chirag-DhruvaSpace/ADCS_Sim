/* made by chirag malik | malikchirag.2005@gmail.com | linkedin: malikchirag */
import { useEffect, useLayoutEffect, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import { gsap } from 'gsap';
import './GlassSelect.css';
export default function GlassSelect({
  id,
  label,
  options,
  initialValue,
  telemetryValue
}) {
  const select = useRef(null),
    trigger = useRef(null),
    menu = useRef(null);
  const [value, setValue] = useState(initialValue),
    [open, setOpen] = useState(false);
  useEffect(() => {
    if (telemetryValue && options.some(option => option.value === telemetryValue) && document.activeElement !== select.current) {
      select.current.value = telemetryValue;
      setValue(telemetryValue);
    }
  }, [telemetryValue, options]);
  useEffect(() => {
    const sync = () => setValue(select.current.value);
    const element = select.current;
    element.addEventListener('change', sync);
    return () => element.removeEventListener('change', sync);
  }, []);
  useEffect(() => {
    if (!open) return;
    const close = event => {
      if (!menu.current?.contains(event.target) && !trigger.current?.contains(event.target)) setOpen(false);
    };
    const key = event => {
      if (event.key === 'Escape') {
        setOpen(false);
        trigger.current.focus();
      }
    };
    const resize = () => setOpen(false);
    document.addEventListener('pointerdown', close);
    document.addEventListener('keydown', key);
    document.addEventListener('scroll', close, true);
    window.addEventListener('resize', resize);
    return () => {
      document.removeEventListener('pointerdown', close);
      document.removeEventListener('keydown', key);
      document.removeEventListener('scroll', close, true);
      window.removeEventListener('resize', resize);
      gsap.killTweensOf(menu.current);
    };
  }, [open]);
  useLayoutEffect(() => {
    if (!open) return;
    const rect = trigger.current.getBoundingClientRect(),
      element = menu.current;
    const width = id === 'modeSelect' ? Math.min(420, innerWidth - 16) : rect.width;
    Object.assign(element.style, {
      left: `${Math.max(8, Math.min(rect.left, innerWidth - width - 8))}px`,
      width: `${width}px`,
      maxHeight: `${Math.min(360, innerHeight - 30)}px`,
      top: `${rect.bottom + 6}px`
    });
    if (element.getBoundingClientRect().bottom > innerHeight - 8) element.style.top = `${Math.max(8, rect.top - element.getBoundingClientRect().height - 6)}px`;
    if (!matchMedia('(prefers-reduced-motion: reduce)').matches) gsap.fromTo(element, {
      autoAlpha: 0,
      y: -7
    }, {
      autoAlpha: 1,
      y: 0,
      duration: .24,
      ease: 'power2.out'
    });
  }, [open, id]);
  function choose(next) {
    select.current.value = next;
    select.current.dispatchEvent(new Event('change', {
      bubbles: true
    }));
    setValue(next);
    setOpen(false);
    trigger.current.focus();
    const controls = select.current.closest('.pointing-controls');
    controls?.classList.remove('mode-changed', 'camera-changed');
    if (controls) {
      void controls.offsetWidth;
      controls.classList.add(id === 'modeSelect' ? 'mode-changed' : 'camera-changed');
    }
    if (!matchMedia('(prefers-reduced-motion: reduce)').matches) gsap.fromTo(select.current, {
      scale: .975,
      filter: 'brightness(1.35)'
    }, {
      scale: 1,
      filter: 'brightness(1)',
      duration: .45,
      ease: 'back.out(2)'
    });
  }
  return <div className="glass-select">{
      /* made by chirag malik | malikchirag.2005@gmail.com | linkedin: malikchirag */
    }<select ref={select} id={id} aria-label={label} className="glass-native-select" defaultValue={initialValue}>{options.map(option => <option key={option.value} value={option.value}>{option.label}</option>)}</select><button ref={trigger} className="glass-select-trigger glass" type="button" aria-haspopup="listbox" aria-expanded={open} onClick={() => setOpen(!open)}><span>{options.find(option => option.value === value)?.label || 'Select'}</span><svg viewBox="0 0 24 24" aria-hidden="true"><path d="m6 9 6 6 6-6" /></svg></button>{open && createPortal(<div ref={menu} className={'glass-select-menu glass ' + (id === 'modeSelect' ? 'mode-menu' : 'camera-menu')} role="listbox">{options.map(option => <button className="glass-select-option" type="button" role="option" aria-selected={option.value === value} data-value={option.value} key={option.value} onClick={() => choose(option.value)}>{option.label}</button>)}</div>, document.body)}</div>;
}
