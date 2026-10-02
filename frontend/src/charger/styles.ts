import { unsafeCSS } from 'lit';
import cssText from './card.css';

// Trusted, repository-owned stylesheet embedded at build time; never user input.
export const styles = unsafeCSS(cssText);
