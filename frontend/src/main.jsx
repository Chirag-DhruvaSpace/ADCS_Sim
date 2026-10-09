/* made by chirag malik | malikchirag.2005@gmail.com | linkedin: malikchirag */
import 'react';
import { createRoot } from 'react-dom/client';
import { gsap } from 'gsap';
import './index.css';
import App from './App.jsx';
/* made by chirag malik | malikchirag.2005@gmail.com | linkedin: malikchirag */
window.gsap = gsap;
document.getElementById('launch-root').replaceChildren();
createRoot(document.getElementById('root')).render(<App />);
