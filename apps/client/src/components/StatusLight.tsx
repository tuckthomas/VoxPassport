import { StyleSheet, View } from 'react-native';

export type StatusLightTone = 'green' | 'white' | 'red' | 'off';

const tones = {
  green: { core: '#34d399', edge: '#166534', shadow: 'rgba(52,211,153,.58)' },
  white: { core: '#f1f5f9', edge: '#64748b', shadow: 'rgba(241,245,249,.5)' },
  red: { core: '#f87171', edge: '#7f1d1d', shadow: 'rgba(248,113,113,.42)' },
  off: { core: '#26303a', edge: '#111827', shadow: 'transparent' },
} as const;

export function StatusLight({ tone = 'green', size = 8 }: { tone?: StatusLightTone; size?: number }) {
  const colors = tones[tone];
  const lit = tone !== 'off';
  return <View pointerEvents="none" style={[styles.root, { width: size, height: size }]}>
    <View style={[styles.bezel, { width: size, height: size, borderRadius: size / 2 }]}> 
      <View style={[styles.core, {
        width: size * 0.58,
        height: size * 0.58,
        borderRadius: size * 0.29,
        backgroundColor: colors.core,
        borderColor: colors.edge,
        boxShadow: lit ? `inset 0 0 1px rgba(255,255,255,.32), 0 0 ${Math.max(3, Math.round(size * 0.55))}px ${colors.shadow}` : 'inset 0 1px 2px rgba(0,0,0,.9)',
      }]} />
    </View>
  </View>;
}

const styles = StyleSheet.create({
  root: { position: 'relative', alignItems: 'center', justifyContent: 'center' },
  bezel: { alignItems: 'center', justifyContent: 'center', backgroundColor: '#05070a', borderWidth: 1, borderColor: '#202833', boxShadow: 'inset 0 1px 2px rgba(0,0,0,.95)' },
  core: { borderWidth: 0.5 },
});
