import type { ReactNode } from 'react';
import { useRef, useState } from 'react';
import { Modal, Pressable, StyleSheet, Text, View } from 'react-native';
import { IconButton } from '@/components/IconButton';

export type DropdownMenuItem = { key: string; label: string; icon?: ReactNode; disabled?: boolean; danger?: boolean; onPress: () => void };

const MENU_WIDTH = 212;

export function DropdownMenu({ label, items }: { label: string; items: DropdownMenuItem[] }) {
  const [open, setOpen] = useState(false);
  const [hoveredKey, setHoveredKey] = useState('');
  const anchorRef = useRef<View>(null);
  const [position, setPosition] = useState({ top: 0, left: 8 });

  function toggleMenu() {
    if (open) {
      setOpen(false);
      return;
    }
    anchorRef.current?.measureInWindow((x, y, width, height) => {
      setPosition({ top: y + height + 6, left: Math.max(8, x + width - MENU_WIDTH) });
      setOpen(true);
    });
  }

  return <View ref={anchorRef} style={styles.anchor}>
    <IconButton label={label} onPress={toggleMenu}><Text style={styles.trigger}>⋮</Text></IconButton>
    <Modal transparent visible={open} animationType="fade" onRequestClose={() => setOpen(false)}>
      <View style={styles.portal}>
        <Pressable accessibilityRole="none" style={[StyleSheet.absoluteFill, styles.dismissLayer]} onPress={() => setOpen(false)} />
        <View accessibilityRole="menu" style={[styles.menu, position]}>{items.map((item) => <Pressable key={item.key} accessibilityRole="menuitem" accessibilityState={{ disabled: item.disabled }} disabled={item.disabled} onHoverIn={() => setHoveredKey(item.key)} onHoverOut={() => setHoveredKey('')} onPress={() => { setOpen(false); item.onPress(); }} style={({ pressed }) => [styles.item, (pressed || hoveredKey === item.key) && styles.itemPressed, item.disabled && styles.itemDisabled]}><View style={styles.itemIcon}>{typeof item.icon === 'string' || !item.icon ? <Text style={[styles.itemIconText, hoveredKey === item.key && styles.itemHoveredText]}>{item.icon || '•'}</Text> : item.icon}</View><Text style={[styles.itemLabel, hoveredKey === item.key && styles.itemHoveredText, item.danger && styles.danger]}>{item.label}</Text></Pressable>)}</View>
      </View>
    </Modal>
  </View>;
}

const styles = StyleSheet.create({
  anchor: { position: 'relative' }, trigger: { color: '#94a3b8', fontSize: 18, lineHeight: 18 },
  portal: { flex: 1 },
  dismissLayer: { cursor: 'auto' },
  menu: { position: 'absolute', width: MENU_WIDTH, padding: 6, gap: 3, backgroundColor: 'rgba(13,19,33,.98)', borderWidth: 1, borderColor: 'rgba(59,130,246,.4)', borderRadius: 8, boxShadow: '0 16px 40px rgba(0,0,0,.85), 0 0 20px rgba(59,130,246,.2)' },
  item: { minHeight: 34, paddingHorizontal: 10, flexDirection: 'row', alignItems: 'center', gap: 8, borderWidth: 1, borderColor: 'transparent', borderRadius: 6 }, itemPressed: { backgroundColor: 'rgba(59,130,246,.18)', borderColor: 'rgba(96,165,250,.3)', transform: [{ translateX: 2 }] }, itemDisabled: { opacity: 0.4 }, itemIcon: { width: 16, alignItems: 'center', justifyContent: 'center' }, itemIconText: { color: '#94a3b8', fontSize: 13 }, itemLabel: { flex: 1, color: '#cbd5e1', fontSize: 13 }, itemHoveredText: { color: '#ffffff' }, danger: { color: '#f87171' },
});
