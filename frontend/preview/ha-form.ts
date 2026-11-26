// Simulator-only ha-form with the selectors the card editors use. Production
// renders Home Assistant's own element, which the card editor dialog loads.
interface Field {
  name: string;
  selector: Record<string, Record<string, unknown>>;
}
type Value = Record<string, unknown>;

class PreviewHaForm extends HTMLElement {
  hass: unknown;
  private _computeLabel: (field: Field) => string = (field) => field.name;
  private _computeHelper: (field: Field) => string | undefined = () => undefined;
  private _pending = false;
  private _data: Value = {};
  private _schema: Field[] = [];
  private readonly root = this.attachShadow({ mode: 'open' });

  set computeLabel(value: (field: Field) => string) {
    this._computeLabel = value;
    this.render();
  }
  get computeLabel() {
    return this._computeLabel;
  }
  set computeHelper(value: (field: Field) => string | undefined) {
    this._computeHelper = value;
    this.render();
  }
  get computeHelper() {
    return this._computeHelper;
  }
  set data(value: Value) {
    this._data = value || {};
    this.render();
  }
  get data(): Value {
    return this._data;
  }
  set schema(value: Field[]) {
    this._schema = value || [];
    this.render();
  }
  get schema(): Field[] {
    return this._schema;
  }

  private emit(name: string, value: unknown) {
    this.dispatchEvent(
      new CustomEvent('value-changed', { detail: { value: { ...this._data, [name]: value } } }),
    );
  }

  private control(field: Field): HTMLElement {
    const [type, options] = Object.entries(field.selector)[0] ?? ['text', {}];
    const current = this._data[field.name];
    if (type === 'boolean') {
      const input = document.createElement('input');
      input.type = 'checkbox';
      input.checked = current === true;
      input.onchange = () => this.emit(field.name, input.checked);
      return input;
    }
    if (type === 'select' || type === 'entity') {
      const select = document.createElement('select');
      const choices =
        type === 'entity'
          ? ((options.include_entities as string[]) || []).map((value) => ({ value, label: value }))
          : (options.options as { value: string; label: string }[]);
      for (const { value, label } of [{ value: '', label: '—' }, ...choices])
        select.append(new Option(label, value, false, value === current));
      select.onchange = () => this.emit(field.name, select.value || undefined);
      return select;
    }
    const input = document.createElement('input');
    input.value = current == null ? '' : String(current);
    if (type === 'number') {
      input.type = 'number';
      for (const key of ['min', 'max', 'step'] as const)
        if (options[key] !== undefined) input[key] = String(options[key]);
      input.onchange = () => this.emit(field.name, input.value ? Number(input.value) : undefined);
    } else input.onchange = () => this.emit(field.name, input.value);
    return input;
  }

  // Lit sets the properties one by one; render once after all of them.
  private render() {
    if (this._pending) return;
    this._pending = true;
    queueMicrotask(() => {
      this._pending = false;
      this.draw();
    });
  }

  private draw() {
    const style = document.createElement('style');
    style.textContent = `label { display:block; margin:0 0 14px; font-size:14px; }
      input:not([type=checkbox]), select { display:block; width:100%; margin-top:6px; padding:10px;
        border:1px solid var(--divider-color,#ccc); border-radius:8px; font:inherit; box-sizing:border-box; }
      small { display:block; opacity:.7; margin-top:4px; }`;
    const fields = this._schema.map((field) => {
      const label = document.createElement('label');
      const control = this.control(field);
      if (control instanceof HTMLInputElement && control.type === 'checkbox')
        label.append(control, ` ${this.computeLabel(field)}`);
      else label.append(this.computeLabel(field), control);
      const helper = this.computeHelper(field);
      if (helper)
        label.append(Object.assign(document.createElement('small'), { textContent: helper }));
      return label;
    });
    this.root.replaceChildren(style, ...fields);
  }
}

if (!customElements.get('ha-form')) customElements.define('ha-form', PreviewHaForm);
