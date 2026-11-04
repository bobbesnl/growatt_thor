import { numberWithin, type EditorField } from '../shared/editor-form';
import type { Entity, SessionCardConfig } from '../shared/types';

/** Card options in the order the editor shows them; defaults match the card. */
export function sessionEditorFields(
  entities: Entity[],
  entity: string,
  t: (key: string) => string,
): EditorField<SessionCardConfig>[] {
  return [
    {
      name: 'entity',
      label: t('charger'),
      selector: { entity: { include_entities: entities.map((item) => item.entity_id) } },
      fallback: entity || undefined,
    },
    {
      name: 'rows',
      label: t('rows'),
      selector: { number: { min: 1, max: 20, step: 1, mode: 'box' } },
      fallback: 10,
      accept: numberWithin(1, 20, true),
    },
    { name: 'show_curve', label: t('showCurve'), selector: { boolean: {} }, fallback: true },
    {
      name: 'show_identifier',
      label: t('showIdentifier'),
      selector: { boolean: {} },
      fallback: true,
    },
  ];
}
