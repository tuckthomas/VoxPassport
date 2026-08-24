import { Link } from 'expo-router';
import { Pressable, Text, View } from 'react-native';
import { useAuth } from '@/auth/AuthContext';
import { Card } from '@/components/Card';
import { Screen } from '@/components/Screen';
import { colors } from '@/theme';

const baseDestinations = [
  ['/translator', 'Translator', 'Use the selected local/self-hosted runtime for translation.'],
  ['/models', 'Models & Engines', 'Inspect local or provider-backed translation engines.'],
  ['/voice-profiles', 'Voice Profiles', 'Manage speaker reference profiles and cloning state.'],
  ['/runtime', 'Runtime & Audio', 'Inspect the local runtime and desktop audio capabilities.'],
  ['/settings', 'Settings', 'Choose runtime targets and provider/runtime configuration.'],
] as const;

export default function HomeScreen() {
  const auth = useAuth();
  const destinations = auth.enabled
    ? [
        ...baseDestinations.slice(0, 4),
        ['/account', 'Account', 'Sign in, create an account, and manage account sessions.'] as const,
        baseDestinations[4],
      ]
    : baseDestinations;

  return (
    <Screen title="VoxPassport" subtitle="Provider-agnostic live speech translation. Desktop first; local by default.">
      <Card>
        <Text style={{ color: colors.text, fontSize: 18, fontWeight: '700' }}>
          {auth.localOnly ? 'Local-only deployment' : 'VoxPassport runtime'}
        </Text>
        <Text style={{ color: colors.muted, marginTop: 8 }}>
          {auth.localOnly
            ? 'Accounts and multi-user cloud controls are disabled. Translation runs against the configured local/private runtime.'
            : 'Local/private inference remains first-class; account features are available only where the deployment enables them.'}
        </Text>
      </Card>
      <View style={{ gap: 12 }}>
        {destinations.map(([href, title, detail]) => (
          <Link key={href} href={href} asChild>
            <Pressable>
              <Card>
                <Text style={{ color: colors.text, fontSize: 16, fontWeight: '700' }}>{title}</Text>
                <Text style={{ color: colors.muted, marginTop: 6 }}>{detail}</Text>
              </Card>
            </Pressable>
          </Link>
        ))}
      </View>
    </Screen>
  );
}
