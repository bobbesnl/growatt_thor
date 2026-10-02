// Simulator-only ha-icon implementation. Production still uses Home Assistant's element.
declare const __PREVIEW_ICON_PATHS__: Record<string, string>;
const paths = __PREVIEW_ICON_PATHS__;
const namespace = 'http://www.w3.org/2000/svg';

class PreviewHaIcon extends HTMLElement {
  static observedAttributes = ['icon'];
  private _icon = '';
  private readonly path = document.createElementNS(namespace, 'path');

  constructor() {
    super();
    const root = this.attachShadow({ mode: 'open' });
    const style = document.createElement('style');
    style.textContent = `:host { display:inline-flex; width:var(--mdc-icon-size,24px); height:var(--mdc-icon-size,24px); align-items:center; justify-content:center; vertical-align:middle; flex-shrink:0; } svg { display:block; width:100%; height:100%; fill:currentColor; }`;
    const svg = document.createElementNS(namespace, 'svg');
    svg.setAttribute('viewBox', '0 0 24 24');
    svg.setAttribute('aria-hidden', 'true');
    svg.setAttribute('focusable', 'false');
    svg.append(this.path);
    root.append(style, svg);
  }
  get icon() {
    return this._icon;
  }
  set icon(value: string) {
    this._icon = value || '';
    const path = paths[this._icon];
    this.path.setAttribute('d', path || (this._icon ? paths['mdi:help-circle-outline'] : ''));
    this.toggleAttribute('data-icon-missing', !!this._icon && !path);
  }
  attributeChangedCallback(_name: string, _old: string | null, value: string | null) {
    this.icon = value || '';
  }
}

if (!customElements.get('ha-icon')) customElements.define('ha-icon', PreviewHaIcon);
