export const theme = {
  colors: {
    background: '#0A0F18',
    surface: '#121A26',
    surfaceRaised: '#192435',
    border: '#29384D',
    text: '#F5F7FA',
    muted: '#9BAABD',
    accent: '#55A7FF',
    success: '#4BC28B',
    warning: '#F2B84B',
    danger: '#F06A6A',
  },
  spacing: {
    xs: 6,
    sm: 10,
    md: 16,
    lg: 24,
    xl: 32,
  },
  radius: {
    sm: 8,
    md: 12,
    lg: 18,
  },
} as const;

export const colors = theme.colors;
