type AccountingMessages = Record<
  | 'title'
  | 'solar'
  | 'battery'
  | 'grid'
  | 'unknown'
  | 'gridCost'
  | 'knownGridCost'
  | 'about'
  | 'unavailable'
  | 'empty'
  | 'partial'
  | 'coverage'
  | 'batteryHint'
  | 'costUnknown'
  | 'costHint'
  | 'partialCostHint'
  | 'gridFirst'
  | 'loadFirst',
  string
>;
export const accountingDictionaries: Record<string, AccountingMessages> = {
  en: {
    title: 'Charging energy',
    solar: 'Solar',
    battery: 'Battery',
    grid: 'Grid',
    unknown: 'Not identified',
    gridCost: 'Grid cost',
    knownGridCost: 'Known grid cost',
    about: 'About this breakdown',
    unavailable: 'Energy recorded. Its sources could not be identified.',
    empty: 'No energy recorded yet.',
    partial: '{energy} kWh could not be assigned to a source.',
    coverage: 'Sources identified for {percent} of the recorded energy.',
    batteryHint:
      'Battery means energy from your home battery. Its earlier solar or grid origin is not tracked.',
    costUnknown: 'Grid cost is unavailable. This does not mean the session was free.',
    costHint:
      'The cost shown covers grid electricity only. Battery storage costs are not included.',
    partialCostHint: 'The cost shown covers only the identified grid share.',
    gridFirst:
      'Estimated from site measurements. Grid draw is assigned to charging first; this rule does not control your charger.',
    loadFirst:
      'Estimated from site measurements. Solar is assigned to household use and battery charging before the vehicle; this rule does not control your charger.',
  },
  de: {
    title: 'Ladeenergie',
    solar: 'Solar',
    battery: 'Batterie',
    grid: 'Netz',
    unknown: 'Nicht zugeordnet',
    gridCost: 'Netzkosten',
    knownGridCost: 'Bekannte Netzkosten',
    about: 'Zur Energieaufteilung',
    unavailable: 'Energie erfasst. Ihre Herkunft konnte nicht zugeordnet werden.',
    empty: 'Noch keine Energie erfasst.',
    partial: '{energy} kWh konnten keiner Quelle zugeordnet werden.',
    coverage: 'Für {percent} der erfassten Energie ist die Quelle zugeordnet.',
    batteryHint:
      'Batterie bezeichnet Energie aus dem Hausakku. Ob sie ursprünglich aus Solar oder Netz stammt, wird nicht erfasst.',
    costUnknown:
      'Netzkosten sind nicht ermittelbar. Das bedeutet nicht, dass die Sitzung kostenlos war.',
    costHint:
      'Die Kosten betreffen nur Netzstrom. Kosten der Batteriespeicherung sind nicht enthalten.',
    partialCostHint: 'Die Kosten betreffen nur den zugeordneten Netzanteil.',
    gridFirst:
      'Aus Standortmessungen abgeleitet. Netzbezug wird zuerst dem Laden zugeordnet; diese Regel steuert die Wallbox nicht.',
    loadFirst:
      'Aus Standortmessungen abgeleitet. Solarenergie wird vor dem Fahrzeug zunächst Hausverbrauch und Batterieladung zugeordnet; diese Regel steuert die Wallbox nicht.',
  },
  nl: {
    title: 'Laadenergie',
    solar: 'Zon',
    battery: 'Batterij',
    grid: 'Net',
    unknown: 'Niet toegewezen',
    gridCost: 'Netkosten',
    knownGridCost: 'Bekende netkosten',
    about: 'Over deze verdeling',
    unavailable: 'Energie geregistreerd. De bronnen konden niet worden bepaald.',
    empty: 'Nog geen energie geregistreerd.',
    partial: '{energy} kWh kon niet aan een bron worden toegewezen.',
    coverage: 'Voor {percent} van de geregistreerde energie is de bron bepaald.',
    batteryHint:
      'Batterij betekent energie uit de thuisbatterij. De eerdere herkomst uit zon of net wordt niet bijgehouden.',
    costUnknown: 'Netkosten zijn niet beschikbaar. Dit betekent niet dat de sessie gratis was.',
    costHint:
      'De kosten betreffen alleen netstroom. Kosten voor batterijopslag zijn niet inbegrepen.',
    partialCostHint: 'De kosten betreffen alleen het toegewezen netaandeel.',
    gridFirst:
      'Afgeleid van locatiemetingen. Netafname wordt eerst aan het laden toegewezen; deze regel stuurt de lader niet aan.',
    loadFirst:
      'Afgeleid van locatiemetingen. Zonne-energie wordt vóór het voertuig aan huisverbruik en batterijladen toegewezen; deze regel stuurt de lader niet aan.',
  },
  fr: {
    title: 'Énergie de recharge',
    solar: 'Solaire',
    battery: 'Batterie',
    grid: 'Réseau',
    unknown: 'Non attribuée',
    gridCost: 'Coût réseau',
    knownGridCost: 'Coût réseau connu',
    about: 'À propos de la répartition',
    unavailable: 'Énergie enregistrée. Ses sources n’ont pas pu être identifiées.',
    empty: 'Aucune énergie enregistrée pour le moment.',
    partial: '{energy} kWh n’ont pas pu être attribués à une source.',
    coverage: 'Sources identifiées pour {percent} de l’énergie enregistrée.',
    batteryHint:
      'La batterie désigne la batterie domestique. Son origine solaire ou réseau antérieure n’est pas suivie.',
    costUnknown:
      'Le coût réseau est indisponible. Cela ne signifie pas que la session était gratuite.',
    costHint:
      'Le coût affiché concerne uniquement le réseau. Les coûts de stockage ne sont pas inclus.',
    partialCostHint: 'Le coût affiché couvre uniquement la part réseau identifiée.',
    gridFirst:
      'Estimation à partir des mesures du site. Le réseau est attribué en priorité à la recharge ; cette règle ne pilote pas la borne.',
    loadFirst:
      'Estimation à partir des mesures du site. Le solaire est attribué au logement et à la batterie avant le véhicule ; cette règle ne pilote pas la borne.',
  },
  es: {
    title: 'Energía de carga',
    solar: 'Solar',
    battery: 'Batería',
    grid: 'Red',
    unknown: 'Sin asignar',
    gridCost: 'Coste de red',
    knownGridCost: 'Coste de red conocido',
    about: 'Sobre el reparto',
    unavailable: 'Energía registrada. No se pudieron identificar sus fuentes.',
    empty: 'Aún no se ha registrado energía.',
    partial: 'No se pudieron asignar {energy} kWh a una fuente.',
    coverage: 'Fuentes identificadas para el {percent} de la energía registrada.',
    batteryHint:
      'Batería indica energía de la batería doméstica. No se registra su origen solar o de red anterior.',
    costUnknown:
      'El coste de red no está disponible. Esto no significa que la sesión fuera gratuita.',
    costHint:
      'El coste mostrado solo incluye electricidad de red. No incluye costes de almacenamiento.',
    partialCostHint: 'El coste mostrado solo cubre la parte de red identificada.',
    gridFirst:
      'Estimación basada en mediciones del sitio. La red se asigna primero a la carga; esta regla no controla el cargador.',
    loadFirst:
      'Estimación basada en mediciones del sitio. La energía solar se asigna al hogar y la batería antes que al vehículo; esta regla no controla el cargador.',
  },
  it: {
    title: 'Energia di ricarica',
    solar: 'Solare',
    battery: 'Batteria',
    grid: 'Rete',
    unknown: 'Non attribuita',
    gridCost: 'Costo rete',
    knownGridCost: 'Costo rete noto',
    about: 'Informazioni sulla ripartizione',
    unavailable: 'Energia registrata. Non è stato possibile identificarne le fonti.',
    empty: 'Nessuna energia ancora registrata.',
    partial: 'Non è stato possibile attribuire {energy} kWh a una fonte.',
    coverage: 'Fonti identificate per il {percent} dell’energia registrata.',
    batteryHint:
      'Batteria indica energia dalla batteria domestica. L’origine precedente da solare o rete non viene tracciata.',
    costUnknown:
      'Il costo di rete non è disponibile. Questo non significa che la sessione fosse gratuita.',
    costHint: 'Il costo mostrato riguarda solo la rete. I costi di accumulo non sono inclusi.',
    partialCostHint: 'Il costo mostrato copre solo la quota di rete identificata.',
    gridFirst:
      'Stima dalle misure del sito. La rete viene attribuita prima alla ricarica; questa regola non controlla la stazione.',
    loadFirst:
      'Stima dalle misure del sito. Il solare viene attribuito alla casa e alla batteria prima del veicolo; questa regola non controlla la stazione.',
  },
  hu: {
    title: 'Töltési energia',
    solar: 'Napenergia',
    battery: 'Akkumulátor',
    grid: 'Hálózat',
    unknown: 'Nem besorolt',
    gridCost: 'Hálózati költség',
    knownGridCost: 'Ismert hálózati költség',
    about: 'Az energia megoszlásáról',
    unavailable: 'Az energia rögzítve. A forrásait nem sikerült azonosítani.',
    empty: 'Még nincs rögzített energia.',
    partial: '{energy} kWh nem rendelhető forráshoz.',
    coverage: 'A rögzített energia {percent}-ának forrása azonosított.',
    batteryHint:
      'Az akkumulátor az otthoni tárolóból származó energiát jelenti. Korábbi napenergia- vagy hálózati eredetét nem követjük.',
    costUnknown:
      'A hálózati költség nem elérhető. Ez nem jelenti azt, hogy a töltés ingyenes volt.',
    costHint: 'A költség csak a hálózati áramot tartalmazza. A tárolás költsége nincs benne.',
    partialCostHint: 'A költség csak az azonosított hálózati részre vonatkozik.',
    gridFirst:
      'Helyszíni mérésekből becsülve. A hálózati vételezést először a töltéshez rendeljük; ez a szabály nem vezérli a töltőt.',
    loadFirst:
      'Helyszíni mérésekből becsülve. A napenergiát először a házhoz és az akkumulátorhoz rendeljük, majd az autóhoz; ez a szabály nem vezérli a töltőt.',
  },
  sl: {
    title: 'Energija polnjenja',
    solar: 'Sonce',
    battery: 'Baterija',
    grid: 'Omrežje',
    unknown: 'Nerazporejeno',
    gridCost: 'Strošek omrežja',
    knownGridCost: 'Znani strošek omrežja',
    about: 'O razdelitvi energije',
    unavailable: 'Energija je zabeležena. Njenih virov ni bilo mogoče določiti.',
    empty: 'Energija še ni zabeležena.',
    partial: '{energy} kWh ni bilo mogoče dodeliti viru.',
    coverage: 'Viri so določeni za {percent} zabeležene energije.',
    batteryHint:
      'Baterija pomeni energijo iz domačega hranilnika. Predhodnega izvora iz sonca ali omrežja ne spremljamo.',
    costUnknown: 'Strošek omrežja ni na voljo. To ne pomeni, da je bilo polnjenje brezplačno.',
    costHint: 'Prikazani strošek zajema le omrežno elektriko. Stroški shranjevanja niso vključeni.',
    partialCostHint: 'Prikazani strošek zajema le določeni delež omrežja.',
    gridFirst:
      'Ocena iz meritev lokacije. Odjem iz omrežja se najprej dodeli polnjenju; to pravilo ne krmili polnilnice.',
    loadFirst:
      'Ocena iz meritev lokacije. Sončna energija se pred vozilom dodeli hiši in bateriji; to pravilo ne krmili polnilnice.',
  },
};
export function accountingTranslate(language: string) {
  const base = language.toLowerCase().replaceAll('_', '-').split('-')[0];
  const messages = accountingDictionaries[base] || accountingDictionaries.en;
  return (key: keyof AccountingMessages) => messages[key];
}
