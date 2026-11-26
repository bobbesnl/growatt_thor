import { unsafeCSS } from 'lit';
import baseCss from './card.css';
import headerCss from './header.css';
import heroCss from './hero.css';
import sessionCss from './session.css';
import actionsCss from './actions.css';
import footerCss from './footer.css';
import responsiveCss from './responsive.css';

// Keep source order: responsive overrides follow every base section.
export const chargerStyles = [
  baseCss,
  headerCss,
  heroCss,
  sessionCss,
  actionsCss,
  footerCss,
  responsiveCss,
].map((text) => unsafeCSS(text));
