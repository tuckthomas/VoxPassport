import type { PropsWithChildren, ReactNode } from 'react';
import { RaisedButton } from '@/components/RaisedButton';
import { WidgetCard } from '@/components/WidgetCard';
import { theme } from '@/theme';

export function Card({ title, subtitle, children, action }: PropsWithChildren<{ title?: string; subtitle?: string; action?: ReactNode }>) {
  return <WidgetCard title={title} subtitle={subtitle} action={action}>{children}</WidgetCard>;
}

export function ActionButton({
  label,
  onPress,
  disabled = false,
  destructive = false,
}: {
  label: string;
  onPress: () => void;
  disabled?: boolean;
  destructive?: boolean;
}) {
  return <RaisedButton label={label} disabled={disabled} onPress={onPress} backgroundColor={destructive ? theme.colors.danger : theme.colors.accent} />;
}
