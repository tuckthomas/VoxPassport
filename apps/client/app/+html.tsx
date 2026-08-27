import { ScrollViewStyleReset } from 'expo-router/html';
import type { PropsWithChildren } from 'react';

export default function Root({ children }: PropsWithChildren) {
  return (
    <html lang="en">
      <head>
        <meta charSet="utf-8" />
        <meta httpEquiv="X-UA-Compatible" content="IE=edge" />
        <meta name="viewport" content="width=device-width, initial-scale=1, shrink-to-fit=no" />
        <link rel="preconnect" href="https://fonts.googleapis.com" />
        <link rel="preconnect" href="https://fonts.gstatic.com" crossOrigin="anonymous" />
        <link
          href="https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@500;600&amp;family=Plus+Jakarta+Sans:wght@400;500;600;700;800&amp;display=swap"
          rel="stylesheet"
        />
        <ScrollViewStyleReset />
        <style dangerouslySetInnerHTML={{ __html: `
          html, body, #root { height: 100%; background: #090d16; }
          body { margin: 0; overflow: hidden; }
          * { box-sizing: border-box; scrollbar-width: thin; scrollbar-color: rgba(59,130,246,.28) transparent; }
          *::-webkit-scrollbar { width: 6px; height: 6px; }
          *::-webkit-scrollbar-thumb { background: rgba(59,130,246,.25); border-radius: 10px; }
        ` }} />
      </head>
      <body>{children}</body>
    </html>
  );
}
