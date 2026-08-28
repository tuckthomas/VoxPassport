import { StyleSheet, Text, View } from 'react-native';

export function AudioFilePicker({ onSelect: _onSelect }: { onSelect: (uri: string, name: string) => void }) {
  return <View style={styles.zone}>
    <Text style={styles.title}>Select WAV, MP3, or M4A reference audio</Text>
    <Text style={styles.hint}>Native file selection will be enabled with the desktop packaging workflow.</Text>
  </View>;
}

const styles = StyleSheet.create({
  zone: { minHeight: 120, alignItems: 'center', justifyContent: 'center', padding: 10, backgroundColor: '#101622', borderWidth: 1, borderStyle: 'dashed', borderColor: '#25334a', borderRadius: 4 },
  title: { color: '#f8fafc', fontSize: 14, fontWeight: '600', textAlign: 'center' },
  hint: { marginTop: 6, color: '#94a3b8', fontSize: 13, textAlign: 'center' },
});
