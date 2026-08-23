import { Link } from 'expo-router';
import { Text, View } from 'react-native';
import { Card } from '@/components/Card';
import { Screen } from '@/components/Screen';
import { colors } from '@/theme';

const destinations = [
  ['/models', 'Models & Engines', 'Select local or provider-backed translation engines.'],
  ['/voice-profiles', 'Voice Profiles', 'Manage speaker reference profiles and cloning state.'],
  ['/runtime', 'Runtime & Audio', 'Inspect the local runtime and desktop audio capabilities.'],
  ['/settings', 'Settings', 'Choose local/self-hosted targets and connection settings.'],
] as const;

export default function HomeScreen() {
  return (
    <Screen title="VoxPassport" subtitle="Provider-agnostic live speech translation. Desktop first; local by default.">
      <Card>
        <Text style={{ color: colors.text, fontSize: 18, fontWeight: '700' }}>Translator</Text>
        <Text style={{ color: colors.muted, marginTop: 8 }}>
          The legacy Studio remains available during migration. The new client is being rebuilt around typed runtime and audio boundaries rather than iframe patches.
        </Text>
      </Card>
      <View style={{ gap: 12 }}>
        {destinations.map(([href, title, detail]) => (
          <Link key={href} href={href} style={{ textDecorationLine: 'none' }}>
            <Card>
              <Text style={{ color: colors.text, fontSize: 16, fontWeight: '700' }}>{title}</Text>
              <Text style={{ color: colors.muted, marginTop: 6 }}>{detail}</Text>
            </Card>
          </Link>
        ))}
      </View>
    </Screen>
  );
}
