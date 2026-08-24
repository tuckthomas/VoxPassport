export type AccountUser = {
  id: string;
  email: string;
  display_name: string | null;
  email_verified: boolean;
  is_active: boolean;
  created_at: string;
  last_login_at: string | null;
};

export type AuthResponse = {
  access_token: string;
  token_type: 'bearer';
  expires_in_seconds: number;
  refresh_token: string | null;
  user: AccountUser;
};

export type ProviderCredentialSummary = {
  id: string;
  provider: string;
  label: string;
  key_version: number;
  created_at: string;
  updated_at: string;
};
