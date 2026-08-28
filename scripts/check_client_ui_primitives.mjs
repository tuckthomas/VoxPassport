import { readFileSync, readdirSync } from 'node:fs';
import { extname, join, relative } from 'node:path';
import { fileURLToPath } from 'node:url';

const root = fileURLToPath(new URL('../apps/client/', import.meta.url));
const raisedButton = fileURLToPath(new URL('../apps/client/src/components/RaisedButton.tsx', import.meta.url));
const raisedNavLink = fileURLToPath(new URL('../apps/client/src/components/RaisedNavLink.tsx', import.meta.url));
const studioShell = fileURLToPath(new URL('../apps/client/src/components/StudioShell.tsx', import.meta.url));
const failures = [];

for (const file of walk(root)) {
  if (!['.tsx', '.ts', '.jsx', '.js', '.css', '.scss'].includes(extname(file))) continue;
  const source = readFileSync(file, 'utf8');
  const display = relative(root, file).replaceAll('\\', '/');
  const isSharedButtonPrimitive = file.endsWith('RaisedButton.tsx');
  if (/\btext-xs\b/.test(source)) failures.push(`${display}: text-xs is forbidden; use typography larger than xs`);
  for (const match of source.matchAll(/\bfontSize\s*:\s*(\d+(?:\.\d+)?)/g)) {
    if (!isSharedButtonPrimitive && Number(match[1]) < 13) failures.push(`${display}: fontSize ${match[1]} is below the enforced 13px minimum outside the shared button primitive`);
  }
  for (const match of source.matchAll(/\bfont-size\s*:\s*(\d+(?:\.\d+)?)px/gi)) {
    if (Number(match[1]) < 13) failures.push(`${display}: font-size ${match[1]}px is below the enforced 13px minimum`);
  }
  if (!['.tsx', '.ts'].includes(extname(file)) || file.endsWith('RaisedButton.tsx') || file.endsWith('IconButton.tsx')) continue;
  for (const match of source.matchAll(/<Pressable\b[\s\S]*?>/g)) {
    const tag = match[0];
    if (!tag.includes('onPress=')) continue;
    if (!tag.includes('accessibilityRole=')) failures.push(`${display}: interactive Pressable must declare a non-button semantic role or use RaisedButton`);
    if (/accessibilityRole=["']button["']/.test(tag)) failures.push(`${display}: buttons must use the shared RaisedButton component`);
    if (/style=\{buttonStyle\}/.test(tag)) failures.push(`${display}: local buttonStyle bypasses the shared raised-button primitive`);
  }
}

const primitive = readFileSync(raisedButton, 'utf8');
for (const contract of ['darken(backgroundColor', 'const raisedDepth = compact ? 3 : 6', '0 ${raisedDepth}px 0 ${depth}', 'const depressed = pressed || latched', '0 1px 0 ${depth}', 'accessibilityRole="button"']) {
  if (!primitive.includes(contract)) failures.push(`RaisedButton.tsx: missing raised-button contract ${JSON.stringify(contract)}`);
}

const navigationPrimitive = readFileSync(raisedNavLink, 'utf8');
if (!navigationPrimitive.includes("raisedControlSurface('#2563eb'")) failures.push('RaisedNavLink.tsx: navigation must use the shared raised-control surface');
const shell = readFileSync(studioShell, 'utf8');
if (!shell.includes('<RaisedNavLink')) failures.push('StudioShell.tsx: primary navigation must use RaisedNavLink');
if (shell.includes('function SidebarNav')) failures.push('StudioShell.tsx: primary navigation must not restore a local navigation-button implementation');

if (failures.length) {
  console.error('Client UI primitive enforcement failed:\n' + failures.map((failure) => `- ${failure}`).join('\n'));
  process.exit(1);
}
console.log('Client UI primitives and minimum 13px non-button typography are enforced.');

function* walk(directory) {
  for (const entry of readdirSync(directory, { withFileTypes: true })) {
    if (entry.name === 'node_modules' || entry.name === '.expo' || entry.name === 'dist') continue;
    const path = join(directory, entry.name);
    if (entry.isDirectory()) yield* walk(path);
    else yield path;
  }
}
