import { unsafeCSS } from 'lit';
import { themeDeclarations } from './palette';
import tokenCss from './tokens.css';
import dialogCss from './dialog.css';

// Only trusted repository-owned stylesheets are embedded at build time.
export const tokenStyles = unsafeCSS(themeDeclarations() + tokenCss);
export const dialogStyles = unsafeCSS(dialogCss);
