import { useRef, useState } from 'react';
import { Modal, Pressable, ScrollView, StyleSheet, Text, useWindowDimensions, View } from 'react-native';

export type SelectDropdownOption = {
  value: string;
  label: string;
  disabled?: boolean;
};

export function SelectDropdown({
  label,
  value,
  options,
  onChange,
}: {
  label: string;
  value: string;
  options: SelectDropdownOption[];
  onChange: (value: string) => void;
}) {
  const anchorRef = useRef<View>(null);
  const { width: viewportWidth, height: viewportHeight } = useWindowDimensions();
  const [open, setOpen] = useState(false);
  const [triggerHovered, setTriggerHovered] = useState(false);
  const [hoveredValue, setHoveredValue] = useState('');
  const [menuLayout, setMenuLayout] = useState({ top: 0, left: 8, width: 240 });
  const selected = options.find((option) => option.value === value);

  function toggle() {
    if (open) {
      setOpen(false);
      return;
    }
    anchorRef.current?.measureInWindow((x, y, width, height) => {
      const menuHeight = Math.min(252, options.length * 44 + 12);
      const below = y + height + 6;
      const top = below + menuHeight <= viewportHeight - 8
        ? below
        : Math.max(8, y - menuHeight - 6);
      setMenuLayout({
        top,
        left: Math.min(Math.max(8, x), Math.max(8, viewportWidth - width - 8)),
        width,
      });
      setOpen(true);
    });
  }

  return <View ref={anchorRef} style={styles.anchor}>
    <Pressable
      accessibilityRole="combobox"
      accessibilityLabel={label}
      accessibilityState={{ expanded: open }}
      onHoverIn={() => setTriggerHovered(true)}
      onHoverOut={() => setTriggerHovered(false)}
      onPress={toggle}
      style={[styles.trigger, (triggerHovered || open) && styles.triggerHovered, open && styles.triggerOpen]}
    >
      <Text numberOfLines={1} style={styles.value}>{selected?.label || value}</Text>
      <Text style={[styles.chevron, open && styles.chevronOpen]}>⌄</Text>
    </Pressable>

    <Modal transparent visible={open} animationType="fade" onRequestClose={() => setOpen(false)}>
      <View style={styles.portal}>
        <Pressable accessibilityRole="none" style={[StyleSheet.absoluteFill, styles.dismissLayer]} onPress={() => setOpen(false)} />
        <ScrollView accessibilityRole="menu" style={[styles.menu, menuLayout]} contentContainerStyle={styles.menuContent}>
          {options.map((option) => {
            const isSelected = option.value === value;
            const isHovered = option.value === hoveredValue;
            return <Pressable
              key={option.value}
              accessibilityRole="menuitem"
              accessibilityState={{ disabled: option.disabled, selected: isSelected }}
              disabled={option.disabled}
              onHoverIn={() => setHoveredValue(option.value)}
              onHoverOut={() => setHoveredValue('')}
              onPress={() => {
                onChange(option.value);
                setOpen(false);
              }}
              style={[styles.item, isHovered && styles.itemHovered, isSelected && styles.itemSelected, option.disabled && styles.itemDisabled]}
            >
              <Text style={[styles.itemLabel, isHovered && styles.itemLabelHovered, isSelected && styles.itemLabelSelected]}>{option.label}</Text>
              {isSelected ? <Text style={styles.check}>✓</Text> : null}
            </Pressable>;
          })}
        </ScrollView>
      </View>
    </Modal>
  </View>;
}

const styles = StyleSheet.create({
  anchor: { width: '100%' },
  trigger: { width: '100%', minHeight: 42, flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', gap: 10, backgroundColor: '#0b0f19', borderWidth: 1, borderColor: 'rgba(59,130,246,.35)', borderRadius: 8, paddingHorizontal: 14, boxShadow: 'inset 0 2px 4px rgba(0,0,0,.4), 0 1px 3px rgba(0,0,0,.2)' },
  triggerHovered: { borderColor: '#60a5fa', backgroundColor: '#101622', boxShadow: 'inset 0 2px 4px rgba(0,0,0,.3), 0 0 12px rgba(59,130,246,.25)' },
  triggerOpen: { borderColor: '#3b82f6', boxShadow: '0 0 0 3px rgba(59,130,246,.3), inset 0 2px 4px rgba(0,0,0,.3)' },
  value: { flex: 1, color: '#f8fafc', fontSize: 13, fontWeight: '700' },
  chevron: { flexShrink: 0, color: '#94a3b8', fontSize: 18, lineHeight: 18, transform: [{ rotate: '0deg' }] },
  chevronOpen: { transform: [{ rotate: '180deg' }] },
  portal: { flex: 1 },
  dismissLayer: { cursor: 'auto' },
  menu: { position: 'absolute', maxHeight: 252, backgroundColor: 'rgba(13,19,33,.98)', borderWidth: 1, borderColor: 'rgba(59,130,246,.4)', borderRadius: 8, boxShadow: '0 16px 40px rgba(0,0,0,.85), 0 0 20px rgba(59,130,246,.2)' },
  menuContent: { padding: 6, gap: 3 },
  item: { minHeight: 38, flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', gap: 8, paddingHorizontal: 12, paddingVertical: 9, borderRadius: 6, borderWidth: 1, borderColor: 'transparent', transform: [{ translateX: 0 }] },
  itemHovered: { backgroundColor: 'rgba(59,130,246,.18)', borderColor: 'rgba(96,165,250,.3)', transform: [{ translateX: 2 }] },
  itemSelected: { backgroundColor: 'rgba(37,99,235,.25)', borderColor: 'rgba(59,130,246,.5)' },
  itemDisabled: { opacity: 0.4 },
  itemLabel: { flex: 1, color: '#cbd5e1', fontSize: 13, fontWeight: '600' },
  itemLabelHovered: { color: '#ffffff' },
  itemLabelSelected: { color: '#60a5fa', fontWeight: '800' },
  check: { color: '#60a5fa', fontSize: 13, fontWeight: '800' },
});
