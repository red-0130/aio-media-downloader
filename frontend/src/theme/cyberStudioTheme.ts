import { defineTheme } from '@astryxdesign/core';
import { neutralTheme } from '@astryxdesign/theme-neutral';

export const cyberStudioTheme = defineTheme({
  name: 'cyber-studio',
  tokens: {
    ...neutralTheme.__inputTokens,
    // Cyber Media Studio palette: Deep midnight slate with vibrant indigo/electric violet accents
    '--color-accent': ['#6366f1', '#818cf8'],
    '--color-accent-muted': ['#4f46e5', '#6366f1'],
    '--color-background-surface': ['#090d16', '#090d16'],
    '--color-background-card': ['#0f172a', '#0f172a'],
    '--color-background-muted': ['#1e293b', '#1e293b'],
    '--color-border': ['#1e293b', '#334155'],
    '--radius-container': '16px',
    '--radius-element': '12px',
  },
  icons: neutralTheme.icons,
});
