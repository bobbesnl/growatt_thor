import { resolveEntity, statusEntities } from './model';
import type { CardConfig, Hass } from './types';

export type CardInitialization = 'ready' | 'connecting' | 'waiting' | 'select' | 'incompatible';

/** A restored status entity may exist before the integration publishes its card data. */
export function cardInitialization(
  hass: Hass | undefined,
  config: CardConfig,
  sessions = false,
): CardInitialization {
  if (!hass) return 'connecting';
  const entity = resolveEntity(hass, config);
  const data = entity?.attributes.thor_card;
  if (data?.schema === 1 && (!sessions || data.sessions?.schema === 1)) return 'ready';
  if (hass.connected === false || !Object.keys(hass.states ?? {}).length) return 'connecting';

  // Entry-id discovery normally filters out unsupported contracts. Still identify
  // that case explicitly rather than displaying a loading message forever.
  const candidate = config.entry_id
    ? Object.values(hass.states).find(
        (item) => item?.attributes.thor_card?.entry_id === config.entry_id,
      )
    : entity;
  const contract = candidate?.attributes.thor_card;
  if (
    contract &&
    (contract.schema !== 1 || (sessions && contract.sessions && contract.sessions.schema !== 1))
  )
    return 'incompatible';
  if (!config.entity && !config.entry_id && statusEntities(hass).length > 1) return 'select';
  // Missing data does not prove a missing selection: HA may still be restoring
  // entities, or the entry may be reloading. A later hass update retries normally.
  return 'waiting';
}
