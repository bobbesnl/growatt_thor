/** Canonical color values shared by CSS tokens and ECharts. */
const light = {
  ink: '#192821',
  muted: '#65756b',
  surface: '#fff',
  panel: '#f4f7f2',
  line: '#e5ebe3',
  green: '#3f7510',
  lime: '#8bc53f',
  amber: '#976016',
  red: '#bc3544',
  blue: '#32719c',
  neutral: '#6c7b72',
  'flow-solar': '#8bc53f',
  'flow-target': '#2f7fb8',
  'flow-over-target': '#db7447',
  'flow-over-target-critical': '#c83e4d',
  'flow-grid-import': '#b36f14',
  'flow-grid-export': '#3f7510',
  'flow-battery': '#7564b5',
  'source-solar': 'var(--flow-solar)',
  'source-battery': 'var(--flow-battery)',
  'source-grid': 'var(--flow-grid-import)',
  'source-unknown': '#d7ded7',
  'on-green': '#fff',
  'chart-text': '#34423a',
  'chart-zoom-bg': 'rgba(229,235,227,.45)',
  'chart-zoom-border': '#d3ddd1',
  'chart-zoom-fill': 'rgba(139,197,63,.20)',
  'chart-shadow-line': '#9ba89f',
  'chart-shadow-area': '#dce4da',
  'chart-area': 'rgba(139,197,63,.20)',
} as const;
const dark: Record<keyof typeof light, string> = {
  ink: '#eff4ed',
  muted: '#a4b3a6',
  surface: '#18211d',
  panel: '#212d25',
  line: '#344039',
  green: '#a5da69',
  lime: '#8bc53f',
  amber: '#efbe6b',
  red: '#ff8c97',
  blue: '#8ac4ed',
  neutral: '#a4b3a6',
  'flow-solar': '#a5da69',
  'flow-target': '#79c7f2',
  'flow-over-target': '#f1966f',
  'flow-over-target-critical': '#ff7580',
  'flow-grid-import': '#efbe6b',
  'flow-grid-export': '#a5da69',
  'flow-battery': '#b9a9f4',
  'source-solar': 'var(--flow-solar)',
  'source-battery': 'var(--flow-battery)',
  'source-grid': 'var(--flow-grid-import)',
  'source-unknown': '#445248',
  'on-green': '#172019',
  'chart-text': '#d7dfd8',
  'chart-zoom-bg': 'rgba(52,64,57,.32)',
  'chart-zoom-border': '#506057',
  'chart-zoom-fill': 'rgba(139,197,63,.24)',
  'chart-shadow-line': '#738078',
  'chart-shadow-area': '#3b4840',
  'chart-area': 'rgba(139,197,63,.16)',
};

function themePalette(isDark: boolean): Record<keyof typeof light, string> {
  return isDark ? dark : light;
}

export function themeDeclarations(): string {
  const declarations = (values: Record<string, string>) =>
    Object.entries(values)
      .map(([key, value]) => `--${key}:${value};`)
      .join('');
  return `:host,.card{${declarations(light)}}.dark{${declarations(dark)}}`;
}

export function chartPalette(isDark: boolean) {
  const tokens = themePalette(isDark);
  return {
    charge: tokens.lime,
    solar: tokens['flow-solar'],
    target: tokens['flow-target'],
    house: tokens['flow-grid-import'],
    battery: tokens['flow-battery'],
    measuredCurrent: tokens.green,
    neutral: tokens.neutral,
    text: tokens['chart-text'],
    muted: tokens.muted,
    line: tokens.line,
    zoomBackground: tokens['chart-zoom-bg'],
    zoomBorder: tokens['chart-zoom-border'],
    zoomFill: tokens['chart-zoom-fill'],
    shadowLine: tokens['chart-shadow-line'],
    shadowArea: tokens['chart-shadow-area'],
    panel: tokens.panel,
    surface: tokens.surface,
    area: tokens['chart-area'],
  };
}
