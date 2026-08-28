import { StyleSheet, View } from 'react-native';

export function TrashIcon({ size = 14, color = '#ef4444' }: { size?: number; color?: string }) {
  const stroke = Math.max(1.25, size * 0.12);
  return <View pointerEvents="none" style={[styles.root, { width: size, height: size }]}>
    <View style={[styles.handle, { width: size * 0.34, height: stroke, top: size * 0.04, left: size * 0.33, backgroundColor: color, borderRadius: stroke }]} />
    <View style={[styles.lid, { width: size * 0.86, height: stroke, top: size * 0.22, left: size * 0.07, backgroundColor: color, borderRadius: stroke }]} />
    <View style={[styles.bin, { width: size * 0.62, height: size * 0.58, left: size * 0.19, bottom: size * 0.04, borderWidth: stroke, borderColor: color, borderRadius: size * 0.08 }]}>
      <View style={[styles.slot, { width: stroke, backgroundColor: color }]} />
      <View style={[styles.slot, { width: stroke, backgroundColor: color }]} />
    </View>
  </View>;
}

const styles = StyleSheet.create({
  root: { position: 'relative' },
  handle: { position: 'absolute' },
  lid: { position: 'absolute' },
  bin: { position: 'absolute', flexDirection: 'row', alignItems: 'center', justifyContent: 'space-evenly' },
  slot: { height: '64%', borderRadius: 2 },
});
