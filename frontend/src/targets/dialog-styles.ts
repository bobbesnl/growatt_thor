import { unsafeCSS } from 'lit';
import cssText from './dialog.css';

// Trusted, repository-owned stylesheet embedded at build time; never user input.
export const goalDialogStyles = unsafeCSS(cssText);
